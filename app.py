import os
import requests
import socket
import random
import threading
import time
from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures

# ==========================================
# --- الإعدادات والبيانات ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"

# هدف البحث
TARGET_HOST = "SC-France1.09vpn.com"
TARGET_PORT = 2083
SNI_HOST = "youtube.com"

SCAN_PORTS = [3128, 33080] 

GCP_PREFIXES = [
    '34.80', '34.81', '34.82', '34.83', '34.84', '34.85', '34.86', '34.87', '34.88', '34.89', '34.90', '34.91', '34.92',
    '35.185', '35.186', '35.187', '35.188', '35.190', '35.191', '35.192', '35.200', '35.201', '35.202',
    '104.196', '104.197', '104.198', '104.199',
    '35.240', '35.241', '35.242', '35.243', '35.244'
]

# حالة البوت
scanning_active = False
scanner_thread = None
current_chat_id = None
keep_alive_active = True

# العدادات
found_count = 0
invalid_count = 0

# تخزين أرقام رسائل الحالة (للاستبدال)
last_manual_status_msg_id = None
last_auto_report_msg_id = None

# إعدادات السرعة
MAX_CONCURRENT_SCANS = 25

app = Flask(__name__)

# --- لوحة المفاتيح ---
KEYBOARD = {
    "keyboard": [["🚀 بدء الصيد", "🛑 إيقاف"], ["📊 الحالة", "❓ مساعدة"]],
    "resize_keyboard": True
}

# ==========================================
# --- منطق البحث والحقن ---
# ==========================================

def generate_random_ip():
    prefix = random.choice(GCP_PREFIXES)
    suffix = f"{random.randint(0, 255)}.{random.randint(1, 254)}"
    return f"{prefix}.{suffix}"

def check_single_proxy(ip, port):
    global invalid_count
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        sock.connect((ip, port))
        
        payload = (
            f"CONNECT {TARGET_HOST}:{TARGET_PORT} HTTP/1.1\r\n"
            f"Host: {SNI_HOST}\r\n\r\n"
        )
        sock.sendall(payload.encode())
        response = sock.recv(4096).decode('utf-8', errors='ignore')
        
        # الفلترة الصارمة
        if "Connection established" not in response:
            invalid_count += 1
            return False, None
        if "<html" in response.lower() or "<body" in response.lower():
            invalid_count += 1
            return False, None
        if "Server:" in response:
            invalid_count += 1
            return False, None
            
        return True, port
            
    except Exception:
        invalid_count += 1
        return False, None
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

def scan_ip_ports(ip):
    results = []
    for port in SCAN_PORTS:
        if not scanning_active: break
        success, p = check_single_proxy(ip, port)
        if success:
            results.append((ip, p))
    return results

def scanner_worker():
    global scanning_active, found_count
    
    print("✅ Scanner: Started")
    send_msg(current_chat_id, "🔥 <b>تم تشغيل الصيد!</b>\n\nجاري البحث عن بروكسي يعمل على نفق `SC-France`...", reply_markup=KEYBOARD)
    
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SCANS) as executor:
        while scanning_active:
            try:
                batch = [generate_random_ip() for _ in range(MAX_CONCURRENT_SCANS)]
                future_to_ip = {executor.submit(scan_ip_ports, ip): ip for ip in batch}
                
                for future in concurrent.futures.as_completed(future_to_ip):
                    if not scanning_active: break
                    
                    results = future.result()
                    if results:
                        for ip, port in results:
                            found_count += 1
                            msg = (
                                f"✅ <b>PROXY FOUND!</b> #{found_count}\n\n"
                                f"🔌 <b>Proxy:</b> <code>{ip}:{port}</code>\n"
                                f"🎯 <b>Target:</b> <code>{TARGET_HOST}:{TARGET_PORT}</code>\n"
                                f"🔓 <b>SNI:</b> <code>{SNI_HOST}</code>\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"✨ <b>Verified & Working</b>"
                            )
                            send_msg(current_chat_id, msg, reply_markup=KEYBOARD)
                            print(f"[+] HIT: {ip}:{port}")
                            time.sleep(0.4)
                
                time.sleep(0.05)

            except Exception as e:
                print(f"Loop Error: {e}")
                time.sleep(1)

    # عند الإيقاف، نحذف آخر تقرير يدوي أو تلقائي إذا وجد ليبدو النظام نظيفاً
    clear_last_status_messages()
    
    stop_msg = (
        f"🛑 <b>تم إيقاف الصيد.</b>\n\n"
        f"✅ النتائج الصالحة: {found_count}\n"
        f"❌ النتائج غير الصالحة: {invalid_count}"
    )
    send_msg(current_chat_id, stop_msg, reply_markup=KEYBOARD)
    print("❌ Scanner: Stopped")

# ==========================================
# --- نظام المراقبة والصيانة (Keep Alive) ---
# ==========================================

def keep_alive_worker():
    """
    مسار خلفي يعمل باستمرار لمراقبة البوت وتنبيهه كل 50 دقيقة
    مع خاصية حذف الرسالة القديمة واستبدالها
    """
    global current_chat_id, found_count, invalid_count, scanning_active, last_auto_report_msg_id
    
    last_report_time = time.time()
    
    while keep_alive_active:
        try:
            time.sleep(60) # فحص كل دقيقة
            
            # 1. Self-Ping
            try:
                port = os.environ.get("PORT", 10000)
                requests.get(f"http://localhost:{port}/", timeout=5)
            except:
                pass

            # 2. إرسال التقرير كل 50 دقيقة (3000 ثانية)
            if time.time() - last_report_time >= 3000:
                if current_chat_id:
                    status_icon = "🟢 نشط" if scanning_active else "🔴 متوقف"
                    
                    if scanning_active:
                        report_text = (
                            f"⏰ <b>تقرير تلقائي (50 دقيقة):</b>\n\n"
                            f"العمل: {status_icon}\n"
                            f"النتائج الصالحة: {found_count}\n"
                            f"النتائج غير الصالحة: {invalid_count}\n"
                            f"🔄 النظام يعمل بكفاءة."
                        )
                    else:
                        report_text = (
                            f"⏰ <b>تقرير تلقائي (50 دقيقة):</b>\n\n"
                            f"العمل: {status_icon}\n"
                            f"النتائج الصالحة: {found_count}\n"
                            f"النتائج غير الصالحة: {invalid_count}\n"
                            f"⚠️ البوت في حالة انتظار."
                        )
                    
                    # استخدام دالة الاستبدال
                    new_msg_id = send_replace_message(current_chat_id, report_text, last_auto_report_msg_id, KEYBOARD)
                    if new_msg_id:
                        last_auto_report_msg_id = new_msg_id
                    last_report_time = time.time()

        except Exception as e:
            print(f"KeepAlive Error: {e}")

# ==========================================
# --- دوال تيليجرام والتحكم (Professional UI) ---
# ==========================================

def send_msg(chat_id, text, reply_markup=None):
    """دالة عادية للإرسال (للرسائل العادية)"""
    if not chat_id: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        payload = {
            "chat_id": chat_id, 
            "text": text, 
            "parse_mode": "HTML", 
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Msg Error: {e}")

def send_replace_message(chat_id, text, old_msg_id=None, reply_markup=None):
    """
    دالة احترافية: تحذف الرسالة القديمة، وترسل الجديدة
    وتعيد رقم الرسالة الجديدة لاستخدامه في الحذف القادم
    """
    # 1. محاولة حذف الرسالة القديمة
    if old_msg_id:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteMessage", json={"chat_id": chat_id, "message_id": old_msg_id}, timeout=5)
        except:
            pass # إذا كانت الرسالة قديمة جداً أو محذوفة، لا نريد توقف البوت

    # 2. إرسال الرسالة الجديدة
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id, 
            "text": text, 
            "parse_mode": "HTML", 
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = requests.post(url, json=payload, timeout=5)
        
        # إرجاع رقم الرسالة الجديدة
        return res.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"Replace Msg Error: {e}")
        return None

def clear_last_status_messages():
    """تستخدم عند إيقاف البوت لمسح التقاير القديمة"""
    global last_manual_status_msg_id, last_auto_report_msg_id
    if current_chat_id:
        try:
            if last_manual_status_msg_id:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteMessage", json={"chat_id": current_chat_id, "message_id": last_manual_status_msg_id})
                last_manual_status_msg_id = None
            if last_auto_report_msg_id:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteMessage", json={"chat_id": current_chat_id, "message_id": last_auto_report_msg_id})
                last_auto_report_msg_id = None
        except:
            pass

def handle_commands(chat_id, text):
    global scanning_active, scanner_thread, current_chat_id, last_manual_status_msg_id
    
    text = text.lower()
    
    if text == "/start" or text == "🚀 بدء الصيد":
        if not scanning_active:
            scanning_active = True
            current_chat_id = chat_id
            scanner_thread = threading.Thread(target=scanner_worker)
            scanner_thread.daemon = True
            scanner_thread.start()
        else:
            send_msg(chat_id, "⚠️ عملية الصيد قيد التشغيل بالفعل!", reply_markup=KEYBOARD)

    elif text == "/stop" or text == "🛑 إيقاف":
        if scanning_active:
            scanning_active = False
            send_msg(chat_id, "⏸ جاري إيقاف البحث...", reply_markup=KEYBOARD)
        else:
            send_msg(chat_id, "🔴 البحث متوقف بالفعل.", reply_markup=KEYBOARD)

    elif text == "/status" or text == "📊 الحالة":
        status_icon = "🟢 نشط" if scanning_active else "🔴 متوقف"
        
        status_text = (
            f"📊 <b>تقرير الحالة الفوري:</b>\n\n"
            f"العمل: {status_icon}\n"
            f"النتائج الصالحة: {found_count}\n"
            f"النتائج غير الصالحة: {invalid_count}\n"
            f"السرعة المتزامنة: {MAX_CONCURRENT_SCANS}"
        )
        
        # استخدام دالة الاستبدال للحالة اليدوية
        new_id = send_replace_message(chat_id, status_text, last_manual_status_msg_id, KEYBOARD)
        if new_id:
            last_manual_status_msg_id = new_id

    elif text == "/help" or text == "❓ مساعدة":
        help_text = (
            "🤖 <b>قائمة الأوامر:</b>\n\n"
            "🚀 <b>بدء الصيد:</b> يبدأ البحث فوراً.\n"
            "🛑 <b>إيقاف:</b> يوقف عملية البحث.\n"
            "📊 <b>الحالة:</b> تقرير فوري (يتم تحديث الرسالة كل ضغطة).\n\n"
            "⏰ <b>ملاحظة:</b> البوت يرسل تقريراً تلقائياً كل 50 دقيقة."
        )
        send_msg(chat_id, help_text, reply_markup=KEYBOARD)

def set_webhook():
    try:
        base_url = os.environ.get('RENDER_EXTERNAL_URL')
        if base_url:
            webhook_url = f"{base_url}/{TOKEN}"
            res = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo").json()
            if res.get('result', {}).get('url') != webhook_url:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
    except:
        pass

# ==========================================
# --- تشغيل السيرفر ---
# ==========================================

@app.route('/')
def home():
    set_webhook()
    return "✅ Professional Proxy Hunter (Koyeb + Auto-Replace)"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            handle_commands(chat_id, text)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"ok": False})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # بدء مسار المراقبة التلقائي
    monitor_thread = threading.Thread(target=keep_alive_worker)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    app.run(host='0.0.0.0', port=port, threaded=True)
