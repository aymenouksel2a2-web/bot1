#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot - Empty Template
"""

from flask import Flask, request
import requests

BOT_TOKEN = "8211273419:AAG62k2EXmwGYLpQ1DkpnZfFxNC58O8-Sk4"

app = Flask(__name__)

# === Flask Routes ===
@app.route('/')
def home():
    return "✅ Bot Running"

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    try:
        d = request.get_json()
        if not d:
            return {"ok": True}
        
        # فارغ - بدون وظيفة
        
        return {"ok": True}
    except:
        return {"ok": False}

# === تشغيل ===
if __name__ == "__main__":
    print("="*50)
    print("🤖 Bot Started")
    print("="*50)
    print(f"\n🔗 Set webhook:")
    print(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=YOUR_URL/{BOT_TOKEN}\n")
    
    app.run(host='0.0.0.0', port=8080)
