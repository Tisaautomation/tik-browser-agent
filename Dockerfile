FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    --no-install-recommends

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

RUN rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
