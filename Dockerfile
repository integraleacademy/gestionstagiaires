FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    fontconfig \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-core \
    fonts-noto-cjk \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-10000}"]
