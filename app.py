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

# بيانات سيرفر التروجان
TROJAN_HOST = "SC-France1.09vpn.com"
TROJAN_PORT = 2083
TROJAN_PASS = "u1023645402"
TROJAN_SNI  = "youtube.com"
PAYLOAD_HOST = "youtube.com"

# إعدادات الصياد (تمت توسعة النطاقات لزيادة الفرص)
IP_RANGES = [
    ("34.64", "34.127"), ("35.184", "35.240"), ("104.154", "104.199"), 
    ("34.80", "34.89"), ("35.200", "35.247"), ("130.211", "130.255")
]
PORTS_TO_SCAN = [80, 8080, 3128] 

# متغيرات الإحصائيات (الذاكرة الحية)
HUNTING = False
SCANNED_COUNT = 0       # عدد ما تم مسحه
RAW_HITS_COUNT = 0      # عدد ما وجده الصياد (الباب المفتوح)
TESTED_COUNT = 0        # عدد ما فحصه المحقق
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
    if xray_process:
        try:
            os.kill(xray_process.pid, signal.SIGTERM)
            xray_process.wait()
        except: pass

    config = {
        "log": {"loglevel": "error"},
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
    
    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)
        
    xray_path = "./xray"
    if os.path.exists(xray_path):
        xray_process = subprocess.Popen([xray_path, "-c", "config.json"])
        time.sleep(1.5) 
        return True
    return False

def test_connection_via_vpn():
    try:
        proxies = {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"}
        start = time.time()
        res = requests.get("http://ip-api.com/json", proxies=proxies, timeout=5)
        ping = int((time.time() - start) * 1000)
        return True, ping, res.json().get("country", "Unknown")
    except:
        return False, 0, ""

# ==========================================
# --- 3. الصياد السريع (Async Hunter) ---
# ==========================================
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
    global SCANNED_COUNT, RAW_HITS_COUNT
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
            
            # إذا وجدنا استجابة إيجابية
            if "200 Connection" in response or "200 OK" in response:
                RAW_HITS_COUNT += 1  # زيادة عداد Hits المفتوحة
                VALIDATION_QUEUE.put((ip, port))
        except: pass

async def hunter_loop():
    sem = asyncio.Semaphore(600) 
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
    global CHAT_ID_TARGET, TESTED_COUNT
    
    while True:
        if not VALIDATION_QUEUE.empty() and HUNTING:
            ip, port = VALIDATION_QUEUE.get()
            TESTED_COUNT += 1 # زيادة عداد ما تم فحصه
            
            restart_xray_with_proxy(ip, port)
            success, ping, country = test_connection_via_vpn()
            
            if success:
                proxy_str = f"{ip}:{port}"
                if proxy_str not in FOUND_WORKING_PROXIES:
                    FOUND_WORKING_PROXIES.append(proxy_str)
                    
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
            time.sleep(0.5)

# ==========================================
# --- 5. واجهة البوت والتقرير ---
# ==========================================
def report_updater():
    global STATUS_MSG_ID
    while True:
        if HUNTING and CHAT_ID_TARGET:
            msg = (
                f"📡 **Advanced Proxy Hunter**\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🔍 Scanned: `{SCANNED_COUNT}`\n"
                f"🔫 **Raw Hits:** `{RAW_HITS_COUNT}`\n"  # هنا ستظهر الـ 35 وأكثر
                f"🛠 Validated: `{TESTED_COUNT}`\n"     # هنا سترى أن المحقق يعمل
                f"✅ **Verified:** `{len(FOUND_WORKING_PROXIES)}`\n"
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
def home(): return "Hunter V3 Running 🛡️"

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
                    RAW_HITS_COUNT = 0 # تصفير العدادات
                    TESTED_COUNT = 0   # تصفير العدادات
                    STATUS_MSG_ID = None
                    
                    with VALIDATION_QUEUE.mutex: VALIDATION_QUEUE.queue.clear()
                    
                    threading.Thread(target=start_async_loop, args=(asyncio.new_event_loop(),), daemon=True).start()
                    threading.Thread(target=validator_worker, daemon=True).start()
                    threading.Thread(target=report_updater, daemon=True).start()
                    
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🚀 **بدء الصيد الشفاف!**\nسترى الآن الفرق بين Hits وبين Verified."})
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
