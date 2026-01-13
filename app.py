import os
import requests
from flask import Flask, request, jsonify

# التوكن الخاص بك
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"

app = Flask(__name__)

def set_webhook():
    """دالة لتجهيز الـ Webhook تلقائياً عند تشغيل البوت"""
    try:
        # الحصول على الرابط الخاص بـ Render تلقائياً
        base_url = os.environ.get('RENDER_EXTERNAL_URL')
        if base_url:
            webhook_url = f"{base_url}/{TOKEN}"
            
            # التحقق مما إذا كان الـ Webhook مضبوطاً من قبل لتجنب التكرار
            check_req = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo")
            current_url = check_req.json().get('result', {}).get('url', '')
            
            # إذا كان الرابط مختلفاً، قم بتحديثه
            if current_url != webhook_url:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={"url": webhook_url})
                print(f"✅ Webhook set to: {webhook_url}")
            else:
                print("✅ Webhook is already set correctly.")
        else:
            print("⚠️ RENDER_EXTERNAL_URL not found. Running locally?")
    except Exception as e:
        print(f"Error setting webhook: {e}")

@app.route('/')
def home():
    # هذه الصفحة تستدعى عند الفحص الصحي (Health Check)، سنستغلها لضبط الـ Webhook
    set_webhook()
    return "Bot is running and active!"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    """هذا هو المسار الذي سيرسل منه تيليجرام الرسائل"""
    try:
        data = request.json
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            
            # الرد بكلمة hi
            send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            requests.post(send_url, json={"chat_id": chat_id, "text": "hi"})
            
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"ok": False})

if __name__ == "__main__":
    # تشغيل التطبيق على المنفذ الذي تفرضه البيئة (Render يستخدم 10000 عادة)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
