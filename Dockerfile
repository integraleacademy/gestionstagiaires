FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /opt/render/project/src

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    fontconfig \
    fonts-dejavu \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-liberation \
    fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY fontconfig/99-msoffice-substitutions.conf /etc/fonts/conf.d/99-msoffice-substitutions.conf
RUN fc-cache -f && fc-match -f '%{family}\n' Calibri | head -n 1 | grep -q Carlito

RUN which libreoffice || true
RUN which soffice || true
RUN libreoffice --version || soffice --version || true

EXPOSE 10000

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
