FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# IMPORTANTE: copiar TODA la carpeta requirements/, no solo local.txt
# local.txt hace "-r base.txt" → si base.txt no está, el build falla
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/local.txt

COPY . .

EXPOSE 8000
