# Application image; scenario configuration is mounted by its Bundle.
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
# Bootstrap CA certificates over signed APT metadata, then use HTTPS.
RUN sed -i -e 's|http://archive.ubuntu.com/ubuntu/\?|http://mirrors.ustc.edu.cn/ubuntu/|g' -e 's|http://security.ubuntu.com/ubuntu/\?|http://mirrors.ustc.edu.cn/ubuntu/|g' -e 's|http://ports.ubuntu.com/ubuntu-ports/\?|http://mirrors.ustc.edu.cn/ubuntu-ports/|g' /etc/apt/sources.list.d/ubuntu.sources && apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=30 update && apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=30 install -y --no-install-recommends ca-certificates && sed -i 's|http://mirrors.ustc.edu.cn/|https://mirrors.ustc.edu.cn/|g' /etc/apt/sources.list.d/ubuntu.sources
RUN apt-get -o Acquire::Retries=0 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=0 -o Acquire::https::Timeout=30 install -y --no-install-recommends ca-certificates curl git build-essential pkg-config libssl-dev libyaml-dev libreadline-dev zlib1g-dev libgmp-dev libgdbm-dev libffi-dev libicu-dev libidn-dev libpq-dev libvips-dev ffmpeg imagemagick postgresql postgresql-contrib redis-server nginx openssl supervisor python3 xz-utils iproute2 iputils-ping
COPY install.sh run.sh /opt/mastodon-service/
RUN apt-get -o Acquire::Retries=0 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=0 -o Acquire::https::Timeout=30 install -y --no-install-recommends certbot cron
RUN bash /opt/mastodon-service/install.sh
COPY enable-http.py /opt/mastodon-service/enable-http.py
RUN python3 /opt/mastodon-service/enable-http.py && rm -rf /var/lib/apt/lists/*
EXPOSE 18084
CMD ["sleep", "infinity"]
