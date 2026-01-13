#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import time

# التوكن الخاص بك
TOKEN = "8449140690:AAE6kMOXaKyVdcCi7uQTBHHienL2lWff5Q4"

def send_message(chat_id, text):
    """دالة لإرسال رسالة"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error sending: {e}")

def main():
    print("✅ Bot is running...")
    print("Send any message to the bot now.")
    
    # هذا المتغير يمنع تكرار نفس الرسالة
    offset = 0
    
    while True:
        try:
            # طلب الرسائل الجديدة من تيليجرام
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            params = {"timeout": 30, "offset": offset}
            response = requests.get(url, params=params)
            data = response.json()

            if data["ok"]:
                for result in data["result"]:
                    # تحديث الـ offset لننتقل للرسالة التالية
                    offset = result["update_id"] + 1
                    
                    # التأكد من وجود رسالة نصية
                    if "message" in result:
                        chat_id = result["message"]["chat"]["id"]
                        
                        # طباعة الرسالة في التيرمينال للمتابعة
                        print(f"Received message from: {chat_id}")
                        
                        # الرد بكلمة hi
                        send_message(chat_id, "hi")
                        
        except Exception as e:
            print(f"Error occurred: {e}")
            # الانتظار 5 ثواني في حال وجود خطأ ثم المحاولة مجدداً
            time.sleep(5)

if __name__ == "__main__":
    main()
