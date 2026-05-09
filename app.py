import os
import requests
import asyncio
import random
import threading
import time
import socket
import logging
import struct
from flask import Flask, jsonify
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional, Tuple, List
import re

# ==========================================
# --- 0. الإعدادات والتهيئة ---
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==========================================
# --- 1. بيانات SSH الجديدة ---
# ==========================================
@dataclass
class SSHConfig:
    host: str = "152.228.162.19"
    domain: str = "ov-france1.09vpn.com"
    username: str = "u3846367053"
    password: str = "pklsopdfsdf"
    ports: tuple = (109, 143)  # Dropbear ports

SSH = SSHConfig()

# Telegram
TOKEN = os.environ.get("BOT_TOKEN", "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

# Target ranges للبحث (Ooredoo/اتصالات موريتانيا)
TARGET_RANGES = [
    (34, 0, 0, 0, 34, 255, 255, 255),    # 34.x.x.x
    (35, 0, 0, 0, 35, 255, 255, 255),    # 35.x.x.x
    (41, 188, 0, 0, 41, 188, 255, 255),  # 41.188.x.x (Mauritania)
    (41, 221, 0, 0, 41, 221, 255, 255),  # 41.221.x.x
    (196, 32, 0, 0, 196, 32, 255, 255),  # 196.32.x.x
]

# البورتات المستهدفة للبروكسي
PROXY_PORTS = [80, 8080, 3128, 8000, 8888, 8118, 1080, 808, 8008, 81, 82, 83, 8081, 8082, 8083]

app = Flask(__name__)

# ==========================================
# --- 2. حالة النظام ---
# ==========================================
class HunterState:
    def __init__(self):
        self.lock = threading.Lock()
        self.hunting = False
        self.chat_id = None
        self.status_msg_id = None
        
        # إحصائيات
        self.scanned = 0
        self.responded = 0
        self.tested = 0
        self.working = 0
        self.blocked_307 = 0
        
        # النتائج
        self.working_proxies: List[dict] = []
        self.validation_queue = Queue()
        
        # التحكم
        self.start_time = None
        self.last_found_time = None
    
    def reset(self):
        with self.lock:
            self.scanned = 0
            self.responded = 0
            self.tested = 0
            self.working = 0
            self.blocked_307 = 0
            self.working_proxies = []
            self.status_msg_id = None
            self.start_time = time.time()
            self.last_found_time = None
            # تفريغ الطابور
            while not self.validation_queue.empty():
                try:
                    self.validation_queue.get_nowait()
                except Empty:
                    break
    
    def increment(self, field: str, value: int = 1):
        with self.lock:
            setattr(self, field, getattr(self, field) + value)
    
    def get_stats(self) -> dict:
        with self.lock:
            elapsed = time.time() - self.start_time if self.start_time else 0
            rate = self.scanned / elapsed if elapsed > 0 else 0
            return {
                "scanned": self.scanned,
                "responded": self.responded,
                "tested": self.tested,
                "working": self.working,
                "blocked": self.blocked_307,
                "elapsed": int(elapsed),
                "rate": int(rate)
            }

state = HunterState()

# ==========================================
# --- 3. فحص SSH الحقيقي عبر البروكسي ---
# ==========================================
class SSHProxyChecker:
    """فاحص SSH حقيقي - يتصل فعلياً بسيرفر SSH عبر البروكسي"""
    
    # Payloads مختلفة للتجربة
    PAYLOADS = [
        # Payload 1: Standard CONNECT
        lambda host, port, domain: (
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: {domain}\r\n"
            f"Proxy-Connection: Keep-Alive\r\n\r\n"
        ),
        # Payload 2: With fake host
        lambda host, port, domain: (
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: www.youtube.com\r\n"
            f"X-Online-Host: www.youtube.com\r\n"
            f"Connection: Keep-Alive\r\n\r\n"
        ),
        # Payload 3: Split injection style
        lambda host, port, domain: (
            f"CONNECT {host}:{port}@www.google.com HTTP/1.1\r\n"
            f"Host: www.google.com\r\n\r\n"
        ),
        # Payload 4: WebSocket upgrade fake
        lambda host, port, domain: (
            f"GET / HTTP/1.1\r\n"
            f"Host: {domain}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n\r\n"
            f"CONNECT {host}:{port} HTTP/1.1\r\n\r\n"
        ),
    ]
    
    # ردود الحظر المعروفة
    BLOCKED_PATTERNS = [
        "307 Temporary Redirect",
        "choof.mr",
        "ooredoo",
        "blocked",
        "forbidden",
        "captive",
        "portal",
        "302 Found",
        "301 Moved",
        "تم حظر",
        "محظور"
    ]
    
    @staticmethod
    def check_proxy(proxy_ip: str, proxy_port: int, timeout: float = 15) -> dict:
        """
        فحص شامل للبروكسي مع محاولة اتصال SSH حقيقي
        """
        result = {
            "ip": proxy_ip,
            "port": proxy_port,
            "success": False,
            "ssh_connected": False,
            "ping": 0,
            "payload_used": None,
            "ssh_banner": None,
            "error": None,
            "blocked": False,
            "block_reason": None
        }
        
        # جرب كل payload
        for idx, payload_func in enumerate(SSHProxyChecker.PAYLOADS):
            for ssh_port in SSH.ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    
                    start = time.time()
                    sock.connect((proxy_ip, proxy_port))
                    
                    # إرسال الـ payload
                    payload = payload_func(SSH.host, ssh_port, SSH.domain)
                    sock.sendall(payload.encode())
                    
                    # استقبال الرد
                    response = b""
                    try:
                        while True:
                            chunk = sock.recv(4096)
                            if not chunk:
                                break
                            response += chunk
                            if len(response) > 1024 or b"\r\n\r\n" in response:
                                break
                    except socket.timeout:
                        pass
                    
                    response_text = response.decode(errors='ignore')
                    ping = int((time.time() - start) * 1000)
                    result["ping"] = ping
                    
                    # فحص الحظر
                    for pattern in SSHProxyChecker.BLOCKED_PATTERNS:
                        if pattern.lower() in response_text.lower():
                            result["blocked"] = True
                            result["block_reason"] = pattern
                            sock.close()
                            return result
                    
                    # فحص نجاح الاتصال
                    if "200 Connection established" in response_text or "HTTP/1.1 200" in response_text or "HTTP/1.0 200" in response_text:
                        result["success"] = True
                        result["payload_used"] = idx + 1
                        
                        # محاولة قراءة SSH banner
                        try:
                            sock.settimeout(5)
                            ssh_banner = sock.recv(256).decode(errors='ignore')
                            if "SSH-" in ssh_banner:
                                result["ssh_connected"] = True
                                result["ssh_banner"] = ssh_banner.strip()
                                
                                # محاولة المصادقة (اختياري - للتأكد)
                                # لا نكمل المصادقة الكاملة هنا، فقط نتأكد من الـ banner
                        except:
                            pass
                        
                        sock.close()
                        return result
                    
                    sock.close()
                    
                except socket.timeout:
                    result["error"] = "Timeout"
                except ConnectionRefusedError:
                    result["error"] = "Refused"
                except Exception as e:
                    result["error"] = str(e)[:50]
        
        return result

# ==========================================
# --- 4. مولد العناوين الذكي ---
# ==========================================
class IPGenerator:
    """مولد IP ذكي مع أولوية للنطاقات المعروفة"""
    
    @staticmethod
    def generate_targeted() -> str:
        """توليد IP من النطاقات المستهدفة"""
        if random.random() < 0.7:  # 70% من النطاقات المستهدفة
            range_choice = random.choice(TARGET_RANGES)
            return f"{random.randint(range_choice[0], range_choice[4])}.{random.randint(range_choice[1], range_choice[5])}.{random.randint(range_choice[2], range_choice[6])}.{random.randint(range_choice[3], range_choice[7])}"
        else:  # 30% عشوائي
            return f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    
    @staticmethod
    def generate_batch(size: int = 50) -> List[Tuple[str, int]]:
        """توليد مجموعة من العناوين مع البورتات"""
        batch = []
        for _ in range(size):
            ip = IPGenerator.generate_targeted()
            # اختر بورتات عشوائية (3 بورتات لكل IP)
            ports = random.sample(PROXY_PORTS, min(3, len(PROXY_PORTS)))
            for port in ports:
                batch.append((ip, port))
        return batch

# ==========================================
# --- 5. الماسح السريع (Async) ---
# ==========================================
class FastScanner:
    """ماسح سريع للكشف عن البورتات المفتوحة"""
    
    QUICK_PAYLOAD = b"CONNECT 152.228.162.19:109 HTTP/1.1\r\nHost: youtube.com\r\n\r\n"
    
    @staticmethod
    async def quick_check(ip: str, port: int, semaphore: asyncio.Semaphore) -> Optional[Tuple[str, int]]:
        """فحص سريع - هل البورت مفتوح ويرد؟"""
        async with semaphore:
            state.increment("scanned")
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=2.0
                )
                
                writer.write(FastScanner.QUICK_PAYLOAD)
                await writer.drain()
                
                data = await asyncio.wait_for(reader.read(128), timeout=2.0)
                
                writer.close()
                try:
                    await writer.wait_closed()
                except:
                    pass
                
                if len(data) > 10:
                    response = data.decode(errors='ignore').lower()
                    # تجاهل الردود المحظورة مباشرة
                    if any(blocked in response for blocked in ['307', 'choof', 'ooredoo', 'redirect']):
                        state.increment("blocked_307")
                        return None
                    
                    state.increment("responded")
                    return (ip, port)
                    
            except:
                pass
            return None
    
    @staticmethod
    async def scan_batch(targets: List[Tuple[str, int]], concurrency: int = 500) -> List[Tuple[str, int]]:
        """مسح مجموعة من الأهداف"""
        semaphore = asyncio.Semaphore(concurrency)
        tasks = [FastScanner.quick_check(ip, port, semaphore) for ip, port in targets]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

# ==========================================
# --- 6. نظام التحقق العميق ---
# ==========================================
class DeepValidator:
    """محقق عميق - يفحص SSH الحقيقي"""
    
    def __init__(self, workers: int = 10):
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.running = False
    
    def start(self):
        self.running = True
        threading.Thread(target=self._worker_loop, daemon=True).start()
    
    def stop(self):
        self.running = False
    
    def _worker_loop(self):
        logger.info("🔍 Deep Validator started")
        while self.running:
            try:
                ip, port = state.validation_queue.get(timeout=1)
                state.increment("tested")
                
                result = SSHProxyChecker.check_proxy(ip, port)
                
                if result["blocked"]:
                    state.increment("blocked_307")
                    self._send_blocked_notification(result)
                elif result["success"]:
                    state.increment("working")
                    state.working_proxies.append(result)
                    state.last_found_time = time.time()
                    self._send_success_notification(result)
                    
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Validator error: {e}")
    
    def _send_success_notification(self, result: dict):
        """إرسال إشعار النجاح"""
        ssh_status = "✅ SSH Banner Received!" if result["ssh_connected"] else "⚠️ 200 OK (No SSH Banner)"
        
        msg = (
            f"🎉 **PROXY FOUND!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 **Proxy:** `{result['ip']}:{result['port']}`\n"
            f"⚡ **Ping:** `{result['ping']}ms`\n"
            f"🔧 **Payload:** #{result['payload_used']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔐 **SSH Status:** {ssh_status}\n"
        )
        
        if result["ssh_banner"]:
            msg += f"📡 **Banner:** `{result['ssh_banner'][:50]}`\n"
        
        msg += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **SSH Config:**\n"
            f"```$$
\n"
$$
            f"Host: {SSH.host}\n"
            f"Port: {SSH.ports[0]} or {SSH.ports[1]}\n"
            f"User: {SSH.username}\n"
            f"Pass: {SSH.password}\n"
            f"```"
        )
        
        send_telegram(state.chat_id, msg)
    
    def _send_blocked_notification(self, result: dict):
        """إرسال إشعار الحظر (مجمع)"""
        # يتم إرسالها بشكل مجمع في التقرير
        pass

validator = DeepValidator()

# ==========================================
# --- 7. محرك الصيد الرئيسي ---
# ==========================================
async def hunting_engine():
    """المحرك الرئيسي للصيد"""
    logger.info("🚀 Hunting engine started")
    
    while state.hunting:
        try:
            # توليد دفعة جديدة
            targets = IPGenerator.generate_batch(100)
            
            # مسح سريع
            responding = await FastScanner.scan_batch(targets, concurrency=400)
            
            # إضافة للتحقق العميق
            for target in responding:
                state.validation_queue.put(target)
            
            # راحة قصيرة
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Hunting error: {e}")
            await asyncio.sleep(1)
    
    logger.info("🛑 Hunting engine stopped")

def start_hunting_engine():
    """بدء المحرك في thread منفصل"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(hunting_engine())

# ==========================================
# --- 8. نظام التقارير ---
# ==========================================
def report_worker():
    """عامل التقارير الدورية"""
    logger.info("📊 Report worker started")
    
    while True:
        if state.hunting and state.chat_id:
            try:
                stats = state.get_stats()
                
                # حساب الوقت
                elapsed = stats["elapsed"]
                hours, remainder = divmod(elapsed, 3600)
                minutes, seconds = divmod(remainder, 60)
                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                msg = (
                    f"📡 **SSH Hunter Pro - Live Stats**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 **Target:** `{SSH.domain}`\n"
                    f"🔌 **Ports:** `{SSH.ports[0]}, {SSH.ports[1]}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔍 **Scanned:** `{stats['scanned']:,}`\n"
                    f"📶 **Responded:** `{stats['responded']:,}`\n"
                    f"🔬 **Deep Tested:** `{stats['tested']:,}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ **Working:** `{stats['working']}`\n"
                    f"🚫 **Blocked (307):** `{stats['blocked']:,}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏱ **Time:** `{time_str}`\n"
                    f"⚡ **Speed:** `{stats['rate']:,}/s`\n"
                )
                
                if state.working_proxies:
                    msg += f"\n🏆 **Last Found:** `{state.working_proxies[-1]['ip']}:{state.working_proxies[-1]['port']}`"
                
                update_status_message(msg)
                
            except Exception as e:
                logger.error(f"Report error: {e}")
        
        time.sleep(5)

def update_status_message(text: str):
    """تحديث رسالة الحالة"""
    try:
        if state.status_msg_id:
            requests.post(
                f"{BASE_URL}/editMessageText",
                json={
                    "chat_id": state.chat_id,
                    "message_id": state.status_msg_id,
                    "text": text,
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        else:
            r = requests.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id": state.chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
            if r.status_code == 200:
                state.status_msg_id = r.json()["result"]["message_id"]
    except:
        pass

# ==========================================
# --- 9. مساعدات Telegram ---
# ==========================================
def send_telegram(chat_id: int, text: str, parse_mode: str = "Markdown"):
    """إرسال رسالة تيليجرام"""
    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            },
            timeout=10
        )
        logger.info(f"📤 Sent message to {chat_id}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Send failed: {e}")
        return False

# ==========================================
# --- 10. معالج أوامر البوت ---
# ==========================================
def handle_command(chat_id: int, text: str):
    """معالجة أوامر البوت"""
    
    if text == "/start":
        welcome = (
            f"👋 **مرحباً بك في SSH Hunter Pro!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 **SSH Server:**\n"
            f"• Host: `{SSH.domain}`\n"
            f"• IP: `{SSH.host}`\n"
            f"• Ports: `{SSH.ports[0]}, {SSH.ports[1]}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **الأوامر:**\n"
            f"• /hunt - بدء الصيد\n"
            f"• /stop - إيقاف الصيد\n"
            f"• /stats - الإحصائيات\n"
            f"• /proxies - البروكسيات الشغالة\n"
            f"• /test `IP:PORT` - فحص بروكسي محدد\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ يتم تجاهل بروكسيات 307 تلقائياً"
        )
        send_telegram(chat_id, welcome)
    
    elif text == "/hunt":
        if state.hunting:
            send_telegram(chat_id, "⚠️ الصيد يعمل بالفعل! استخدم /stop للإيقاف")
        else:
            state.hunting = True
            state.chat_id = chat_id
            state.reset()
            
            # بدء الخدمات
            threading.Thread(target=start_hunting_engine, daemon=True).start()
            validator.start()
            threading.Thread(target=report_worker, daemon=True).start()
            
            send_telegram(chat_id, "🚀 **تم بدء الصيد!**\nسيتم إرسال البروكسيات الشغالة فور اكتشافها...")
            logger.info(f"Hunting started by {chat_id}")
    
    elif text == "/stop":
        if state.hunting:
            state.hunting = False
            validator.stop()
            
            stats = state.get_stats()
            summary = (
                f"🛑 **تم إيقاف الصيد**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 **الملخص:**\n"
                f"• Scanned: `{stats['scanned']:,}`\n"
                f"• Working: `{stats['working']}`\n"
                f"• Blocked: `{stats['blocked']:,}`\n"
                f"• Time: `{stats['elapsed']}s`"
            )
            send_telegram(chat_id, summary)
            logger.info(f"Hunting stopped by {chat_id}")
        else:
            send_telegram(chat_id, "⚠️ الصيد متوقف بالفعل")
    
    elif text == "/stats":
        if state.hunting:
            stats = state.get_stats()
            msg = (
                f"📊 **الإحصائيات الحالية:**\n"
                f"• Scanned: `{stats['scanned']:,}`\n"
                f"• Responded: `{stats['responded']:,}`\n"
                f"• Tested: `{stats['tested']:,}`\n"
                f"• Working: `{stats['working']}`\n"
                f"• Blocked: `{stats['blocked']:,}`\n"
                f"• Speed: `{stats['rate']}/s`"
            )
            send_telegram(chat_id, msg)
        else:
            send_telegram(chat_id, "⚠️ الصيد متوقف. استخدم /hunt للبدء")
    
    elif text == "/proxies":
        if state.working_proxies:
            proxies_text = "\n".join([
                f"• `{p['ip']}:{p['port']}` ({p['ping']}ms)"
                for p in state.working_proxies[-10:]
            ])
            msg = f"✅ **آخر {min(10, len(state.working_proxies))} بروكسي شغال:**\n{proxies_text}"
            send_telegram(chat_id, msg)
        else:
            send_telegram(chat_id, "⚠️ لم يتم العثور على بروكسيات بعد")
    
    elif text.startswith("/test "):
        try:
            target = text.split(" ")[1]
            ip, port = target.split(":")
            port = int(port)
            
            send_telegram(chat_id, f"🔍 جاري فحص `{ip}:{port}`...")
            
            result = SSHProxyChecker.check_proxy(ip, port)
            
            if result["blocked"]:
                msg = f"🚫 **محظور!**\n• السبب: `{result['block_reason']}`"
            elif result["success"]:
                ssh_status = "✅ SSH يعمل!" if result["ssh_connected"] else "⚠️ 200 OK فقط"
                msg = (
                    f"✅ **يعمل!**\n"
                    f"• Ping: `{result['ping']}ms`\n"
                    f"• Payload: #{result['payload_used']}\n"
                    f"• SSH: {ssh_status}"
                )
                if result["ssh_banner"]:
                    msg += f"\n• Banner: `{result['ssh_banner'][:50]}`"
            else:
                msg = f"❌ **لا يعمل**\n• السبب: `{result['error']}`"
            
            send_telegram(chat_id, msg)
            
        except Exception as e:
            send_telegram(chat_id, f"❌ خطأ في الصيغة. استخدم: `/test IP:PORT`")

# ==========================================
# --- 11. البوت (Long Polling) ---
# ==========================================
def bot_polling():
    """حلقة استقبال رسائل تيليجرام"""
    time.sleep(3)  # انتظار Flask
    
    logger.info("🤖 Bot polling started")
    
    # حذف webhook
    try:
        requests.get(f"{BASE_URL}/deleteWebhook?drop_pending_updates=true", timeout=10)
        logger.info("Webhook deleted")
    except Exception as e:
        logger.error(f"Delete webhook failed: {e}")
    
    offset = None
    
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            
            r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=35)
            
            if r.status_code != 200:
                logger.warning(f"getUpdates failed: {r.status_code}")
                time.sleep(2)
                continue
            
            updates = r.json().get("result", [])
            
            for upd in updates:
                offset = upd["update_id"] + 1
                
                if "message" in upd and "text" in upd["message"]:
                    chat_id = upd["message"]["chat"]["id"]
                    text = upd["message"]["text"].strip()
                    
                    logger.info(f"📥 Received from {chat_id}: {text}")
                    handle_command(chat_id, text)
        
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(2)

# ==========================================
# --- 12. Flask Routes ---
# ==========================================
@app.route('/')
def home():
    stats = state.get_stats() if state.hunting else {}
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <title>SSH Hunter Pro</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial; background: #1a1a2e; color: #eee; padding: 20px; }}
            .card {{ background: #16213e; padding: 20px; border-radius: 10px; margin: 10px 0; }}
            .stat {{ font-size: 24px; color: #00ff88; }}
            h1 {{ color: #00ff88; }}
        </style>
    </head>
    <body>
        <h1>🎯 SSH Hunter Pro</h1>
        <div class="card">
            <h3>SSH Server</h3>
            <p>Host: {SSH.domain}</p>
            <p>IP: {SSH.host}</p>
            <p>Ports: {SSH.ports}</p>
        </div>
        <div class="card">
            <h3>Status: {"🟢 Hunting" if state.hunting else "🔴 Idle"}</h3>
            {"<p class='stat'>Scanned: " + str(stats.get('scanned', 0)) + "</p>" if state.hunting else ""}
            {"<p class='stat'>Working: " + str(stats.get('working', 0)) + "</p>" if state.hunting else ""}
        </div>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "hunting": state.hunting,
        "stats": state.get_stats() if state.hunting else {}
    })

@app.route('/api/proxies')
def api_proxies():
    return jsonify({
        "count": len(state.working_proxies),
        "proxies": state.working_proxies
    })

# ==========================================
# --- 13. التشغيل ---
# ==========================================
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🚀 SSH Hunter Pro Starting...")
    logger.info(f"🎯 Target: {SSH.domain} ({SSH.host})")
    logger.info(f"🔌 Ports: {SSH.ports}")
    logger.info("=" * 50)
    
    # تشغيل البوت
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()
    
    # تشغيل Flask
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🌐 Flask starting on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)
