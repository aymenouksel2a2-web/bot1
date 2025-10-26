#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MeowSSH Bot - Lightweight Version with Reply Feature
- Optimized for 0.1 CPU / 512MB RAM
- Reply to user message for easy tracking
- Show previous account info when waiting
- Auto cleanup old data
"""

from flask import Flask, request
import requests, time
from datetime import datetime, timedelta

BOT_TOKEN   = "8288789847:AAHSGOPiKHtZU1b3qpfoz5h4ByeUTco0gv8"
CHANNEL_ID  = -1002479732983
CHANNEL_USER= "@aynHTTPXCHAT"

app = Flask(__name__)

# قواميس خفيفة - تُنظف تلقائياً
user_accounts = {}  # {user_id: {"time": datetime, "data": {...}}}
user_clicks = {}    # {user_id: timestamp}
user_blocks = {}    # {user_id: datetime}

# إعدادات
MAX_USERS_IN_MEMORY = 100  # أقصى عدد مستخدمين محفوظين
CLEANUP_INTERVAL = 50      # تنظيف كل 50 طلب
request_counter = 0

# === تنظيف الذاكرة تلقائياً ===
def cleanup_old_data():
    """حذف البيانات القديمة لتوفير الذاكرة"""
    global user_accounts, user_clicks, user_blocks
    
    now = datetime.now()
    
    # حذف الحسابات القديمة (أكثر من 3 ساعات)
    old_accounts = [uid for uid, data in user_accounts.items() 
                    if (now - data["time"]).total_seconds() > 10800]
    for uid in old_accounts:
        del user_accounts[uid]
    
    # حذف الضغطات القديمة (أكثر من دقيقة)
    old_clicks = [uid for uid, t in user_clicks.items() 
                  if time.time() - t > 60]
    for uid in old_clicks:
        del user_clicks[uid]
    
    # حذف الحظر المنتهي
    old_blocks = [uid for uid, dt in user_blocks.items() 
                  if (now - dt).total_seconds() > 30]
    for uid in old_blocks:
        del user_blocks[uid]
    
    # إذا تجاوز الحد، احذف الأقدم
    if len(user_accounts) > MAX_USERS_IN_MEMORY:
        sorted_users = sorted(user_accounts.items(), 
                            key=lambda x: x[1]["time"])
        for uid, _ in sorted_users[:20]:
            del user_accounts[uid]

# === إنشاء حساب SSH ===
def create_ssh():
    """إنشاء حساب SSH - optimized"""
    url = "https://painel.meowssh.shop:5000/test_ssh_public"
    hdr = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    r = requests.post(url, headers=hdr, json={"store_owner_id": 1}, timeout=8)
    r.raise_for_status()
    d = r.json()
    
    return {
        "u": d['Usuario'],
        "p": d['Senha'],
        "l": d['limite'],
        "v": d['Expiracao'].replace("hora(s)", "ساعات").replace("horas", "ساعات").replace("hora", "ساعة"),
        "t": datetime.now().strftime('%H:%M')
    }

# === دوال API خفيفة ===
def send(chat_id, text, markup=None, reply_to=None):
    """إرسال رسالة - optimized with reply support"""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                     json=payload, timeout=5)
    except:
        pass

def delete(chat_id, msg_id):
    """حذف رسالة - optimized"""
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
                     json={"chat_id": chat_id, "message_id": msg_id}, timeout=3)
    except:
        pass

# === دوال مساعدة ===
def time_text(sec):
    """تحويل ثواني إلى نص"""
    if sec <= 0:
        return "0"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    
    if h > 0:
        return f"{h}س {m}د"
    elif m > 0:
        return f"{m}د {s}ث"
    else:
        return f"{s}ث"

def can_create(uid):
    """فحص 3 ساعات"""
    if uid not in user_accounts:
        return True, 0
    
    elapsed = (datetime.now() - user_accounts[uid]["time"]).total_seconds()
    remaining = 10800 - int(elapsed)
    
    return remaining <= 0, max(0, remaining)

def can_click(uid):
    """فحص 30 ثانية"""
    if uid not in user_clicks:
        return True, 0
    
    elapsed = time.time() - user_clicks[uid]
    remaining = 30 - int(elapsed)
    
    return remaining <= 0, max(0, remaining)

def is_blocked(uid):
    """فحص الحظر"""
    if uid not in user_blocks:
        return False, 0
    
    elapsed = (datetime.now() - user_blocks[uid]).total_seconds()
    remaining = 30 - int(elapsed)
    
    if remaining <= 0:
        del user_blocks[uid]
        return False, 0
    
    return True, int(remaining)

# === لوحات مفاتيح ===
KB = {"keyboard": [[{"text": "إنشاء حساب🐱"}, {"text": "تحميل📱"}]], "resize_keyboard": True}
DL = {"inline_keyboard": [[{"text": "📥 تحميل", "url": "https://t.me/aynhttpx/26"}]]}

# === معالجات ===
def h_start(cid):
    send(cid, "🐱 <b>أهلاً بك!</b>\n\n⏰ حساب مجاني كل 3 ساعات", KB)

def h_dl(cid):
    send(cid, "📱 <b>تطبيق القط</b>\n\nاضغط للتحميل ⬇️", DL)

def h_create(cid, uid, mid):
    global request_counter
    
    # تنظيف دوري
    request_counter += 1
    if request_counter % CLEANUP_INTERVAL == 0:
        cleanup_old_data()
    
    # 1. فحص الحظر
    blocked, b_time = is_blocked(uid)
    if blocked:
        delete(cid, mid)
        send(cid, f"⏳ <b>محظور مؤقتاً</b>\n\n⏱ الوقت المتبقي: {b_time}ث", reply_to=mid)
        return
    
    # 2. فحص Anti-Spam
    ok_click, c_time = can_click(uid)
    if not ok_click:
        delete(cid, mid)
        user_blocks[uid] = datetime.now()
        send(cid, 
            f"⚠️ <b>ضغط متكرر!</b>\n\n"
            f"⏳ محظور لـ: 30 ثانية\n"
            f"⏱ متبقي من الضغطة السابقة: {c_time}ث", 
            reply_to=mid)
        return
    
    # 3. تسجيل الضغطة
    user_clicks[uid] = time.time()
    
    # 4. فحص 3 ساعات
    ok_create, a_time = can_create(uid)
    
    if ok_create:
        # ✅ إنشاء حساب جديد
        try:
            d = create_ssh()
            user_accounts[uid] = {"time": datetime.now(), "data": d}
            
            send(cid, 
                f"🐱 <b>تم إنشاء حساب القط!</b> - {d['t']}\n\n"
                f"👤 <b>اسم المستخدم:</b> <code>{d['u']}</code>\n"
                f"🔑 <b>كلمة المرور:</b> <code>{d['p']}</code>\n"
                f"📊 <b>الحد الأقصى:</b> {d['l']}\n"
                f"⏳ <b>مدة الصلاحية:</b> {d['v']}\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 <b>نصيحة:</b> احفظ هذه المعلومات الآن!",
                reply_to=mid)
        except Exception as e:
            send(cid, f"⚠️ <b>خطأ في إنشاء الحساب!</b>\n\nحاول مرة أخرى بعد قليل.", reply_to=mid)
    else:
        # ❌ انتظر - عرض معلومات الحساب السابق
        if uid in user_accounts and "data" in user_accounts[uid]:
            d = user_accounts[uid]["data"]
            send(cid, 
                f"⏰ <b>يجب الانتظار قبل حساب جديد!</b>\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📋 <b>حسابك الحالي:</b>\n\n"
                f"👤 <b>اسم المستخدم:</b> <code>{d['u']}</code>\n"
                f"🔑 <b>كلمة المرور:</b> <code>{d['p']}</code>\n"
                f"📊 <b>الحد الأقصى:</b> {d['l']}\n"
                f"⏳ <b>مدة الصلاحية:</b> {d['v']}\n"
                f"🕐 <b>تم الإنشاء:</b> {d['t']}\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⏳ <b>الوقت المتبقي:</b> {time_text(a_time)}\n\n"
                f"💡 <b>ملاحظة:</b> حساب جديد كل 3 ساعات فقط",
                reply_to=mid)
        else:
            # في حالة عدم وجود بيانات (نادر الحدوث)
            send(cid, 
                f"⏰ <b>يجب الانتظار قبل حساب جديد!</b>\n\n"
                f"⏳ <b>الوقت المتبقي:</b> {time_text(a_time)}\n\n"
                f"💡 <b>ملاحظة:</b> حساب جديد كل 3 ساعات فقط",
                reply_to=mid)

# === Flask Routes ===
@app.route('/')
def home():
    return f"✅ Running | Users: {len(user_accounts)} | Clicks: {len(user_clicks)}"

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    try:
        d = request.get_json()
        if not d or "message" not in d:
            return {"ok": True}
        
        m = d["message"]
        cid = m["chat"]["id"]
        uid = m["from"]["id"]
        txt = m.get("text", "")
        mid = m["message_id"]
        
        # فحص المجموعة
        if cid != CHANNEL_ID:
            send(cid, f"📍 <b>عذراً!</b>\n\nالبوت يعمل فقط في المجموعة:\n{CHANNEL_USER}")
            return {"ok": True}
        
        # المعالجات
        if txt == "/start":
            h_start(cid)
        elif txt == "تحميل📱":
            h_dl(cid)
        elif txt == "إنشاء حساب🐱":
            h_create(cid, uid, mid)
        
        return {"ok": True}
    except:
        return {"ok": False}

# === تشغيل ===
if __name__ == "__main__":
    print("="*50)
    print("🐱 MeowSSH Bot - Lightweight Mode + Reply")
    print("="*50)
    print(f"💾 Max users in memory: {MAX_USERS_IN_MEMORY}")
    print(f"🧹 Auto cleanup every: {CLEANUP_INTERVAL} requests")
    print(f"⚡ Optimized for: 0.1 CPU / 512MB RAM")
    print(f"💬 Reply feature: Enabled")
    print(f"📋 Show previous account: Enabled")
    print("="*50)
    print(f"\n🔗 Set webhook:")
    print(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=YOUR_URL/{BOT_TOKEN}\n")
    
    app.run(host='0.0.0.0', port=8080, threaded=False)
