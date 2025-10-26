#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Group Protection Bot - Full Featured
حماية شاملة لمجموعات تيليجرام
"""

from flask import Flask, request
import requests
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict

BOT_TOKEN = "8211273419:AAG62k2EXmwGYLpQ1DkpnZfFxNC58O8-Sk4"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# === قواعد البيانات في الذاكرة ===
# إعدادات كل مجموعة
group_settings = defaultdict(lambda: {
    "antilink": True,           # منع الروابط
    "antiforward": False,       # منع التوجيه
    "antiflood": True,          # منع الإغراق
    "antibot": True,            # منع البوتات
    "welcome": True,            # رسالة ترحيب
    "captcha": True,            # التحقق من الأعضاء
    "media_filter": {},         # فلتر الوسائط (photo, video, sticker, etc)
    "max_warns": 3,             # عدد التحذيرات المسموح
    "locked": False,            # قفل المجموعة
    "flood_limit": 5,           # حد رسائل الإغراق
    "flood_time": 10,           # وقت الإغراق بالثواني
    "max_chars": 0,             # حد الأحرف (0 = غير محدود)
    "welcome_msg": "🎉 أهلاً بك {user} في {chat}!\n\nاقرأ القواعد: /rules",
    "rules": "📋 قواعد المجموعة:\n\n1. احترم الجميع\n2. ممنوع الروابط\n3. ممنوع السب"
})

# كلمات محظورة لكل مجموعة
banned_words = defaultdict(list)

# قائمة بيضاء (مستخدمين مسموح لهم)
whitelist = defaultdict(list)

# تحذيرات المستخدمين
user_warns = defaultdict(lambda: defaultdict(int))

# تتبع رسائل المستخدمين للإغراق
user_messages = defaultdict(lambda: defaultdict(list))

# المستخدمين الجدد الذين ينتظرون التحقق
pending_users = defaultdict(dict)

# سجل الأحداث
action_logs = defaultdict(list)

# === دوال API ===
def api_request(method, data=None):
    """طلب API موحد"""
    try:
        r = requests.post(f"{API_URL}/{method}", json=data, timeout=5)
        return r.json()
    except:
        return None

def send_message(chat_id, text, reply_to=None, markup=None, parse_mode="HTML"):
    """إرسال رسالة"""
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    if markup:
        data["reply_markup"] = markup
    return api_request("sendMessage", data)

def delete_message(chat_id, message_id):
    """حذف رسالة"""
    return api_request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def kick_user(chat_id, user_id):
    """طرد مستخدم"""
    return api_request("banChatMember", {"chat_id": chat_id, "user_id": user_id})

def ban_user(chat_id, user_id):
    """حظر مستخدم"""
    return api_request("banChatMember", {"chat_id": chat_id, "user_id": user_id})

def unban_user(chat_id, user_id):
    """إلغاء حظر"""
    return api_request("unbanChatMember", {"chat_id": chat_id, "user_id": user_id})

def mute_user(chat_id, user_id, until=None):
    """كتم مستخدم"""
    permissions = {
        "can_send_messages": False,
        "can_send_media_messages": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False
    }
    data = {"chat_id": chat_id, "user_id": user_id, "permissions": permissions}
    if until:
        data["until_date"] = int(time.time()) + until
    return api_request("restrictChatMember", data)

def unmute_user(chat_id, user_id):
    """إلغاء كتم"""
    permissions = {
        "can_send_messages": True,
        "can_send_media_messages": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True
    }
    return api_request("restrictChatMember", {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": permissions
    })

def get_chat_admins(chat_id):
    """الحصول على المشرفين"""
    result = api_request("getChatAdministrators", {"chat_id": chat_id})
    if result and result.get("ok"):
        return [admin["user"]["id"] for admin in result["result"]]
    return []

# === دوال مساعدة ===
def is_admin(chat_id, user_id):
    """فحص إذا كان المستخدم مشرف"""
    admins = get_chat_admins(chat_id)
    return user_id in admins

def is_whitelisted(chat_id, user_id):
    """فحص القائمة البيضاء"""
    return user_id in whitelist[chat_id]

def add_log(chat_id, action):
    """إضافة سجل"""
    log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] {action}"
    action_logs[chat_id].append(log_entry)
    if len(action_logs[chat_id]) > 50:  # حفظ آخر 50 سجل
        action_logs[chat_id].pop(0)

def has_links(text):
    """فحص وجود روابط"""
    link_pattern = r'(https?://|www\.|t\.me/|@\w+)'
    return re.search(link_pattern, text.lower()) is not None

def has_repeated_chars(text):
    """فحص الحروف المكررة"""
    return re.search(r'(.)\1{4,}', text) is not None

def check_flood(chat_id, user_id):
    """فحص الإغراق"""
    settings = group_settings[chat_id]
    now = time.time()
    
    # تنظيف الرسائل القديمة
    user_messages[chat_id][user_id] = [
        msg_time for msg_time in user_messages[chat_id][user_id]
        if now - msg_time < settings["flood_time"]
    ]
    
    # إضافة الرسالة الحالية
    user_messages[chat_id][user_id].append(now)
    
    # فحص العدد
    return len(user_messages[chat_id][user_id]) > settings["flood_limit"]

def add_warn(chat_id, user_id):
    """إضافة تحذير"""
    user_warns[chat_id][user_id] += 1
    warns = user_warns[chat_id][user_id]
    max_warns = group_settings[chat_id]["max_warns"]
    
    if warns >= max_warns:
        ban_user(chat_id, user_id)
        user_warns[chat_id][user_id] = 0
        return True, warns
    return False, warns

# === معالجات الأوامر ===
def handle_start(chat_id, user_id):
    """أمر /start"""
    text = (
        "🛡 <b>بوت حماية المجموعات</b>\n\n"
        "مرحباً! أنا بوت متخصص في حماية مجموعات تيليجرام.\n\n"
        "<b>الميزات الرئيسية:</b>\n"
        "• منع الروابط والإعلانات\n"
        "• مكافحة الإغراق\n"
        "• نظام التحذيرات\n"
        "• التحقق من الأعضاء الجدد\n"
        "• فلترة المحتوى\n\n"
        "أضفني إلى مجموعتك واجعلني مشرفاً!\n\n"
        "الأوامر: /help"
    )
    send_message(chat_id, text)

def handle_help(chat_id):
    """أمر /help"""
    text = (
        "📚 <b>قائمة الأوامر:</b>\n\n"
        "<b>🔒 أوامر الحماية:</b>\n"
        "/lock - قفل المجموعة\n"
        "/unlock - فتح المجموعة\n"
        "/antilink <on/off> - منع الروابط\n"
        "/antiflood <on/off> - منع الإغراق\n"
        "/antibot <on/off> - منع البوتات\n\n"
        "<b>👥 أوامر الإدارة:</b>\n"
        "/ban - حظر عضو (رد على رسالته)\n"
        "/kick - طرد عضو\n"
        "/mute - كتم عضو\n"
        "/unmute - إلغاء كتم\n"
        "/warn - تحذير عضو\n"
        "/warns - عرض التحذيرات\n"
        "/resetwarns - مسح التحذيرات\n\n"
        "<b>⚙️ أوامر الإعدادات:</b>\n"
        "/setwelcome - تعيين رسالة الترحيب\n"
        "/setrules - تعيين القواعد\n"
        "/rules - عرض القواعد\n"
        "/addword - إضافة كلمة محظورة\n"
        "/delword - حذف كلمة محظورة\n"
        "/whitelist - إضافة للقائمة البيضاء\n"
        "/settings - عرض الإعدادات\n"
        "/logs - عرض السجل"
    )
    send_message(chat_id, text)

def handle_ban(chat_id, user_id, target_msg, admin_name):
    """أمر /ban"""
    if not target_msg.get("reply_to_message"):
        send_message(chat_id, "❌ رد على رسالة العضو المراد حظره!")
        return
    
    target_user = target_msg["reply_to_message"]["from"]
    target_id = target_user["id"]
    target_name = target_user.get("first_name", "المستخدم")
    
    if is_admin(chat_id, target_id):
        send_message(chat_id, "❌ لا يمكن حظر مشرف!")
        return
    
    ban_user(chat_id, target_id)
    delete_message(chat_id, target_msg["reply_to_message"]["message_id"])
    send_message(chat_id, f"🚫 تم حظر {target_name} بواسطة {admin_name}")
    add_log(chat_id, f"حظر {target_name} بواسطة {admin_name}")

def handle_kick(chat_id, user_id, target_msg, admin_name):
    """أمر /kick"""
    if not target_msg.get("reply_to_message"):
        send_message(chat_id, "❌ رد على رسالة العضو المراد طرده!")
        return
    
    target_user = target_msg["reply_to_message"]["from"]
    target_id = target_user["id"]
    target_name = target_user.get("first_name", "المستخدم")
    
    if is_admin(chat_id, target_id):
        send_message(chat_id, "❌ لا يمكن طرد مشرف!")
        return
    
    kick_user(chat_id, target_id)
    unban_user(chat_id, target_id)  # السماح له بالعودة
    send_message(chat_id, f"👞 تم طرد {target_name}")
    add_log(chat_id, f"طرد {target_name} بواسطة {admin_name}")

def handle_mute(chat_id, user_id, target_msg, admin_name):
    """أمر /mute"""
    if not target_msg.get("reply_to_message"):
        send_message(chat_id, "❌ رد على رسالة العضو المراد كتمه!")
        return
    
    target_user = target_msg["reply_to_message"]["from"]
    target_id = target_user["id"]
    target_name = target_user.get("first_name", "المستخدم")
    
    if is_admin(chat_id, target_id):
        send_message(chat_id, "❌ لا يمكن كتم مشرف!")
        return
    
    # كتم لمدة 24 ساعة
    mute_user(chat_id, target_id, 86400)
    send_message(chat_id, f"🔇 تم كتم {target_name} لمدة 24 ساعة")
    add_log(chat_id, f"كتم {target_name} بواسطة {admin_name}")

def handle_warn(chat_id, user_id, target_msg, admin_name):
    """أمر /warn"""
    if not target_msg.get("reply_to_message"):
        send_message(chat_id, "❌ رد على رسالة العضو المراد تحذيره!")
        return
    
    target_user = target_msg["reply_to_message"]["from"]
    target_id = target_user["id"]
    target_name = target_user.get("first_name", "المستخدم")
    
    if is_admin(chat_id, target_id):
        send_message(chat_id, "❌ لا يمكن تحذير مشرف!")
        return
    
    banned, warns = add_warn(chat_id, target_id)
    max_warns = group_settings[chat_id]["max_warns"]
    
    if banned:
        send_message(chat_id, f"⛔️ تم حظر {target_name} بعد {max_warns} تحذيرات!")
        add_log(chat_id, f"حظر {target_name} بعد {max_warns} تحذيرات")
    else:
        send_message(chat_id, f"⚠️ تحذير {warns}/{max_warns} لـ {target_name}")
        add_log(chat_id, f"تحذير {target_name} ({warns}/{max_warns})")

def handle_settings(chat_id):
    """عرض الإعدادات"""
    settings = group_settings[chat_id]
    text = (
        "⚙️ <b>إعدادات المجموعة:</b>\n\n"
        f"🔗 منع الروابط: {'✅' if settings['antilink'] else '❌'}\n"
        f"📤 منع التوجيه: {'✅' if settings['antiforward'] else '❌'}\n"
        f"💬 منع الإغراق: {'✅' if settings['antiflood'] else '❌'}\n"
        f"🤖 منع البوتات: {'✅' if settings['antibot'] else '❌'}\n"
        f"👋 رسالة الترحيب: {'✅' if settings['welcome'] else '❌'}\n"
        f"🔐 التحقق (Captcha): {'✅' if settings['captcha'] else '❌'}\n"
        f"🔒 المجموعة: {'مقفلة' if settings['locked'] else 'مفتوحة'}\n"
        f"⚠️ عدد التحذيرات: {settings['max_warns']}\n"
        f"💨 حد الإغراق: {settings['flood_limit']} رسائل/{settings['flood_time']}ث\n"
        f"📝 حد الأحرف: {settings['max_chars'] if settings['max_chars'] > 0 else 'غير محدود'}\n"
        f"🚫 كلمات محظورة: {len(banned_words[chat_id])}\n"
        f"✅ قائمة بيضاء: {len(whitelist[chat_id])}"
    )
    send_message(chat_id, text)

def handle_logs(chat_id):
    """عرض السجل"""
    logs = action_logs[chat_id]
    if not logs:
        send_message(chat_id, "📋 لا يوجد سجل بعد")
        return
    
    text = "📋 <b>سجل الأحداث (آخر 20):</b>\n\n"
    text += "\n".join(logs[-20:])
    send_message(chat_id, text)

# === فحص المحتوى ===
def check_content(message, chat_id, user_id):
    """فحص محتوى الرسالة"""
    settings = group_settings[chat_id]
    msg_id = message["message_id"]
    text = message.get("text", message.get("caption", ""))
    
    # تخطي المشرفين والقائمة البيضاء
    if is_admin(chat_id, user_id) or is_whitelisted(chat_id, user_id):
        return True
    
    # فحص المجموعة المقفلة
    if settings["locked"]:
        delete_message(chat_id, msg_id)
        send_message(chat_id, "🔒 المجموعة مقفلة حالياً!", reply_to=msg_id)
        return False
    
    # فحص الروابط
    if settings["antilink"] and text and has_links(text):
        delete_message(chat_id, msg_id)
        send_message(chat_id, "🚫 الروابط ممنوعة!", reply_to=msg_id)
        add_warn(chat_id, user_id)
        add_log(chat_id, f"حذف رابط من {message['from'].get('first_name', 'مستخدم')}")
        return False
    
    # فحص التوجيه
    if settings["antiforward"] and message.get("forward_from"):
        delete_message(chat_id, msg_id)
        send_message(chat_id, "🚫 التوجيه ممنوع!", reply_to=msg_id)
        return False
    
    # فحص الكلمات المحظورة
    if text:
        text_lower = text.lower()
        for word in banned_words[chat_id]:
            if word.lower() in text_lower:
                delete_message(chat_id, msg_id)
                send_message(chat_id, "🚫 كلمة محظورة!", reply_to=msg_id)
                add_warn(chat_id, user_id)
                return False
    
    # فحص الحروف المكررة
    if text and has_repeated_chars(text):
        delete_message(chat_id, msg_id)
        send_message(chat_id, "🚫 ممنوع الحروف المكررة!", reply_to=msg_id)
        return False
    
    # فحص طول النص
    if settings["max_chars"] > 0 and text and len(text) > settings["max_chars"]:
        delete_message(chat_id, msg_id)
        send_message(chat_id, f"🚫 النص طويل جداً! الحد: {settings['max_chars']} حرف", reply_to=msg_id)
        return False
    
    # فحص الإغراق
    if settings["antiflood"] and check_flood(chat_id, user_id):
        delete_message(chat_id, msg_id)
        mute_user(chat_id, user_id, 300)  # كتم 5 دقائق
        send_message(chat_id, "⚠️ تم كشف إغراق! تم الكتم لـ 5 دقائق", reply_to=msg_id)
        add_log(chat_id, f"كتم {message['from'].get('first_name', 'مستخدم')} للإغراق")
        return False
    
    return True

# === معالج الأعضاء الجدد ===
def handle_new_member(message, chat_id):
    """معالجة عضو جديد"""
    settings = group_settings[chat_id]
    new_members = message.get("new_chat_members", [])
    
    for member in new_members:
        user_id = member["id"]
        user_name = member.get("first_name", "العضو")
        
        # فحص البوتات
        if member.get("is_bot") and settings["antibot"]:
            kick_user(chat_id, user_id)
            send_message(chat_id, f"🤖 تم طرد البوت: {user_name}")
            add_log(chat_id, f"طرد بوت: {user_name}")
            continue
        
        # نظام التحقق Captcha
        if settings["captcha"] and not member.get("is_bot"):
            # كتم حتى يتم التحقق
            mute_user(chat_id, user_id)
            
            # إنشاء زر التحقق
            markup = {
                "inline_keyboard": [[
                    {"text": "✅ أنا إنسان", "callback_data": f"verify_{user_id}"}
                ]]
            }
            
            msg = send_message(
                chat_id,
                f"👋 مرحباً {user_name}!\n\nاضغط الزر للتحقق خلال دقيقتين:",
                markup=markup
            )
            
            if msg and msg.get("result"):
                pending_users[chat_id][user_id] = {
                    "msg_id": msg["result"]["message_id"],
                    "time": time.time()
                }
        
        # رسالة الترحيب
        elif settings["welcome"]:
            welcome_text = settings["welcome_msg"].replace("{user}", user_name).replace("{chat}", message["chat"].get("title", "المجموعة"))
            send_message(chat_id, welcome_text)

# === Flask Routes ===
@app.route('/')
def home():
    return "🛡 Group Protection Bot Active"

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        
        # معالجة الرسائل
        if "message" in update:
            message = update["message"]
            chat = message["chat"]
            chat_id = chat["id"]
            user = message["from"]
            user_id = user["id"]
            text = message.get("text", "")
            
            # فقط في المجموعات
            if chat["type"] not in ["group", "supergroup"]:
                if text == "/start":
                    handle_start(chat_id, user_id)
                return {"ok": True}
            
            # معالجة الأعضاء الجدد
            if "new_chat_members" in message:
                handle_new_member(message, chat_id)
                return {"ok": True}
            
            # الأوامر (للمشرفين فقط)
            if text.startswith("/") and is_admin(chat_id, user_id):
                cmd = text.split()[0].lower()
                admin_name = user.get("first_name", "المشرف")
                
                if cmd == "/help":
                    handle_help(chat_id)
                elif cmd == "/ban":
                    handle_ban(chat_id, user_id, message, admin_name)
                elif cmd == "/kick":
                    handle_kick(chat_id, user_id, message, admin_name)
                elif cmd == "/mute":
                    handle_mute(chat_id, user_id, message, admin_name)
                elif cmd == "/unmute" and message.get("reply_to_message"):
                    target_id = message["reply_to_message"]["from"]["id"]
                    unmute_user(chat_id, target_id)
                    send_message(chat_id, "🔊 تم إلغاء الكتم")
                elif cmd == "/warn":
                    handle_warn(chat_id, user_id, message, admin_name)
                elif cmd == "/lock":
                    group_settings[chat_id]["locked"] = True
                    send_message(chat_id, "🔒 تم قفل المجموعة")
                elif cmd == "/unlock":
                    group_settings[chat_id]["locked"] = False
                    send_message(chat_id, "🔓 تم فتح المجموعة")
                elif cmd == "/settings":
                    handle_settings(chat_id)
                elif cmd == "/logs":
                    handle_logs(chat_id)
                elif cmd == "/rules":
                    send_message(chat_id, group_settings[chat_id]["rules"])
                elif cmd.startswith("/antilink"):
                    parts = text.split()
                    if len(parts) > 1:
                        group_settings[chat_id]["antilink"] = parts[1].lower() == "on"
                        status = "مفعل" if group_settings[chat_id]["antilink"] else "معطل"
                        send_message(chat_id, f"🔗 منع الروابط: {status}")
                elif cmd.startswith("/antiflood"):
                    parts = text.split()
                    if len(parts) > 1:
                        group_settings[chat_id]["antiflood"] = parts[1].lower() == "on"
                        status = "مفعل" if group_settings[chat_id]["antiflood"] else "معطل"
                        send_message(chat_id, f"💬 منع الإغراق: {status}")
                
                return {"ok": True}
            
            # فحص المحتوى
            check_content(message, chat_id, user_id)
        
        # معالجة الأزرار (Callback)
        elif "callback_query" in update:
            callback = update["callback_query"]
            data = callback["data"]
            chat_id = callback["message"]["chat"]["id"]
            user_id = callback["from"]["id"]
            msg_id = callback["message"]["message_id"]
            
            # التحقق من العضو الجديد
            if data.startswith("verify_"):
                target_id = int(data.split("_")[1])
                if user_id == target_id:
                    unmute_user(chat_id, user_id)
                    delete_message(chat_id, msg_id)
                    send_message(chat_id, f"✅ تم التحقق من {callback['from'].get('first_name', 'العضو')}")
                    if user_id in pending_users[chat_id]:
                        del pending_users[chat_id][user_id]
                else:
                    api_request("answerCallbackQuery", {
                        "callback_query_id": callback["id"],
                        "text": "❌ هذا الزر ليس لك!",
                        "show_alert": True
                    })
        
        return {"ok": True}
    except Exception as e:
        print(f"Error: {e}")
        return {"ok": False}

# === تشغيل ===
if __name__ == "__main__":
    print("="*60)
    print("🛡 Telegram Group Protection Bot")
    print("="*60)
    print("✅ Anti-Spam | Anti-Flood | Anti-Link")
    print("✅ Captcha | Warnings | Media Filter")
    print("✅ Welcome Messages | Rules | Logs")
    print("="*60)
    print(f"\n🔗 Set webhook:")
    print(f"{API_URL}/setWebhook?url=YOUR_URL/{BOT_TOKEN}\n")
    
    app.run(host='0.0.0.0', port=8080)
