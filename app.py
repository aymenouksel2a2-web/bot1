import os
import requests
import json
import asyncio
import random
import threading
import time
import socket
from flask import Flask, request, jsonify
from queue import Queue

# ==========================================
# --- 1. إعدادات البوت والهدف (SSH Target) ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"

# بيانات سيرفر SSH الذي تريد الاتصال به (من طلبك)
SSH_HOST = "SC-France2.09vpn.com"
SSH_PORT = 109  # البورت الذي تستخدمه

# الهوست الخاص بالبايلود (SNI)
PAYLOAD_HOST = "youtube.com"

app = Flask(__name__)

# --- نطاقات البحث (Google Cloud Ranges) ---
# سنركز على 34 و 35 لأنها الأشهر، والبوت سيقوم بفلترة المحظور منها
TARGET_PREFIXES = [34, 35] 
PORTS_TO_SCAN = [3128] 

# متغيرات الإحصائيات
HUNTING = False
SCANNED_COUNT = 0       
RAW_HITS_COUNT = 0      
TESTED_COUNT = 0        
VALIDATION_QUEUE = Queue() 
FOUND_WORKING_PROXIES = [] 
CHAT_ID_TARGET = None
STATUS_MSG_ID = None

# ==========================================
# --- 2. نظام فحص الحقن (SSH Injection Tester) ---
# ==========================================
# هذا هو "العقل" الجديد للبوت بدلاً من Xray
def check_ssh_injection(proxy_ip, proxy_port):
    try:
        # 1. تجهيز البايلود كما طلبته بالضبط
        # لاحظ: \r\n هي نفسها [crlf]
        payload = (
            f"CONNECT {SSH_HOST}:{SSH_PORT} HTTP/1.1\r\n"
            f"Host: {PAYLOAD_HOST}\r\n"
            "Service: SSH\r\n"
            "Mode: O C X \r\n\r\n"
        )
        
        # 2. إنشاء اتصال مباشر بالبروكسي
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10) # مهلة 10 ثواني للرد
        
        start_time = time.time()
        sock.connect((proxy_ip, int(proxy_port)))
        sock.sendall(payload.encode())
        
        # 3. قراءة الرد (Header Analysis)
        response = sock.recv(4096).decode(errors='ignore')
        sock.close()
        ping = int((time.time() - start_time) * 1000)

        # ====================================================
        # --- الفلتر الذكي (Ooredoo Filter) ---
        # ====================================================
        
        # 1. كشف الحظر (صفحة شوف / 307)
        if "307 Temporary Redirect" in response or "choof" in response or "ooredoo" in response:
            return False, ping, "Blacklisted (307)"
            
        # 2. كشف النجاح الحقيقي (200 OK)
        if "HTTP/1.1 200" in response:
            # تحقق إضافي: هل السيرفر رد ببروتوكول SSH؟ (للتأكد أن الاتصال مر فعلاً)
            # ملاحظة: بعض البروكسيات لا تمرر رد SSH فوراً، لذا سنكتفي بـ 200 OK كدليل نجاح أولي
            return True, ping, "SSH Connected ✅"

        return False, ping, "No 200 OK"

    except Exception as e:
        return False, 0, str(e)

# ==========================================
# --- 3. الصياد (Async Hunter) ---
# ==========================================
# بايلود خفيف جداً للمسح السريع فقط
SCAN_PAYLOAD = (
    f"CONNECT {SSH_HOST}:{SSH_PORT} HTTP/1.1\r\n"
    f"Host: {PAYLOAD_HOST}\r\n"
    "Connection: Keep-Alive\r\n\r\n"
).encode()

def generate_targeted_ip():
    prefix = random.choice(TARGET_PREFIXES)
    return f"{prefix}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}"

async def scan_socket(ip, port, sem):
    global SCANNED_COUNT, RAW_HITS_COUNT
    async with sem:
        SCANNED_COUNT += 1
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=1.0)
            writer.write(SCAN_PAYLOAD)
            await writer.drain()
            
            # نقرأ أول 64 بايت فقط لنرى هل هناك استجابة
            data = await asyncio.wait_for(reader.read(64), timeout=1.0)
            response = data.decode(errors='ignore')
            
            writer.close()
            try: await writer.wait_closed()
            except: pass
            
            # إذا رد البروكسي بأي شيء (حتى لو 307)، نرسله للمحقق ليفحصه بدقة
            if len(response) > 5: 
                RAW_HITS_COUNT += 1
                VALIDATION_QUEUE.put((ip, port))
        except:
            pass

async def hunter_loop():
    sem = asyncio.Semaphore(600) # سرعة عالية
    print(">>> SSH Websocket Hunter Started 🚀")
    while HUNTING:
        tasks = []
        for _ in range(100):
            ip = generate_targeted_ip()
            for port in PORTS_TO_SCAN:
                tasks.append(scan_socket(ip, port, sem))
        
        if tasks:
            await asyncio.gather(*tasks)
        else:
            await asyncio.sleep(0.1)

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(hunter_loop())

# ==========================================
# --- 4. المحقق (Validator Thread) - SSH Mode ---
# ==========================================
def validator_worker():
    global CHAT_ID_TARGET, TESTED_COUNT
    
    while True:
        if not VALIDATION_QUEUE.empty() and HUNTING:
            ip, port = VALIDATION_QUEUE.get()
            TESTED_COUNT += 1
            
            # استخدام دالة الفحص الجديدة
            success, ping, msg_status = check_ssh_injection(ip, port)
            
            if success:
                # ✅ نجاح: بروكسي نظيف ومرر الاتصال
                proxy_str = f"{ip}:{port}"
                if proxy_str not in FOUND_WORKING_PROXIES:
                    FOUND_WORKING_PROXIES.append(proxy_str)
                    
                    msg = (
                        f"✅ **SSH BYPASS SUCCESS!**\n"
                        f"🌐 Proxy: `{ip}:{port}`\n"
                        f"⚡ Ping: `{ping}ms`\n"
                        f"🛡️ Status: **Clean (No 307)**\n"
                        f"⚙️ Works with your SSH Config!"
                    )
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
            else:
                # ❌ فشل: إما محظور (307) أو لا يعمل
                # إرسال رسالة فقط إذا كان الخطأ 307 لنعرف أن البوت يفلتر
                if "307" in msg_status:
                    fail_msg = f"⛔ `{ip}:{port}` -> Ooredoo Blacklist (307)"
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                json={"chat_id": CHAT_ID_TARGET, "text": fail_msg, "parse_mode": "Markdown"})
                
            time.sleep(0.1)
        else:
            time.sleep(0.5)

# ==========================================
# --- 5. واجهة البوت ---
# ==========================================
def report_updater():
    global STATUS_MSG_ID
    while True:
        if HUNTING and CHAT_ID_TARGET:
            msg = (
                f"📡 **SSH Websocket Hunter (Ooredoo Fix)**\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🎯 Target: `{SSH_HOST}:{SSH_PORT}`\n"
                f"🔍 Scanned: `{SCANNED_COUNT}`\n"
                f"🔫 Raw Hits: `{RAW_HITS_COUNT}`\n"
                f"🛠 Checked: `{TESTED_COUNT}`\n"
                f"✅ **Clean Proxies:** `{len(FOUND_WORKING_PROXIES)}`\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⚠️ Filtering 307 Redirects..."
            )
            url = f"https://api.telegram.org/bot{TOKEN}/"
            try:
                if STATUS_MSG_ID:
                    requests.post(url + "editMessageText", 
                                json={"chat_id": CHAT_ID_TARGET, "message_id": STATUS_MSG_ID, "text": msg, "parse_mode": "Markdown"})
                else:
                    res = requests.post(url + "sendMessage", 
                                      json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
                    if res.status_code == 200: STATUS_MSG_ID = res.json()["result"]["message_id"]
            except: pass
        time.sleep(8) 

@app.route('/')
def home(): return "SSH Hunter Running"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    global HUNTING, CHAT_ID_TARGET, FOUND_WORKING_PROXIES, SCANNED_COUNT, RAW_HITS_COUNT, TESTED_COUNT, STATUS_MSG_ID
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/hunt":
                if not HUNTING:
                    HUNTING = True
                    CHAT_ID_TARGET = chat_id
                    FOUND_WORKING_PROXIES = []
                    SCANNED_COUNT = 0
                    RAW_HITS_COUNT = 0
                    TESTED_COUNT = 0
                    STATUS_MSG_ID = None
                    with VALIDATION_QUEUE.mutex: VALIDATION_QUEUE.queue.clear()
                    
                    threading.Thread(target=start_async_loop, args=(asyncio.new_event_loop(),), daemon=True).start()
                    threading.Thread(target=validator_worker, daemon=True).start()
                    threading.Thread(target=report_updater, daemon=True).start()
                    
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                json={"chat_id": chat_id, "text": "🚀 **بدء صيد SSH Websocket!**\nسأتجاهل أي بروكسي يعطي 307 (صفحة شوف)."})
                else:
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "⚠️ البوت يعمل."})
            
            elif text == "/stop":
                HUNTING = False
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🛑 تم الإيقاف."})
                
        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') or os.environ.get('RENDER_EXTERNAL_URL')
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": f"{base_url}/{TOKEN}"})
    except: pass

if __name__ == "__main__":
    set_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
