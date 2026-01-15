FROM python:3.9-slim

# تحميل الأدوات الضرورية
RUN apt-get update && apt-get install -y wget unzip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# تحميل Xray (السطر المسؤول عن جلب الـ VPN)
RUN wget https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip && \
    unzip Xray-linux-64.zip && \
    chmod +x xray && \
    rm Xray-linux-64.zip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
