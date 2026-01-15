import os
import requests
import json
import subprocess
import time
from flask import Flask, request, jsonify

# ==========================================
# --- 1. إعدادات VPN (VMESS Configuration) ---
# ==========================================
VPN_CONFIG = {
    "log": {"loglevel": "warning"},
    "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
    "outbounds": [
        {
            "protocol": "vmess", # تغيير البروتوكول هنا
            "settings": {
                "vnext": [{
                    "address": "w2ilwe-dr7rsvrgza-ue.a.run.app", # الهوست الجديد
                    "port": 443,
                    "users": [{
                        "id": "eeee4444-bbbb-3ccc-1eee-eeeeaaaacccc", # UUID الجديد
                        "alterId": 0, # ضروري لبروتوكول VMESS
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {
                    "serverName": "youtube.com", # SNI الجديد
                    "allowInsecure": False
                },
                "wsSettings": {
                    "path": "/Telegram/@w2ilwe/@x_3_o_x", # المسار الجديد
                    "headers": {
                        "Host": "w2ilwe-dr7rsvrgza-ue.a.run.app"
                    }
                }
            }
        }
    ]
}

def start_vpn():
    xray_path = "./xray"
    if not os.path.exists(xray_path):
        print("Xray binary not found! Check Dockerfile.")
        return

    # كتابة الإعدادات الجديدة
    with open("config.json", "w") as f:
        json.dump(VPN_CONFIG, f, indent=4)

    # تشغيل Xray
    subprocess.Popen([xray_path, "-c", "config.json"])
    print(">>> VPN (VMESS) Started on 127.0.0.1:10808")
    time.sleep(3) 

# ==========================================
# --- 2. إعدادات البوت ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)

PROXY = {
    "http": "socks5://127.0.0.1:10808",
    "https": "socks5://127.0.0.1:10808"
}

def get_connection_info():
    """فحص الاتصال عبر السيرفر الجديد"""
    try:
        response = requests.get("http://ip-api.com/json", proxies=PROXY, timeout=10)
        data = response.json()
        return {
            "status": "✅ متصل (Connected)",
            "ip": data.get("query", "Unknown"),
            "country": data.get("country", "Unknown"),
            "isp": data.get("isp", "Unknown")
        }
    except Exception as e:
        return {"status": "❌ فشل الاتصال", "error": str(e)}

def send_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, proxies=PROXY, timeout=10)
    except Exception as e:
        print(f"Error sending msg: {e}")

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            webhook_url = f"{base_url}/{TOKEN}"
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
    except:
        pass

@app.route('/')
def home():
    return "Bot running with VMESS Config"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                send_msg(chat_id, "جاري تجربة سيرفر VMESS الجديد... 🔄")
                info = get_connection_info()
                
                if "error" in info:
                    msg = f"⚠️ فشل الاتصال:\n{info['error']}"
                else:
                    msg = (
                        f"🚀 **نجح الاتصال بالسيرفر الجديد!**\n\n"
                        f"🌍 الدولة: {info['country']}\n"
                        f"📟 الآي بي: `{info['ip']}`\n"
                        f"🏢 المزود: {info['isp']}"
                    )
                send_msg(chat_id, msg)
                
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

if __name__ == "__main__":
    start_vpn()
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
