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

# هدف البحث (السيرفر الفرنسي)
TARGET_HOST = "SC-France1.09vpn.com"
TARGET_PORT = 2083
SNI_HOST = "youtube.com"

# المنافذ المحسنة للفحص
SCAN_PORTS = [3128, 33080] 

# نطاقات جوجل (مكان البحث)
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

# العدادات
found_count = 0
invalid_count = 0 # متغير جديد لحساب النتائج المرفوضة

# --- إعدادات السرعة (Koyeb Optimized) ---
# رفعت القيمة إلى 25 لأن Koyeb أقوى وأقرب جغرافياً من Render
MAX_CONCURRENT_SCANS = 25

app = Flask(__name__)

# --- لوحة المفاتيح (Professional UI) ---
KEYBOARD = {
    "keyboard": [["🚀 بدء الصيد", "🛑 إيقاف"], ["📊 الحالة", "❓ مساعدة"]],
    "resize_keyboard": True
}

# ==========================================
# --- منطق البحث والحقن (Strict Mode + Counters) ---
# ==========================================

def generate_random_ip():
    prefix = random.choice(GCP_PREFIXES)
    suffix = f"{random.randint(0, 255)}.{random.randint(1, 254)}"
    return f"{prefix}.{suffix}"

def check_single_proxy(ip, port):
    """
    فحص دقيق وتسجيل الإحصائيات
    """
    global invalid_count # الوصول للمتغير العام لزيادة العداد عند الفشل
    
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5) # 1.5 ثانية تكفي مع قرب السيرفر الألماني
        
        # 1. الاتصال
        sock.connect((ip, port))
        
        # 2. حقن التوجيه
        payload = (
            f"CONNECT {TARGET_HOST}:{TARGET_PORT} HTTP/1.1\r\n"
            f"Host: {SNI_HOST}\r\n\r\n"
        )
        sock.sendall(payload.encode())
        response = sock.recv(4096).decode('utf-8', errors='ignore')
        
        # 3. الفحص الصارم (Strict Filtering)
        if "Connection established" not in response:
            invalid_count += 1 # فشل الشرط الأول
            return False, None
            
        if "<html" in response.lower() or "<body" in response.lower():
            invalid_count += 1 # اكتشف صفحة ويب
            return False, None
            
        if "Server:" in response:
            invalid_count += 1 # اكتشف خادم عادي
            return False, None
            
        # إذا وصل هنا، فهو بروكسي صالح
        return True, port
            
    except Exception:
        # خطأ في الاتصال (Timeout, Refused, etc.)
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
    """
    المحرك الرئيسي للبحث
    """
    global scanning_active, found_count, invalid_count
    
    print("✅ Scanner: Started (Koyeb Mode)")
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

    # رسالة الإيقاف مع ملخص الإحصائيات
    stop_msg = (
        f"🛑 <b>تم إيقاف الصيد.</b>\n\n"
        f"✅ النتائج الصالحة: {found_count}\n"
        f"❌ النتائج غير الصالحة: {invalid_count}"
    )
    send_msg(current_chat_id, stop_msg, reply_markup=KEYBOARD)
    print("❌ Scanner: Stopped")

# ==========================================
# --- دوال تيليجرام والتحكم ---
# ==========================================

def send_msg(chat_id, text, reply_markup=None):
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

def handle_commands(chat_id, text):
    global scanning_active, scanner_thread, current_chat_id
    
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
        
        # تقرير الحالة شامل العدادات
        status_text = (
            f"📊 <b>تقرير الحالة:</b>\n\n"
            f"العمل: {status_icon}\n"
            f"النتائج الصالحة: {found_count}\n"
            f"النتائج غير الصالحة: {invalid_count}\n"
            f"السرعة المتزامنة: {MAX_CONCURRENT_SCANS}"
        )
        send_msg(chat_id, status_text, reply_markup=KEYBOARD)

    elif text == "/help" or text == "❓ مساعدة":
        help_text = (
            "🤖 <b>قائمة الأوامر:</b>\n\n"
            "🚀 <b>بدء الصيد:</b> يبدأ البحث عن البروكسيات فوراً.\n"
            "🛑 <b>إيقاف:</b> يوقف عملية البحث ويوفر الموارد.\n"
            "📊 <b>الحالة:</b> لمعرفة عدد النتائج الصالحة والمرفوضة.\n\n"
            "⚡ <b>الوضع:</b> صيد ذكي (يمنع البروكسيات الكاذبة)."
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
# --- مسارات الويب ---
# ==========================================

@app.route('/')
def home():
    set_webhook()
    return "✅ Professional Proxy Hunter (Koyeb Optimized)"

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
    app.run(host='0.0.0.0', port=port, threaded=True)
