import os
import requests
import json
import subprocess
import time
import signal
from flask import Flask, request, jsonify

# ==========================================
# --- متغيرات عالمية ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)
xray_process = None  # لتخزين عملية الـ VPN الحالية

PROXY = {
    "http": "socks5://127.0.0.1:10808",
    "https": "socks5://127.0.0.1:10808"
}

# ==========================================
# --- دوال التعامل مع Xray ---
# ==========================================

def parse_user_config(user_json):
    """تحويل JSON المستخدم إلى إعدادات Xray القياسية"""
    try:
        data = json.loads(user_json)
        
        # استخراج البيانات بناءً على النوع
        if "vlessTunnelConfig" in data or data.get("type") == "VLESS":
            protocol = "vless"
            conf = data["vlessTunnelConfig"]["v2rayConfig"]
        elif "vmessTunnelConfig" in data or data.get("type") == "VMESS":
            protocol = "vmess"
            conf = data["vmessTunnelConfig"]["v2rayConfig"]
        else:
            return None, "نوع السيرفر غير مدعوم أو JSON غير صحيح"

        # استخراج القيم المشتركة
        address = conf.get("host") or conf.get("wsHeaderHost")
        port = int(conf.get("port", 443))
        uuid = conf.get("uuid")
        path = conf.get("wsPath", "/")
        sni = conf.get("serverNameIndication", "")
        host_header = conf.get("wsHeaderHost", address)

        # بناء هيكل Outbound الخاص بـ Xray
        outbound = {
            "protocol": protocol,
            "settings": {
                "vnext": [{
                    "address": address,
                    "port": port,
                    "users": [{
                        "id": uuid,
                        "encryption": "none",
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {
                    "serverName": sni,
                    "allowInsecure": True
                },
                "wsSettings": {
                    "path": path,
                    "headers": {
                        "Host": host_header
                    }
                }
            }
        }
        
        # إضافة alterId إذا كان VMESS
        if protocol == "vmess":
            outbound["settings"]["vnext"][0]["users"][0]["alterId"] = 0

        # تجميع ملف Config الكامل
        final_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [outbound]
        }
        
        return final_config, None

    except Exception as e:
        return None, f"خطأ في تحليل البيانات: {str(e)}"

def restart_vpn(config_dict):
    """إعادة تشغيل الـ VPN بالإعدادات الجديدة"""
    global xray_process
    
    # 1. إيقاف العملية القديمة إن وجدت
    if xray_process:
        try:
            os.kill(xray_process.pid, signal.SIGTERM)
            xray_process.wait()
        except:
            pass
    
    # 2. كتابة ملف الإعدادات
    with open("config.json", "w") as f:
        json.dump(config_dict, f, indent=4)
        
    # 3. تشغيل العملية الجديدة
    xray_path = "./xray"
    if os.path.exists(xray_path):
        xray_process = subprocess.Popen([xray_path, "-c", "config.json"])
        time.sleep(2) # انتظار التشغيل
        return True
    return False

def check_connection():
    """فحص الاتصال عبر البروكسي"""
    try:
        start_time = time.time()
        response = requests.get("http://ip-api.com/json", proxies=PROXY, timeout=8)
        ping = int((time.time() - start_time) * 1000)
        data = response.json()
        return {
            "success": True,
            "ping": ping,
            "ip": data.get("query", "Unknown"),
            "country": data.get("country", "Unknown"),
            "isp": data.get("isp", "Unknown")
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==========================================
# --- دوال البوت ---
# ==========================================

def send_msg(chat_id, text, use_vpn=False):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        # نحاول الإرسال المباشر لضمان الوصول إلا إذا طلبنا تجربة الـ VPN
        proxies = PROXY if use_vpn else None
        requests.post(url, json={"chat_id": chat_id, "text": text}, proxies=proxies, timeout=5)
    except:
        # محاولة احتياطية بدون بروكسي
        if use_vpn:
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
    return "Bot is running with Dynamic Config Support"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            # --- أمر /start ---
            if text == "/start":
                send_msg(chat_id, "أهلاً بك! 🛠\nأرسل الإعدادات بصيغة JSON باستخدام الأمر:\n`/add {json...}`\n\nوسأقوم بتجربة الاتصال فوراً.")

            # --- أمر /add ---
            elif text.startswith("/add"):
                raw_json = text.replace("/add", "", 1).strip()
                
                if not raw_json:
                    send_msg(chat_id, "⚠️ خطأ: يرجى وضع كود JSON بعد الأمر.")
                    return jsonify({"ok": True})

                send_msg(chat_id, "⚙️ جاري تحليل الإعدادات وتشغيل السيرفر...")
                
                # 1. تحليل JSON
                new_config, error = parse_user_config(raw_json)
                
                if error:
                    send_msg(chat_id, f"❌ فشل تحليل الكود:\n{error}")
                    return jsonify({"ok": True})
                
                # 2. تشغيل الـ VPN
                if restart_vpn(new_config):
                    # 3. فحص الاتصال
                    info = check_connection()
                    
                    if info["success"]:
                        msg = (
                            f"✅ **تم الاتصال بنجاح!**\n\n"
                            f"⚡️ البينج: `{info['ping']}ms`\n"
                            f"🌍 الدولة: {info['country']}\n"
                            f"📟 الآي بي: `{info['ip']}`\n"
                            f"🏢 المزود: {info['isp']}"
                        )
                        send_msg(chat_id, msg)
                    else:
                        msg = f"❌ **السيرفر لا يعمل!**\nالسبب: {info['error']}"
                        send_msg(chat_id, msg)
                else:
                    send_msg(chat_id, "❌ خطأ داخلي: لم يتم العثور على ملف xray.")

        return jsonify({"ok": True})
    except Exception as e:
        print(e)
        return jsonify({"ok": False})

if __name__ == "__main__":
    # تشغيل ملف Dockerfile سيضمن وجود xray
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
