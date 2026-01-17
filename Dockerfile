FROM python:3.9-slim

# تحديث النظام وتحميل الأدوات
RUN apt-get update && apt-get install -y wget unzip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# تحميل Xray (النسخة المتوافقة)
RUN wget -q https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip && \
    unzip -q Xray-linux-64.zip && \
    chmod +x xray && \
    rm Xray-linux-64.zip *.dat

# نسخ الملفات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# أمر التشغيل
CMD ["python", "app.py"]
