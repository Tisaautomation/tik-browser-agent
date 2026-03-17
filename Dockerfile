FROM python:3.11-slim

WORKDIR /app

# Install base deps for playwright
RUN apt-get update && apt-get install -y     wget curl gnupg ca-certificates     --no-install-recommends && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Let playwright install chromium AND its system deps automatically
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py"]