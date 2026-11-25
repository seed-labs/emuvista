FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/stock
COPY requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential swig libssl-dev libxml2-dev libpcre3-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential swig libssl-dev libxml2-dev libpcre3-dev \
    && rm -rf /var/lib/apt/lists/*
COPY stock_service ./stock_service

EXPOSE 8080
CMD ["uvicorn", "stock_service.api:app", "--host", "0.0.0.0", "--port", "8080"]
