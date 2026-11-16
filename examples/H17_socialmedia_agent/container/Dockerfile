FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends dnsmasq-base ca-certificates iputils-ping && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/agent
COPY agent/requirements.txt ./requirements.txt
RUN python -m pip install --retries 3 --timeout 30 -r requirements.txt
COPY agent/ ./
COPY start.sh /opt/start.sh
COPY h14-root-ca.crt /usr/local/share/ca-certificates/h14-root-ca.crt
RUN chmod 644 /usr/local/share/ca-certificates/h14-root-ca.crt && update-ca-certificates
EXPOSE 8089
ENTRYPOINT ["bash", "/opt/start.sh"]
