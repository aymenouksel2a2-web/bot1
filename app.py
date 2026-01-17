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
# --- 1. إعدادات البوت والتروجان ---
# ==========================================
# ⚠️ هام: استبدل التوكن وبيانات التروجان ببياناتك الصحيحة والجديدة
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4" 

# بيانات سيرفر التروجان (تأكد أنها تعمل 100% وإلا لن ينجح أي فحص)
TROJAN_HOST = "SC-France1.09vpn.com"
TROJAN_PORT = 2083
TROJAN_PASS = "u1023645402"
TROJAN_SNI  = "youtube.com"
PAYLOAD_HOST = "youtube.com"

app = Flask(__name__)

# --- إعدادات النطاقات (34 و 35 فقط) ---
# سيقوم البوت باختيار إما 34 أو 35، ثم يملأ الباقي عشوائياً
TARGET_PREFIXES = [34, 35] 
PORTS_TO_SCAN = [3128] 

# متغيرات الإحصائيات
HUNTING = False
SCANNED_COUNT = 0       
RAW_HITS_COUNT = 0      
TESTED_COUNT = 0        
VALIDATION_QUEUE = Queue() 
FOUND_WORKING_PROXIES = [] 
CHAT_ID_TARGET = None
STATUS_MSG_ID = None

# ==========================================
# --- 2. إدارة Xray (VPN Controller) ---
# ==========================================
xray_process = None

def restart_xray_with_proxy(proxy_ip, proxy_port):
    global xray_process
    
    # قتل العملية السابقة بشكل نظيف
    if xray_process:
        try:
            xray_process.terminate()
            xray_process.wait(timeout=1)
        except:
            try: os.kill(xray_process.pid, signal.SIGKILL)
            except: pass

    # إعداد ملف الكونفيج الجديد
    config = {
        "log": {"loglevel": "error"},
        "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [
            {
                "tag": "proxy_out",
                "protocol": "trojan",
                "settings": {
                    "servers": [{"address": TROJAN_HOST, "port": int(TROJAN_PORT), "password": TROJAN_PASS}]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {"serverName": TROJAN_SNI, "allowInsecure": True}
                },
                "proxySettings": {"tag": "inject_layer"}
            },
            {
                "tag": "inject_layer",
                "protocol": "http",
                "settings": {
                    "servers": [{"address": proxy_ip, "port": int(proxy_port)}],
                    "headers": {"Host": PAYLOAD_HOST}
                }
            }
        ]
    }
    
    try:
        with open("config.json", "w") as f:
            json.dump(config, f, indent=4)
        
        xray_path = "./xray"
        if os.path.exists(xray_path):
            xray_process = subprocess.Popen([xray_path, "-c", "config.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0) # انتظار ثانية ليقوم Xray بالتشغيل
            return True
    except Exception as e:
        print(f"Error starting Xray: {e}")
    return False

def test_connection_via_vpn():
    try:
        proxies = {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"}
        start = time.time()
        # تمت زيادة الوقت إلى 15 ثانية لأن الاتصال عبر البروكسي بطيء
        res = requests.get("http://ip-api.com/json", proxies=proxies, timeout=15)
        
        if res.status_code == 200:
            ping = int((time.time() - start) * 1000)
            data = res.json()
            return True, ping, data.get("country", "Unknown"), data.get("query", "")
    except:
        pass
    return False, 0, "", ""

# ==========================================
# --- 3. الصياد (Async Hunter) ---
# ==========================================
# بايلود بسيط ومتوافق
RAW_PAYLOAD = (
    f"CONNECT {PAYLOAD_HOST}:443 HTTP/1.1\r\n"
    f"Host: {PAYLOAD_HOST}\r\n"
    "Proxy-Connection: Keep-Alive\r\n\r\n"
).encode()

def generate_targeted_ip():
    prefix = random.choice(TARGET_PREFIXES)
    return f"{prefix}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}"

async def scan_socket(ip, port, sem):
    global SCANNED_COUNT, RAW_HITS_COUNT
    async with sem:
        SCANNED_COUNT += 1
        try:
            # مهلة قصيرة جداً للمسح السريع
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=1.2)
            writer.write(RAW_PAYLOAD)
            await writer.drain()
            
            # قراءة بداية الرد فقط
            data = await asyncio.wait_for(reader.read(128), timeout=1.2)
            response = data.decode(errors='ignore')
            
            writer.close()
            try: await writer.wait_closed()
            except: pass
            
            # التحقق من استجابة 200 OK
            if "200 Connection" in response or "200 OK" in response:
                RAW_HITS_COUNT += 1
                VALIDATION_QUEUE.put((ip, port))
        except:
            pass

async def hunter_loop():
    # تقليل العدد المتزامن قليلاً لضمان استقرار السيرفر
    sem = asyncio.Semaphore(500) 
    print(">>> Hunter Started targeting 34.x & 35.x 🚀")
    while HUNTING:
        tasks = []
        # توليد دفعة من المهام
        for _ in range(100):
            ip = generate_targeted_ip()
            for port in PORTS_TO_SCAN:
                tasks.append(scan_socket(ip, port, sem))
        
        if tasks:
            await asyncio.gather(*tasks)
        else:
            await asyncio.sleep(0.1)

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(hunter_loop())

# ==========================================
# --- 4. المحقق (Validator Thread) ---
# ==========================================
def validator_worker():
    global CHAT_ID_TARGET, TESTED_COUNT
    
    while True:
        if not VALIDATION_QUEUE.empty() and HUNTING:
            ip, port = VALIDATION_QUEUE.get()
            TESTED_COUNT += 1
            
            # تشغيل Xray ومحاولة الاتصال
            if restart_xray_with_proxy(ip, port):
                # محاولة مرتين للتحقق (Retry Logic)
                success = False
                for _ in range(2):
                    success, ping, country, real_ip = test_connection_via_vpn()
                    if success: break
                    time.sleep(1)
                
                if success:
                    proxy_str = f"{ip}:{port}"
                    if proxy_str not in FOUND_WORKING_PROXIES:
                        FOUND_WORKING_PROXIES.append(proxy_str)
                        
                        msg = (
                            f"💎 **GOLDEN PROXY FOUND!**\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"🌐 Proxy: `{ip}:{port}`\n"
                            f"🏳️ Loc: {country}\n"
                            f"⚡ Ping: `{ping}ms`\n"
                            f"✅ **Trojan Tunnel Works!**\n"
                            f"━━━━━━━━━━━━━━━━"
                        )
                        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                    json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
        else:
            time.sleep(0.5)

# ==========================================
# --- 5. واجهة البوت والتقرير ---
# ==========================================
def report_updater():
    global STATUS_MSG_ID
    while True:
        if HUNTING and CHAT_ID_TARGET:
            msg = (
                f"📡 **Hunter V4 (Google Cloud Ed.)**\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🎯 Target: `34.x, 35.x` | Port: `3128`\n"
                f"🔍 Scanned: `{SCANNED_COUNT}`\n"
                f"🔫 Raw Hits: `{RAW_HITS_COUNT}`\n"
                f"🛠 Validated: `{TESTED_COUNT}`\n"
                f"✅ **Working:** `{len(FOUND_WORKING_PROXIES)}`\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⏳ Searching..."
            )
            url = f"https://api.telegram.org/bot{TOKEN}/"
            try:
                if STATUS_MSG_ID:
                    requests.post(url + "editMessageText", 
                                json={"chat_id": CHAT_ID_TARGET, "message_id": STATUS_MSG_ID, "text": msg, "parse_mode": "Markdown"})
                else:
                    res = requests.post(url + "sendMessage", 
                                      json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
                    if res.status_code == 200: STATUS_MSG_ID = res.json()["result"]["message_id"]
            except: pass
        time.sleep(6) # تحديث كل 6 ثواني

@app.route('/')
def home(): return "Hunter Optimized Running"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    global HUNTING, CHAT_ID_TARGET, FOUND_WORKING_PROXIES, SCANNED_COUNT, RAW_HITS_COUNT, TESTED_COUNT, STATUS_MSG_ID
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
                    RAW_HITS_COUNT = 0
                    TESTED_COUNT = 0
                    STATUS_MSG_ID = None
                    
                    with VALIDATION_QUEUE.mutex: VALIDATION_QUEUE.queue.clear()
                    
                    # بدء الخيوط (Threads)
                    threading.Thread(target=start_async_loop, args=(asyncio.new_event_loop(),), daemon=True).start()
                    threading.Thread(target=validator_worker, daemon=True).start()
                    threading.Thread(target=report_updater, daemon=True).start()
                    
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                json={"chat_id": chat_id, "text": "🚀 **بدء الصيد المركز (34/35 : 3128)**\nيرجى الانتظار، التحقق الآن يأخذ وقتاً أطول لضمان الدقة."})
                else:
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "⚠️ البوت يعمل بالفعل."})
            
            elif text == "/stop":
                HUNTING = False
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🛑 تم الإيقاف."})
                
        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') or os.environ.get('RENDER_EXTERNAL_URL')
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": f"{base_url}/{TOKEN}"})
    except: pass

if __name__ == "__main__":
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
