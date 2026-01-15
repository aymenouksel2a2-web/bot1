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
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": "w2ilwe-dr7rsvrgza-ue.a.run.app",
                    "port": 443,
                    "users": [{
                        "id": "eeee4444-bbbb-3ccc-1eee-eeeeaaaacccc",
                        "alterId": 0,
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {
                    "serverName": "youtube.com",
                    "allowInsecure": False
                },
                "wsSettings": {
                    "path": "/Telegram/@w2ilwe/@x_3_o_x",
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

    with open("config.json", "w") as f:
        json.dump(VPN_CONFIG, f, indent=4)

    subprocess.Popen([xray_path, "-c", "config.json"])
    print(">>> VPN Started on 127.0.0.1:10808")
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
    """فحص الاتصال عبر البروكسي"""
    try:
        # محاولة الاتصال عبر الـ VPN
        response = requests.get("http://ip-api.com/json", proxies=PROXY, timeout=5)
        data = response.json()
        return {
            "success": True,
            "ip": data.get("query", "Unknown"),
            "country": data.get("country", "Unknown"),
            "isp": data.get("isp", "Unknown")
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_msg(chat_id, text, use_vpn=True):
    """
    دالة ذكية للإرسال:
    تحاول الإرسال عبر VPN أولاً، إذا فشلت ترسل عبر النت العادي
    """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    
    if use_vpn:
        try:
            # محاولة الإرسال عبر الـ VPN
            requests.post(url, json={"chat_id": chat_id, "text": text}, proxies=PROXY, timeout=5)
        except Exception as e:
            print(f"VPN Send Failed: {e}")
            # إذا فشل، نعيد المحاولة بدون VPN لنخبر المستخدم
            fallback_text = f"⚠️ **فشل الـ VPN!**\n\nحاولت الرد عليك عبر الـ VPN ولكن السيرفر لا يعمل.\nالخطأ: {e}\n\n(هذه الرسالة مرسلة عبر الاتصال المباشر)"
            requests.post(url, json={"chat_id": chat_id, "text": fallback_text})
    else:
        # إرسال مباشر (بدون VPN)
        requests.post(url, json={"chat_id": chat_id, "text": text})

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
    return "Bot is running..."

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                # إشعار للمستخدم أن الفحص جاري (بدون VPN لضمان الوصول)
                send_msg(chat_id, "جاري تجربة الاتصال... ⏳", use_vpn=False)
                
                info = get_connection_info()
                
                if info["success"]:
                    msg = (
                        f"✅ **اتصال VMESS ناجح!**\n\n"
                        f"🌍 الدولة: {info['country']}\n"
                        f"📟 الآي بي: `{info['ip']}`\n"
                        f"🏢 المزود: {info['isp']}"
                    )
                    # نرسل النتيجة عبر الـ VPN لإثبات أنه يعمل
                    send_msg(chat_id, msg, use_vpn=True)
                else:
                    msg = f"❌ **السيرفر لا يعمل!**\nالخطأ: {info['error']}"
                    # نرسل الخطأ عبر الاتصال العادي
                    send_msg(chat_id, msg, use_vpn=False)
                
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

if __name__ == "__main__":
    start_vpn()
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
