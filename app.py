#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Bot - Replies 'hi' to everything
"""

from flask import Flask, request
import requests

BOT_TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"

app = Flask(__name__)

def send(chat_id, text):
    """دالة لإرسال رسالة"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=5)
    except:
        pass

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if data and "message" in data:
            chat_id = data["message"]["chat"]["id"]
            # الرد بكلمة hi فقط
            send(chat_id, "hi")
    except:
        pass
    return {"ok": True}

@app.route('/')
def home():
    return "Bot is running!"

if __name__ == "__main__":
    print("Simple Bot started!")
    app.run(host='0.0.0.0', port=8080)
