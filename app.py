import os
import requests
import socket
import random
import threading
import time
from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor

# --- إعدادات البوت والهدف ---
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"

# إعدادات الهدف والتمويه (بناءً على طلبك)
TARGET_HOST = "SC-France1.09vpn.com"
TARGET_PORT = 2083
SNI_HOST = "youtube.com"

# المنافذ التي سنبحث عليها
SCAN_PORTS = [33080, 3128, 8080]

# نطاقات جوجل (تم توسيعها لزيادة احتمالات النجاح)
GCP_PREFIXES = [
    '34.80', '34.81', '34.82', '34.83', '34.84', '34.85', '34.86', '34.87', '34.88', '34.89', '34.90', '34.91', '34.92',
    '35.185', '35.186', '35.187', '35.188', '35.190', '35.191', '35.192', '35.200', '35.201', '35.202',
    '104.196', '104.197', '104.198', '104.199',
    '35.240', '35.241', '35.242', '35.243', '35.244'
]

# متغيرات التحكم العام
scanning_active = False
scanner_thread = None
current_chat_id = None
found_count = 0

# عدد الفحوصات المتزامنة (كلما زاد العدد زادت السرعة ولكن يزيد الاستهلاك)
MAX_CONCURRENT_SCANS = 10

app = Flask(__name__)

# --- دوال البحث والحقن (Optimized) ---

def generate_random_ip():
    """توليد IP عشوائي"""
    prefix = random.choice(GCP_PREFIXES)
    suffix = f"{random.randint(0, 255)}.{random.randint(1, 254)}"
    return f"{prefix}.{suffix}"

def check_single_proxy(ip, port):
    """
    فحص بروكسي واحد لمعرفة ما إذا كان يقبل حقن الاتصال.
    تقوم هذه الدالة بإرسال بايلود CONNECT وتفقد الرد.
    """
    sock = None
    try:
        # إنشاء المقبض
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0) # مهلة 2 ثانية
        
        # 1. الاتصال بالبروكسي
        sock.connect((ip, port))
        
        # 2. بناء البايلود الدقيق (Injection Payload)
        # CONNECT [Target] HTTP/1.1
        # Host: [SNI] (للتمويه)
        payload = (
            f"CONNECT {TARGET_HOST}:{TARGET_PORT} HTTP/1.1\r\n"
            f"Host: {SNI_HOST}\r\n\r\n"
        )
        
        # 3. إرسال الحقن
        sock.sendall(payload.encode())
        
        # 4. استقبال الرد
        response = sock.recv(1024).decode('utf-8', errors='ignore')
        
        # 5. التحقق من الرد (200 يعني النجاح)
        if "200 Connection established" in response or "200 OK" in response:
            return True, port
            
    except Exception:
        pass
    finally:
        # إغلاق المقبض بشكل آمن
        if sock:
            try:
                sock.close()
            except:
                pass
    return False, None

def scan_ip_ports(ip):
    """تقوم بفحص الـ IP على جميع المنافذ المطلوبة"""
    results = []
    for port in SCAN_PORTS:
        if not scanning_active: break # إيقاف سريع
        success, p = check_single_proxy(ip, port)
        if success:
            results.append((ip, p))
    return results

def scanner_worker():
    """
    المحرك الرئيسي للبحث.
    يستخدم ThreadPoolExecutor لتسريع البحث عشر مرات.
    """
    global scanning_active, found_count
    
    print(f"🚀 Scanner Started (Concurrency: {MAX_CONCURRENT_SCANS})...")
    send_telegram_msg(current_chat_id, f"💉 **تم تشغيل الصيد المتزامن!**\nالهدف: `{TARGET_HOST}:{TARGET_PORT}`")
    
    # إنشاء تجمع خيوط للمعالجة المتوازية
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SCANS) as executor:
        while scanning_active:
            try:
                # تجهيز قائمة من الـ IPs للفحص في الدفعة الواحدة
                batch = [generate_random_ip() for _ in range(MAX_CONCURRENT_SCANS)]
                
                # بدء الفحص بشكل متزامن
                future_to_ip = {executor.submit(scan_ip_ports, ip): ip for ip in batch}
                
                # معالجة النتائج بمجرد ظهورها
                for future in concurrent.futures.as_completed(future_to_ip):
                    if not scanning_active: break
                    
                    results = future.result()
                    if results:
                        for ip, port in results:
                            found_count += 1
                            msg = (
                                f"✅ **PROXY FOUND!** #{found_count}\n\n"
                                f"🔌 **Proxy:** `{ip}:{port}`\n"
                                f"🎯 **Target:** `{TARGET_HOST}:{TARGET_PORT}`\n"
                                f"🔓 **SNI:** `{SNI_HOST}`\n"
                                f"🤖 **Method:** CONNECT Injection"
                            )
                            send_telegram_msg(current_chat_id, msg)
                            print(f"[+] HIT: {ip}:{port}")
                            # استراحة قصيرة جداً بعد كل نجاح لعدم إزعاج تيليجرام
                            time.sleep(0.5)

            except Exception as e:
                print(f"Scanner Loop Error: {e}")
                time.sleep(1)

    send_telegram_msg(current_chat_id, f"🛑 توقف البحث. إجمالي النتائج: {found_count}")

# --- دوال تيليجرام والسيرفر ---

import concurrent.futures # تم الاستيراد لاحقاً لتوضيح الكود

def send_telegram_msg(chat_id, text):
    if not chat_id: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=5)
    except Exception as e:
        print(f"Error sending msg: {e}")

def set_webhook():
    try:
        base_url = os.environ.get('RENDER_EXTERNAL_URL')
        if base_url:
            webhook_url = f"{base_url}/{TOKEN}"
            # فحص قبل الضبط لتوفير الوقت
            res = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo").json()
            if res.get('result', {}).get('url') != webhook_url:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
                print(f"✅ Webhook Set")
    except:
        pass

@app.route('/')
def home():
    set_webhook()
    return f"🤖 High-Speed Proxy Hunter. Status: {'Scanning' if scanning_active else 'Idle'}"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    global scanning_active, scanner_thread, current_chat_id
    
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "").lower()
            
            if text == "/start":
                if not scanning_active:
                    scanning_active = True
                    current_chat_id = chat_id
                    scanner_thread = threading.Thread(target=scanner_worker)
                    scanner_thread.daemon = True
                    scanner_thread.start()
                else:
                    send_telegram_msg(chat_id, "⚠️ البوت يعمل بالفعل!")
            
            elif text == "/stop":
                if scanning_active:
                    scanning_active = False
                    send_telegram_msg(chat_id, "⏸ جاري إيقاف البحث...")
                else:
                    send_telegram_msg(chat_id, "🔴 البحث متوقف بالفعل.")
                    
            elif text == "/help":
                help_msg = (
                    "🔹 `/start` : بدء الصيد (سريع جداً)\n"
                    "🔹 `/stop` : إيقاف البحث\n"
                    "🔹 `/status` : حالة البوت"
                )
                send_telegram_msg(chat_id, help_msg)
            
            elif text == "/status":
                status = "🟢 نشط (يبحث)" if scanning_active else "🔴 متوقف"
                send_telegram_msg(chat_id, f"📊 **الحالة:** {status}\n\nعدد النتائج: {found_count}")

        return jsonify({"ok": True})
    except Exception as e:
        print(f"Webhook Error: {e}")
        return jsonify({"ok": False})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
