FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive DISPLAY=:99 AGENT_BROWSER_CONFIG=/run/browser-agent/browser_connection.json
# Install system and desktop dependencies in separate layers.
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y python3 python3-venv iproute2 dnsutils dnsmasq-base ca-certificates curl
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y xvfb x11-utils x11vnc novnc openbox fonts-noto-cjk
RUN python3 -m venv /opt/venv
COPY agent/requirements.txt /opt/agent/requirements.txt
# Source changes do not reinstall dependencies.
RUN /opt/venv/bin/pip install --retries 3 --timeout 30 -r /opt/agent/requirements.txt
RUN /opt/venv/bin/playwright install-deps chromium
RUN /opt/venv/bin/playwright install chromium
COPY agent/ /opt/agent/
COPY start.sh launch_browser.js egress_urls.txt /opt/browser-agent/
WORKDIR /opt/agent
ENTRYPOINT ["bash", "/opt/browser-agent/start.sh"]
