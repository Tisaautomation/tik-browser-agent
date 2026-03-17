FROM python:3.11-slim

WORKDIR /app

# Install base tools
RUN apt-get update && apt-get install -y     wget curl gnupg ca-certificates     --no-install-recommends

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright install --with-deps needs apt access (do NOT clean apt lists before this)
RUN playwright install --with-deps chromium

# Now clean up
RUN rm -rf /var/lib/apt/lists/*

COPY . .

CMD ["python", "main.py"]