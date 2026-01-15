import os
import requests
import json
import asyncio
import random
import threading
import time
import subprocess
import signal
from flask import Flask, request, jsonify
from queue import Queue

# ==========================================
# --- 1. إعدادات البوت والتروجان الثابتة ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)

# بيانات سيرفر التروجان الخاص بك (الثابتة)
TROJAN_HOST = "SC-France1.09vpn.com"
TROJAN_PORT = 2083
TROJAN_PASS = "u1023645402"
TROJAN_SNI  = "youtube.com"
PAYLOAD_HOST = "youtube.com"

# إعدادات الصياد
IP_RANGES = [
    ("34.64", "34.127"), ("35.184", "35.240"), ("104.154", "104.199"), # نطاقات جوجل
]
PORTS_TO_SCAN = [80, 8080, 3128] # المنافذ المستهدفة

# متغيرات التحكم
HUNTING = False
SCANNED_COUNT = 0
VALIDATION_QUEUE = Queue() # طابور البروكسيات التي تنتظر فحص التروجان
FOUND_WORKING_PROXIES = [] # البروكسيات التي نجحت فعلياً
CHAT_ID_TARGET = None
STATUS_MSG_ID = None

# ==========================================
# --- 2. إدارة Xray (VPN Controller) ---
# ==========================================
xray_process = None

def restart_xray_with_proxy(proxy_ip, proxy_port):
    """إعادة تشغيل Xray لاستخدام بروكسي محدد"""
    global xray_process
    
    # إيقاف العملية السابقة
    if xray_process:
        try:
            os.kill(xray_process.pid, signal.SIGTERM)
            xray_process.wait()
        except: pass

    # إعداد الكونفيج مع البروكسي المكتشف
    config = {
        "log": {"loglevel": "error"}, # تقليل السجلات للسرعة
        "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [
            {
                "tag": "proxy_out",
                "protocol": "trojan",
                "settings": {
                    "servers": [{"address": TROJAN_HOST, "port": TROJAN_PORT, "password": TROJAN_PASS}]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {"serverName": TROJAN_SNI, "allowInsecure": True}
                },
                "proxySettings": {"tag": "inject_layer"} # إجبار المرور عبر البروكسي
            },
            {
                "tag": "inject_layer",
                "protocol": "http",
                "settings": {
                    "servers": [{"address": proxy_ip, "port": int(proxy_port)}],
                    "headers": {"Host": PAYLOAD_HOST} # Payload
                }
            }
        ]
    }
    
    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)
        
    xray_path = "./xray"
    if os.path.exists(xray_path):
        xray_process = subprocess.Popen([xray_path, "-c", "config.json"])
        time.sleep(2) # انتظار تشغيل السيرفر
        return True
    return False

def test_connection_via_vpn():
    """محاولة الاتصال بالإنترنت عبر الـ VPN"""
    try:
        proxies = {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"}
        start = time.time()
        # مهلة قصيرة (5 ثواني) لأننا نريد البروكسيات السريعة فقط
        res = requests.get("http://ip-api.com/json", proxies=proxies, timeout=5)
        ping = int((time.time() - start) * 1000)
        return True, ping, res.json().get("country", "Unknown")
    except:
        return False, 0, ""

# ==========================================
# --- 3. الصياد السريع (Async Hunter) ---
# ==========================================
# بايلود الفحص الأولي (فقط للتأكد أن البروكسي مفتوح)
RAW_PAYLOAD = (
    b"CONNECT youtube.com:443 HTTP/1.1\r\n"
    b"Host: youtube.com\r\n"
    b"Proxy-Connection: Keep-Alive\r\n\r\n"
)

def generate_ip():
    base_start, base_end = random.choice(IP_RANGES)
    start = int(base_start.split('.')[1])
    end = int(base_end.split('.')[1])
    return f"{base_start.split('.')[0]}.{random.randint(start, end)}.{random.randint(0, 255)}.{random.randint(0, 255)}"

async def scan_socket(ip, port, sem):
    global SCANNED_COUNT
    async with sem:
        SCANNED_COUNT += 1
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=1.5)
            writer.write(RAW_PAYLOAD)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=1.5)
            response = data.decode(errors='ignore')
            writer.close()
            await writer.wait_closed()
            
            # إذا استجاب البروكسي بـ 200 OK، نرسله للمحقق
            if "200 Connection" in response or "200 OK" in response:
                VALIDATION_QUEUE.put((ip, port))
        except: pass

async def hunter_loop():
    sem = asyncio.Semaphore(500) # سرعة الفحص
    print(">>> Hunter Started 🚀")
    while HUNTING:
        tasks = []
        for _ in range(50):
            ip = generate_ip()
            for port in PORTS_TO_SCAN:
                tasks.append(scan_socket(ip, port, sem))
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.1)

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(hunter_loop())

# ==========================================
# --- 4. المحقق (Validator Thread) ---
# ==========================================
def validator_worker():
    """خيط منفصل يقوم بتجربة البروكسيات المكتشفة داخل Trojan"""
    global CHAT_ID_TARGET
    
    while True:
        if not VALIDATION_QUEUE.empty() and HUNTING:
            ip, port = VALIDATION_QUEUE.get()
            
            # 1. تشغيل Xray بهذا البروكسي
            restart_xray_with_proxy(ip, port)
            
            # 2. فحص الاتصال الحقيقي
            success, ping, country = test_connection_via_vpn()
            
            if success:
                proxy_str = f"{ip}:{port}"
                if proxy_str not in FOUND_WORKING_PROXIES:
                    FOUND_WORKING_PROXIES.append(proxy_str)
                    
                    # إرسال إشعار فوري عند العثور على كنز
                    msg = (
                        f"💎 **FOUND GOLDEN PROXY!**\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"🌐 IP: `{ip}:{port}`\n"
                        f"⚡ Ping: `{ping}ms` | 🚩 {country}\n"
                        f"✅ **Works with Trojan Config!**\n"
                        f"━━━━━━━━━━━━━━━━"
                    )
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
        else:
            time.sleep(1) # استراحة إذا كان الطابور فارغاً

# ==========================================
# --- 5. واجهة البوت والتقرير ---
# ==========================================
def report_updater():
    global STATUS_MSG_ID
    while True:
        if HUNTING and CHAT_ID_TARGET:
            q_size = VALIDATION_QUEUE.qsize()
            msg = (
                f"📡 **Trojan Proxy Hunter**\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🔍 Scanned IPs: `{SCANNED_COUNT}`\n"
                f"⌛ Waiting Check: `{q_size}`\n"
                f"✅ **Verified Working:** `{len(FOUND_WORKING_PROXIES)}`\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⚠️ Scanning & validating live..."
            )
            url = f"https://api.telegram.org/bot{TOKEN}/"
            try:
                if STATUS_MSG_ID:
                    requests.post(url + "editMessageText", json={"chat_id": CHAT_ID_TARGET, "message_id": STATUS_MSG_ID, "text": msg, "parse_mode": "Markdown"})
                else:
                    res = requests.post(url + "sendMessage", json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
                    if res.status_code == 200: STATUS_MSG_ID = res.json()["result"]["message_id"]
            except: pass
        time.sleep(5)

@app.route('/')
def home(): return "Hunter-Validator Bot Running 🛡️"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    global HUNTING, CHAT_ID_TARGET, FOUND_WORKING_PROXIES, SCANNED_COUNT, STATUS_MSG_ID
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/hunt":
                if not HUNTING:
                    HUNTING = True
                    CHAT_ID_TARGET = chat_id
                    FOUND_WORKING_PROXIES = []
                    SCANNED_COUNT = 0
                    STATUS_MSG_ID = None
                    
                    # تفريغ الطابور القديم
                    with VALIDATION_QUEUE.mutex: VALIDATION_QUEUE.queue.clear()
                    
                    # تشغيل الخيوط
                    threading.Thread(target=start_async_loop, args=(asyncio.new_event_loop(),), daemon=True).start()
                    threading.Thread(target=validator_worker, daemon=True).start()
                    threading.Thread(target=report_updater, daemon=True).start()
                    
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🚀 **بدء الصيد والتحقق المزدوج!**\nسأخبرك فقط بالبروكسيات التي تنجح في تشغيل Trojan."})
                else:
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "⚠️ الصيد يعمل بالفعل."})
            
            elif text == "/stop":
                HUNTING = False
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🛑 تم الإيقاف."})
                
        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": f"{base_url}/{TOKEN}"})
    except: pass

if __name__ == "__main__":
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
