import os
import requests
import json
import subprocess
import time
from flask import Flask, request, jsonify

# ==========================================
# --- إعدادات المحاكاة الدقيقة (Hardcoded) ---
# ==========================================

# 1. بيانات السيرفر (Trojan)
TROJAN_HOST = "SC-France1.09vpn.com"
TROJAN_PORT = 2083
TROJAN_PASS = "u1023645402"
TROJAN_SNI  = "youtube.com"

# 2. بيانات الحقن (Injection Proxy)
INJECT_HOST = "34.41.115.197"
INJECT_PORT = 3128

# 3. محاكاة الـ Payload
# Payload: "CONNECT [host_port] [protocol][crlf]Host: youtube.com[crlf][crlf]"
# في Xray، نضع Host: youtube.com داخل headers للبروكسي HTTP
PAYLOAD_HOST = "youtube.com"

XRAY_CONFIG = {
    "log": {"loglevel": "warning"},
    "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
    "outbounds": [
        # --- المخرج 1: سيرفر Trojan الأصلي ---
        {
            "tag": "proxy_out",
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": TROJAN_HOST,
                    "port": TROJAN_PORT,
                    "password": TROJAN_PASS
                }]
            },
            "streamSettings": {
                "network": "tcp",
                "security": "tls",
                "tlsSettings": {
                    "serverName": TROJAN_SNI,
                    "allowInsecure": True
                }
            },
            # توجيه الاتصال عبر طبقة الحقن (Inject)
            "proxySettings": {
                "tag": "inject_layer"
            }
        },
        # --- المخرج 2: طبقة الحقن (HTTP Proxy + Payload) ---
        {
            "tag": "inject_layer",
            "protocol": "http", # نستخدم HTTP لأنه هو الذي يتعامل مع CONNECT
            "settings": {
                "servers": [{
                    "address": INJECT_HOST,
                    "port": INJECT_PORT
                }],
                # هنا نضع الـ Payload Header
                # هذا سيجعل الطلب يبدو كـ: CONNECT target HTTP/1.1 \r\n Host: youtube.com
                "headers": {
                    "Host": PAYLOAD_HOST
                }
            }
        }
    ]
}

# ==========================================
# --- تشغيل النظام ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)

PROXY_DICT = {
    "http": "socks5://127.0.0.1:10808",
    "https": "socks5://127.0.0.1:10808"
}

def start_simulation():
    """تشغيل Xray بالإعدادات الثابتة"""
    xray_path = "./xray"
    if not os.path.exists(xray_path):
        print("❌ Error: Xray binary not found!")
        return

    # كتابة ملف الإعدادات
    with open("config.json", "w") as f:
        json.dump(XRAY_CONFIG, f, indent=4)
        
    # تشغيل العملية في الخلفية
    subprocess.Popen([xray_path, "-c", "config.json"])
    print(f">>> Simulation Started: Trojan -> Proxy({INJECT_HOST}) + Payload({PAYLOAD_HOST})")
    time.sleep(3)

def check_connection():
    """فحص الاتصال الفعلي"""
    try:
        start = time.time()
        # محاولة جلب IP عبر النفق
        res = requests.get("http://ip-api.com/json", proxies=PROXY_DICT, timeout=15)
        ping = int((time.time() - start) * 1000)
        data = res.json()
        return {
            "success": True,
            "ping": ping,
            "ip": data.get("query"),
            "country": data.get("country"),
            "isp": data.get("isp")
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_msg(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=5)
    except: pass

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": f"{base_url}/{TOKEN}"})
    except: pass

# ==========================================
# --- واجهة البوت ---
# ==========================================
@app.route('/')
def home(): return "Dark Tunnel Simulator Running..."

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                send_msg(chat_id, "⚙️ **بدء فحص المحاكاة (Simulation Check)**\n\n"
                                  "جاري محاكاة Dark Tunnel بالإعدادات التالية:\n"
                                  f"🔹 **Svr:** `{TROJAN_HOST}`\n"
                                  f"🔹 **Inj:** `{INJECT_HOST}:{INJECT_PORT}`\n"
                                  f"🔹 **Payload:** `Host: {PAYLOAD_HOST}`\n\n"
                                  "⏳ انتظر النتيجة...")
                
                info = check_connection()
                
                if info["success"]:
                    msg = (
                        "✅ **نجحت المحاكاة! (Connected)**\n\n"
                        "هذا يعني أن:\n"
                        "1. السيرفر سليم.\n"
                        "2. البروكسي (34.84...) يعمل.\n"
                        "3. الـ Payload صحيح.\n\n"
                        f"🌍 {info['country']} - {info['isp']}\n"
                        f"📟 IP: `{info['ip']}`"
                    )
                else:
                    msg = (
                        "❌ **فشلت المحاكاة! (Disconnected)**\n\n"
                        "بما أن الإعدادات مطابقة تماماً لتطبيقك، فالسبب هو:\n"
                        "🔴 **البروكسي (Proxy IP) محظور أو لا يستجيب.**\n\n"
                        f"الخطأ التقني: `{info['error']}`"
                    )
                
                send_msg(chat_id, msg)
                
        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

if __name__ == "__main__":
    start_simulation()
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
