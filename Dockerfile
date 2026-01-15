# استخدام بايثون كأساس
FROM python:3.9-slim

# تثبيت أدوات التحميل وفك الضغط
RUN apt-get update && apt-get install -y wget unzip && rm -rf /var/lib/apt/lists/*

# إعداد مجلد العمل
WORKDIR /app

# تحميل Xray VPN (محرك VLESS)
RUN wget https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && \
    unzip Xray-linux-64.zip && \
    chmod +x xray && \
    rm Xray-linux-64.zip

# نسخ الملفات وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# تشغيل البوت
CMD ["python", "app.py"]
