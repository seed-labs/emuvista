FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
# Install networking and Python dependencies.
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y python3 python3-venv iproute2 dnsutils dnsmasq-base ca-certificates curl
RUN python3 -m venv /opt/venv
COPY agent/requirements.txt /opt/agent/requirements.txt
# Source changes do not reinstall dependencies.
RUN /opt/venv/bin/pip install --retries 3 --timeout 30 -r /opt/agent/requirements.txt
COPY agent/ /opt/agent/
COPY packages/ /opt/agent/packages/
COPY tool-config.json /opt/agent/tool-config.json
COPY start.sh egress_urls.txt /opt/domain-agent/
WORKDIR /opt/agent
ENTRYPOINT ["bash", "/opt/domain-agent/start.sh"]
