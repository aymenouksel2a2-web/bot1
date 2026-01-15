import os
import requests
import json
import asyncio
import random
import threading
import time
from flask import Flask, request, jsonify

# ==========================================
# --- إعدادات البوت والصياد ---
# ==========================================
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"
app = Flask(__name__)

# المتغيرات المشتركة (الذاكرة الحية)
HUNTING = False
FOUND_PROXIES = []
SCANNED_COUNT = 0
STATUS_MESSAGE_ID = None # لتعديل الرسالة بدلاً من إرسال جديد
CHAT_ID_TARGET = None

# بايلود الفحص (خفيف وسريع)
PAYLOAD_CHECK = (
    b"CONNECT youtube.com:443 HTTP/1.1\r\n"
    b"Host: youtube.com\r\n"
    b"Proxy-Connection: Keep-Alive\r\n\r\n"
)

# نطاقات Google Cloud (الأكثر احتمالاً لوجود بروكسيات)
IP_RANGES = [
    ("34.64", "34.127"),
    ("35.184", "35.240"),
    ("104.154", "104.199"),
]

# ==========================================
# --- المحرك غير المتزامن (Async Engine) ---
# ==========================================

def generate_ip():
    """توليد IP ذكي وسريع"""
    base_start, base_end = random.choice(IP_RANGES)
    start = int(base_start.split('.')[1])
    end = int(base_end.split('.')[1])
    return f"{base_start.split('.')[0]}.{random.randint(start, end)}.{random.randint(0, 255)}.{random.randint(0, 255)}"

async def scan_target(ip, port, semaphore):
    """فحص الهدف بنظام Non-Blocking I/O"""
    global SCANNED_COUNT
    async with semaphore: # للتحكم في عدد العمليات المتزامنة
        SCANNED_COUNT += 1
        try:
            # محاولة الاتصال بمهلة قصيرة جداً (لأننا نبحث عن السريع فقط)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=2.0
            )
            
            # إرسال البايلود
            writer.write(PAYLOAD_CHECK)
            await writer.drain()
            
            # قراءة الرد
            data = await asyncio.wait_for(reader.read(100), timeout=2.0)
            response = data.decode(errors='ignore')
            
            writer.close()
            await writer.wait_closed()

            # التحقق من النجاح
            if "200 Connection" in response or "200 OK" in response:
                proxy = f"{ip}:{port}"
                if proxy not in FOUND_PROXIES:
                    FOUND_PROXIES.append(proxy)
                    print(f"🔥 HIT: {proxy}")
                    
        except:
            pass

async def hunter_loop():
    """حلقة التحكم الرئيسية"""
    global HUNTING
    # Semaphore: يسمح بـ 500 عملية فحص في نفس اللحظة! (رقم خارق)
    sem = asyncio.Semaphore(500)
    
    print(">>> Hunter Engine Started 🚀")
    
    while HUNTING:
        tasks = []
        # تجهيز دفعة من 100 عملية فحص
        for _ in range(100):
            ip = generate_ip()
            # نفحص البورتات الشهيرة
            tasks.append(scan_target(ip, 80, sem))
            tasks.append(scan_target(ip, 3128, sem))
            tasks.append(scan_target(ip, 8080, sem))
            
        # تنفيذ الدفعة كلها دفعة واحدة
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.1) # استراحة قصيرة جداً للمعالج

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(hunter_loop())

# ==========================================
# --- المراسل الذكي (Smart Reporter) ---
# ==========================================
def report_worker():
    """
    هذه الدالة هي الحل لمشكلة التطبيل والسرعة.
    بدلاً من إرسال رسالة كل ثانية، تقوم بتحديث رسالة واحدة كل 5 ثوانٍ.
    """
    global STATUS_MESSAGE_ID
    last_count = 0
    
    while True:
        if HUNTING and CHAT_ID_TARGET:
            # إذا وجدنا بروكسيات جديدة أو تغير العداد
            if len(FOUND_PROXIES) > last_count or SCANNED_COUNT % 1000 == 0:
                last_count = len(FOUND_PROXIES)
                
                # تنسيق الرسالة
                proxies_text = "\n".join([f"`{p}`" for p in FOUND_PROXIES[-10:]]) # آخر 10 فقط
                msg = (
                    f"📡 **RadaR Hunter Active**\n"
                    f"━━━━━━━━━━━━\n"
                    f"🔍 Scanned: `{SCANNED_COUNT}` IPs\n"
                    f"✅ **Hits Found:** `{len(FOUND_PROXIES)}`\n"
                    f"━━━━━━━━━━━━\n"
                    f"Latest Hits:\n{proxies_text}\n"
                    f"━━━━━━━━━━━━\n"
                    f"⚠️ _Updating live..._"
                )
                
                url = f"https://api.telegram.org/bot{TOKEN}/"
                
                try:
                    # إذا لم تكن هناك رسالة سابقة، أرسل واحدة جديدة
                    if STATUS_MESSAGE_ID is None:
                        res = requests.post(url + "sendMessage", json={"chat_id": CHAT_ID_TARGET, "text": msg, "parse_mode": "Markdown"})
                        if res.status_code == 200:
                            STATUS_MESSAGE_ID = res.json()["result"]["message_id"]
                    # إذا كانت موجودة، قم بتعديلها (Edit) لتجنب الحظر
                    else:
                        requests.post(url + "editMessageText", json={
                            "chat_id": CHAT_ID_TARGET, 
                            "message_id": STATUS_MESSAGE_ID, 
                            "text": msg, 
                            "parse_mode": "Markdown"
                        })
                except Exception as e:
                    print(f"Reporting Error: {e}")
                    STATUS_MESSAGE_ID = None # إعادة تعيين في حالة الخطأ
        
        time.sleep(4) # تحديث كل 4 ثواني (آمن جداً لتيليجرام)

# ==========================================
# --- Flask Routes ---
# ==========================================
@app.route('/')
def home(): return "Hunter Bot Running 🔫"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    global HUNTING, CHAT_ID_TARGET, FOUND_PROXIES, SCANNED_COUNT, STATUS_MESSAGE_ID
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            if text == "/hunt":
                if HUNTING:
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "⚠️ الصيد يعمل بالفعل!"})
                else:
                    HUNTING = True
                    CHAT_ID_TARGET = chat_id
                    FOUND_PROXIES = []
                    SCANNED_COUNT = 0
                    STATUS_MESSAGE_ID = None
                    
                    # تشغيل خيط الفحص (Async Loop)
                    new_loop = asyncio.new_event_loop()
                    t = threading.Thread(target=start_background_loop, args=(new_loop,), daemon=True)
                    t.start()
                    
                    # تشغيل خيط المراسل (Reporter)
                    r = threading.Thread(target=report_worker, daemon=True)
                    r.start()
                    
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🚀 **بدء عملية الصيد المكثف!**\nجاري تجهيز المحركات..."})

            elif text == "/stop":
                HUNTING = False
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "🛑 تم إيقاف الصيد.\n\nالنتائج محفوظة في القائمة."})

        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

def set_webhook():
    try:
        base_url = os.environ.get('KOYEB_APP_URL') 
        if base_url:
            if base_url.endswith('/'): base_url = base_url[:-1]
            requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": f"{base_url}/{TOKEN}"})
    except: pass

if __name__ == "__main__":
    set_webhook()
    # نحتاج لبيئة تسمح بالـ Threading
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
