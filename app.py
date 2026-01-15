import os
import requests
import json
import subprocess
import time
import signal
import re # مكتبة للتعامل مع النصوص بذكاء
from flask import Flask, request, jsonify

# ==========================================
# --- المتغيرات والإعدادات ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)
xray_process = None 

PROXY = {
    "http": "socks5://127.0.0.1:10808",
    "https": "socks5://127.0.0.1:10808"
}

# ==========================================
# --- معالجة Xray والذكاء في التصحيح ---
# ==========================================

def parse_user_config(user_json):
    """تحويل JSON المستخدم إلى إعدادات Xray مع تصحيح الأخطاء تلقائياً"""
    try:
        # تنظيف النص من أي زيادات
        user_json = user_json.strip()
        data = json.loads(user_json)
        
        # تحديد البروتوكول (VLESS أو VMESS)
        if "vlessTunnelConfig" in data or data.get("type") == "VLESS":
            protocol = "vless"
            # دعم صيغ مختلفة للـ JSON (سواء كانت مباشرة أو داخل هيكل Dark Tunnel)
            if "vlessTunnelConfig" in data:
                conf = data["vlessTunnelConfig"].get("v2rayConfig", data["vlessTunnelConfig"])
            else:
                conf = data
                
        elif "vmessTunnelConfig" in data or data.get("type") == "VMESS":
            protocol = "vmess"
            if "vmessTunnelConfig" in data:
                conf = data["vmessTunnelConfig"].get("v2rayConfig", data["vmessTunnelConfig"])
            else:
                conf = data
        else:
            return None, "نوع السيرفر غير مدعوم أو JSON غير صحيح"

        # استخراج البيانات
        address = conf.get("host") or conf.get("address") or conf.get("wsHeaderHost")
        port = int(conf.get("port", 443))
        uuid = conf.get("uuid") or conf.get("id")
        path = conf.get("wsPath") or conf.get("path") or "/"
        sni = conf.get("serverNameIndication") or conf.get("sni") or ""
        host_header = conf.get("wsHeaderHost") or conf.get("host") or address

        # ---------------------------------------------------------
        # 🧠 [الذكاء الإصطناعي] تصحيح التمويه (SNI Fixer)
        # المشكلة: Koyeb لا يحتاج تمويه، والتمويه يكسر اتصال Google Cloud
        # الحل: إذا كان السيرفر run.app والـ SNI هو youtube.com -> اجعل SNI هو العنوان الحقيقي
        # ---------------------------------------------------------
        if "run.app" in address and ("youtube" in sni or "google" in sni):
            print(f">>> Auto-Fixing SNI: Changed from {sni} to {address}")
            sni = address
            host_header = address # توحيد الهوست لضمان الاتصال
        # ---------------------------------------------------------

        # بناء هيكل Outbound
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
                    "allowInsecure": True, # السماح بالشهادات غير الموثوقة قليلاً لتجنب المشاكل
                    "fingerprint": "chrome" # محاولة محاكاة المتصفح
                },
                "wsSettings": {
                    "path": path,
                    "headers": {
                        "Host": host_header
                    }
                }
            }
        }
        
        if protocol == "vmess":
            outbound["settings"]["vnext"][0]["users"][0]["alterId"] = 0

        final_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [outbound]
        }
        
        return final_config, None

    except Exception as e:
        return None, f"خطأ في تحليل البيانات: {str(e)}"

def restart_vpn(config_dict):
    global xray_process
    if xray_process:
        try:
            os.kill(xray_process.pid, signal.SIGTERM)
            xray_process.wait()
        except: pass
    
    with open("config.json", "w") as f:
        json.dump(config_dict, f, indent=4)
        
    xray_path = "./xray"
    if os.path.exists(xray_path):
        # استخدام nohup أو تشغيل مستقل لضمان الاستقرار
        xray_process = subprocess.Popen([xray_path, "-c", "config.json"])
        time.sleep(3) 
        return True
    return False

def check_connection():
    try:
        start_time = time.time()
        # زدنا مدة الانتظار قليلاً لتجنب Read timed out الكاذب
        response = requests.get("http://ip-api.com/json", proxies=PROXY, timeout=10)
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
# --- البوت ---
# ==========================================

def send_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        # نحاول الإرسال بدون بروكسي أولاً لضمان وصول الرد حتى لو الـ VPN خربان
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except:
        pass

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            webhook_url = f"{base_url}/{TOKEN}"
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
    except: pass

@app.route('/')
def home(): return "Bot Running with Auto-Fix 🚀"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                send_msg(chat_id, "أرسل كود JSON باستخدام:\n`/add {json}`\n\nوسأقوم بتصحيح إعدادات Google Cloud تلقائياً 😉")

            elif text.startswith("/add"):
                raw_json = text.replace("/add", "", 1).strip()
                if not raw_json: return jsonify({"ok": True})

                send_msg(chat_id, "⚙️ جاري التحليل والاتصال...")
                
                new_config, error = parse_user_config(raw_json)
                if error:
                    send_msg(chat_id, f"❌ خطأ JSON:\n{error}")
                else:
                    if restart_vpn(new_config):
                        info = check_connection()
                        if info["success"]:
                            msg = (
                                f"✅ **تم الاتصال بنجاح!**\n"
                                f"⚡️ `{info['ping']}ms` | 🌍 {info['country']}\n"
                                f"📟 IP: `{info['ip']}`"
                            )
                            send_msg(chat_id, msg)
                        else:
                            send_msg(chat_id, f"❌ فشل الاتصال:\n{info['error']}")
                    else:
                        send_msg(chat_id, "❌ مشكلة في تشغيل xray")

        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

if __name__ == "__main__":
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
