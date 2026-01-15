import os
import requests
import json
import subprocess
import time
import signal
import re
from flask import Flask, request, jsonify

# ==========================================
# --- الإعدادات ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)
xray_process = None 

PROXY = {
    "http": "socks5://127.0.0.1:10808",
    "https": "socks5://127.0.0.1:10808"
}

# ==========================================
# --- معالجة Xray مع دعم الحقن (Injection) ---
# ==========================================

def parse_user_config(user_json):
    """تحويل JSON مع دعم محاكاة الحقن (Injection Proxy)"""
    try:
        user_json = user_json.strip()
        data = json.loads(user_json)
        
        protocol = ""
        conf = {}
        inject_conf = None

        # 1. تحديد البروتوكول واستخراج البيانات
        if "vlessTunnelConfig" in data or data.get("type") == "VLESS":
            protocol = "vless"
            conf = data.get("vlessTunnelConfig", {}).get("v2rayConfig", data.get("vlessTunnelConfig", data))
        elif "vmessTunnelConfig" in data or data.get("type") == "VMESS":
            protocol = "vmess"
            conf = data.get("vmessTunnelConfig", {}).get("v2rayConfig", data.get("vmessTunnelConfig", data))
        elif "trojanTunnelConfig" in data or data.get("type") == "TROJAN":
            protocol = "trojan"
            conf = data.get("trojanTunnelConfig", {}).get("v2rayConfig", data.get("trojanTunnelConfig", data))
        else:
            return None, "نوع السيرفر غير مدعوم"

        # استخراج إعدادات الحقن إن وجدت
        if "injectConfig" in data:
            inject_conf = data["injectConfig"]
        elif "vlessTunnelConfig" in data and "injectConfig" in data["vlessTunnelConfig"]:
            inject_conf = data["vlessTunnelConfig"]["injectConfig"]
        elif "trojanTunnelConfig" in data and "injectConfig" in data["trojanTunnelConfig"]:
            inject_conf = data["trojanTunnelConfig"]["injectConfig"]

        # بيانات السيرفر الأساسي
        address = conf.get("host") or conf.get("address") or conf.get("wsHeaderHost")
        port = int(conf.get("port", 443))
        uuid_or_password = conf.get("password") or conf.get("uuid") or conf.get("id")
        path = conf.get("wsPath") or conf.get("path") or "/"
        sni = conf.get("serverNameIndication") or conf.get("sni") or ""
        host_header = conf.get("wsHeaderHost") or conf.get("host") or address

        # ---------------------------------------------------------
        # بناء قائمة Outbounds
        # ---------------------------------------------------------
        outbounds = []
        
        # إعدادات الاتصال بالسيرفر الأصلي (Main Outbound)
        main_outbound_settings = {}
        if protocol == "trojan":
            main_outbound_settings = {
                "servers": [{"address": address, "port": port, "password": uuid_or_password}]
            }
        else:
            main_outbound_settings = {
                "vnext": [{"address": address, "port": port, "users": [{"id": uuid_or_password, "encryption": "none", "security": "auto"}]}]
            }
            if protocol == "vmess": main_outbound_settings["vnext"][0]["users"][0]["alterId"] = 0

        main_outbound = {
            "protocol": protocol,
            "settings": main_outbound_settings,
            "streamSettings": {
                "network": "ws" if path != "/" else "tcp",
                "security": "tls",
                "tlsSettings": {"serverName": sni, "allowInsecure": True},
                "wsSettings": {"path": path, "headers": {"Host": host_header}} if path != "/" else None
            }
        }

        # --- منطق المحاكاة (Injection Logic) ---
        # إذا كان الحقن مفعل، نقوم بتوجيه الاتصال عبر البروكسي
        proxy_info = ""
        if inject_conf and inject_conf.get("enabled") == True:
            proxy_host = inject_conf.get("proxyHost")
            proxy_port = int(inject_conf.get("proxyPort", 80))
            
            if proxy_host:
                print(f">>> Simulating Injection via: {proxy_host}:{proxy_port}")
                proxy_info = f" (عبر الحقن: {proxy_host})"
                
                # 1. نضيف إعدادات البروكسي للسيرفر الأصلي
                main_outbound["proxySettings"] = {
                    "tag": "injector_proxy" # هذا يربطه بالخروج الثاني
                }
                
                # 2. إنشاء Outbound خاص بالحقن (HTTP Proxy)
                injector_outbound = {
                    "tag": "injector_proxy",
                    "protocol": "http", # أغلب تطبيقات الحقن تستخدم HTTP Proxy
                    "settings": {
                        "servers": [{
                            "address": proxy_host,
                            "port": proxy_port
                        }]
                    }
                }
                outbounds.append(injector_outbound)

        # نضيف السيرفر الأساسي كأول مخرج
        outbounds.insert(0, main_outbound)

        final_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": outbounds
        }
        
        return final_config, None, proxy_info

    except Exception as e:
        return None, f"خطأ: {str(e)}", ""

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
        response = requests.get("http://ip-api.com/json", proxies=PROXY, timeout=10)
        ping = int((time.time() - start_time) * 1000)
        data = response.json()
        return {"success": True, "ping": ping, "country": data.get("country"), "ip": data.get("query")}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==========================================
# --- البوت ---
# ==========================================
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

@app.route('/')
def home(): return "Bot Running (Dark Tunnel Simulation Mode) 📱"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/start":
                send_msg(chat_id, "وضع محاكاة Dark Tunnel مفعل 📱\nأرسل الكود وسأحاول الاتصال عبر البروكسي (Inject) الموجود فيه.")

            elif text.startswith("/add"):
                raw_json = text.replace("/add", "", 1).strip()
                if not raw_json: return jsonify({"ok": True})

                send_msg(chat_id, "⚙️ جاري التحليل ومحاولة الحقن...")
                
                new_config, error, proxy_info = parse_user_config(raw_json)
                
                if error:
                    send_msg(chat_id, f"❌ خطأ JSON:\n{error}")
                else:
                    if restart_vpn(new_config):
                        info = check_connection()
                        if info["success"]:
                            msg = (
                                f"✅ **تم الاتصال بنجاح!**{proxy_info}\n"
                                f"النوع: {new_config['outbounds'][0]['protocol'].upper()}\n"
                                f"⚡️ `{info['ping']}ms` | 🌍 {info['country']}\n"
                                f"📟 IP: `{info['ip']}`"
                            )
                            send_msg(chat_id, msg)
                        else:
                            # هنا ستظهر النتيجة الحقيقية إذا كان البروكسي لا يعمل
                            msg = f"❌ **فشل الاتصال (مثل الهاتف تماماً)**\n\nالسبب: البوت حاول الاتصال عبر البروكسي {proxy_info} ولكنه فشل.\nالخطأ: {info['error']}"
                            send_msg(chat_id, msg)
                    else:
                        send_msg(chat_id, "❌ مشكلة في xray")

        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

if __name__ == "__main__":
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
