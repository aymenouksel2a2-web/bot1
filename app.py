import os
import requests
import json
import subprocess
import time
import signal
import re
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
# --- معالجة Xray (VLESS / VMESS / TROJAN) ---
# ==========================================

def parse_user_config(user_json):
    """تحويل JSON المستخدم إلى إعدادات Xray مع دعم Trojan"""
    try:
        user_json = user_json.strip()
        data = json.loads(user_json)
        
        protocol = ""
        conf = {}

        # 1. تحديد البروتوكول واستخراج الكونفيج الخام
        if "vlessTunnelConfig" in data or data.get("type") == "VLESS":
            protocol = "vless"
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
        
        # --- إضافة دعم TROJAN هنا ---
        elif "trojanTunnelConfig" in data or data.get("type") == "TROJAN":
            protocol = "trojan"
            if "trojanTunnelConfig" in data:
                conf = data["trojanTunnelConfig"].get("v2rayConfig", data["trojanTunnelConfig"])
            else:
                conf = data
        else:
            return None, "نوع السيرفر غير مدعوم (Unsupported Protocol)"

        # 2. استخراج البيانات المشتركة
        address = conf.get("host") or conf.get("address") or conf.get("wsHeaderHost")
        port = int(conf.get("port", 443))
        
        # Trojan يستخدم password، بينما Vless/Vmess يستخدمون id/uuid
        # سنحاول استخراج أيهما موجود
        uuid_or_password = conf.get("password") or conf.get("uuid") or conf.get("id")
        
        path = conf.get("wsPath") or conf.get("path") or "/"
        sni = conf.get("serverNameIndication") or conf.get("sni") or ""
        host_header = conf.get("wsHeaderHost") or conf.get("host") or address

        # 3. تصحيح SNI الذكي (لإعدادات Cloud Run)
        if address and "run.app" in address and ("youtube" in sni or "google" in sni):
            print(f">>> Auto-Fixing SNI: Changed from {sni} to {address}")
            sni = address
            host_header = address

        # 4. بناء هيكل الإعدادات (Settings) حسب البروتوكول
        outbound_settings = {}
        
        if protocol == "trojan":
            # هيكل Trojan يختلف قليلاً (servers بدلاً من vnext)
            outbound_settings = {
                "servers": [{
                    "address": address,
                    "port": port,
                    "password": uuid_or_password,
                    "email": "trojan@xray.com" # مجرد حقل شكلي
                }]
            }
        else:
            # هيكل VMESS و VLESS
            outbound_settings = {
                "vnext": [{
                    "address": address,
                    "port": port,
                    "users": [{
                        "id": uuid_or_password,
                        "encryption": "none",
                        "security": "auto"
                    }]
                }]
            }
            # إضافة alterId لـ VMESS فقط
            if protocol == "vmess":
                outbound_settings["vnext"][0]["users"][0]["alterId"] = 0

        # 5. تجميع الـ Outbound النهائي
        outbound = {
            "protocol": protocol,
            "settings": outbound_settings,
            "streamSettings": {
                "network": "ws" if path != "/" else "tcp", # تخمين نوع الشبكة
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
                } if path != "/" else None # إضافة wsSettings فقط إذا كان هناك مسار
            }
        }
        
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
        xray_process = subprocess.Popen([xray_path, "-c", "config.json"])
        time.sleep(3) 
        return True
    return False

def check_connection():
    try:
        start_time = time.time()
        # زدنا المهلة لضمان الاتصال
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
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except: pass

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            webhook_url = f"{base_url}/{TOKEN}"
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
    except: pass

@app.route('/')
def home(): return "Bot Running with Trojan Support 🚀"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                send_msg(chat_id, "أهلاً! البوت الآن يدعم:\n✅ VLESS\n✅ VMESS\n✅ TROJAN\n\nأرسل الكود باستخدام `/add` للتجربة.")

            elif text.startswith("/add"):
                raw_json = text.replace("/add", "", 1).strip()
                if not raw_json: return jsonify({"ok": True})

                send_msg(chat_id, "⚙️ جاري تحليل الإعدادات...")
                
                new_config, error = parse_user_config(raw_json)
                if error:
                    send_msg(chat_id, f"❌ خطأ:\n{error}")
                else:
                    if restart_vpn(new_config):
                        info = check_connection()
                        if info["success"]:
                            msg = (
                                f"✅ **تم الاتصال بنجاح!**\n"
                                f"📡 البروتوكول: {new_config['outbounds'][0]['protocol'].upper()}\n"
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
