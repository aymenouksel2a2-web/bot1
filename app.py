import os
import requests
import json
import subprocess
import time
import threading
from flask import Flask, request, jsonify

# ==========================================
# --- 1. إعدادات VPN (VLESS Configuration) ---
# ==========================================
VLESS_CONFIG = {
    "log": {"loglevel": "warning"},
    "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
    "outbounds": [
        {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": "server8-28405491988.europe-west1.run.app",
                    "port": 443,
                    "users": [{"id": "d7d687f9-2eae-49e5-aa6c-5eefa8b4d018", "encryption": "none"}]
                }]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {"serverName": "yt3.ggpht.com", "allowInsecure": False},
                "wsSettings": {"path": "/", "headers": {"Host": "server8-28405491988.europe-west1.run.app"}}
            }
        }
    ]
}

# تشغيل الـ VPN في الخلفية
def start_vpn():
    xray_path = "./xray" # سيتم توفيره عبر Dockerfile
    if not os.path.exists(xray_path):
        print("Xray binary not found! Check Dockerfile.")
        return

    with open("config.json", "w") as f:
        json.dump(VLESS_CONFIG, f, indent=4)

    # تشغيل العملية
    subprocess.Popen([xray_path, "-c", "config.json"])
    print(">>> VPN Started on 127.0.0.1:10808")
    time.sleep(3) # انتظار التجهيز

# ==========================================
# --- 2. إعدادات البوت ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)

# البروكسي الذي سيستخدمه البوت للاتصال بتيليجرام
PROXY = {
    "http": "socks5://127.0.0.1:10808",
    "https": "socks5://127.0.0.1:10808"
}

def send_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        # نستخدم البروكسي هنا
        requests.post(url, json={"chat_id": chat_id, "text": text}, proxies=PROXY, timeout=10)
    except Exception as e:
        print(f"Error sending msg: {e}")

def set_webhook():
    """ضبط الويب هوك تلقائياً"""
    try:
        # Koyeb يوفر هذا المتغير تلقائياً
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            webhook_url = f"{base_url}/{TOKEN}"
            # الويب هوك نرسله بدون بروكسي لضمان الوصول
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
            print(f"Webhook set to: {webhook_url}")
    except:
        pass

@app.route('/')
def home():
    return "Bot is running on VLESS Tunnel"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                send_msg(chat_id, "Hello! I am connected via VLESS VPN 🛡️")
                
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

if __name__ == "__main__":
    start_vpn() # تشغيل الـ VPN أولاً
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
