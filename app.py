#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram ID Bot - معرفة معرف تيليجرام
"""

from flask import Flask, request
import requests

BOT_TOKEN = "8211273419:AAG62k2EXmwGYLpQ1DkpnZfFxNC58O8-Sk4"

app = Flask(__name__)

# === دوال API ===
def send(chat_id, text, reply_to=None):
    """إرسال رسالة"""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                     json=payload, timeout=5)
    except:
        pass

# === Flask Routes ===
@app.route('/')
def home():
    return "✅ Telegram ID Bot Running"

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    try:
        d = request.get_json()
        if not d or "message" not in d:
            return {"ok": True}
        
        m = d["message"]
        cid = m["chat"]["id"]
        uid = m["from"]["id"]
        mid = m["message_id"]
        
        # معلومات المستخدم
        first_name = m["from"].get("first_name", "")
        last_name = m["from"].get("last_name", "")
        username = m["from"].get("username", "")
        
        # معلومات الدردشة
        chat_type = m["chat"]["type"]
        chat_title = m["chat"].get("title", "")
        
        # بناء الرسالة
        msg = "🆔 <b>معلومات التيليجرام</b>\n\n"
        msg += f"👤 <b>معرف المستخدم:</b> <code>{uid}</code>\n"
        
        if username:
            msg += f"📝 <b>اسم المستخدم:</b> @{username}\n"
        
        msg += f"📛 <b>الاسم الأول:</b> {first_name}\n"
        
        if last_name:
            msg += f"📛 <b>الاسم الأخير:</b> {last_name}\n"
        
        msg += f"\n💬 <b>معرف الدردشة:</b> <code>{cid}</code>\n"
        msg += f"📂 <b>نوع الدردشة:</b> {chat_type}\n"
        
        if chat_title:
            msg += f"🏷 <b>عنوان المجموعة:</b> {chat_title}\n"
        
        # إرسال الرد
        send(cid, msg, reply_to=mid)
        
        return {"ok": True}
    except:
        return {"ok": False}

# === تشغيل ===
if __name__ == "__main__":
    print("="*50)
    print("🆔 Telegram ID Bot")
    print("="*50)
    print(f"\n🔗 Set webhook:")
    print(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=YOUR_URL/{BOT_TOKEN}\n")
    
    app.run(host='0.0.0.0', port=8080)
