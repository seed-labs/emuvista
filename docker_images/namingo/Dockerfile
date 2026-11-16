# Application image; scenario configuration is mounted by its Bundle.
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
# Bootstrap CA certificates over signed APT metadata, then use HTTPS.
RUN sed -i -e 's|http://archive.ubuntu.com/ubuntu/\?|http://mirrors.ustc.edu.cn/ubuntu/|g' -e 's|http://security.ubuntu.com/ubuntu/\?|http://mirrors.ustc.edu.cn/ubuntu/|g' -e 's|http://ports.ubuntu.com/ubuntu-ports/\?|http://mirrors.ustc.edu.cn/ubuntu-ports/|g' /etc/apt/sources.list.d/ubuntu.sources && apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=30 update && apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=30 install -y --no-install-recommends ca-certificates && sed -i 's|http://mirrors.ustc.edu.cn/|https://mirrors.ustc.edu.cn/|g' /etc/apt/sources.list.d/ubuntu.sources
RUN apt-get -o Acquire::Retries=0 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=0 -o Acquire::https::Timeout=30 install -y --no-install-recommends bind9-dnsutils ca-certificates cron curl git iproute2 iputils-ping mariadb-client mariadb-server nginx openssl python3 redis-server software-properties-common unzip
RUN mkdir -p /usr/share/keyrings && curl -fLsS --connect-timeout 10 --max-time 60 https://ppa.setup-php.com/keys/ondrej/php.gpg -o /usr/share/keyrings/ondrej-php.gpg && echo '46865863bccffcf614bf1c8603492c6a5465dcc8d774f0020e7518378ba53466  /usr/share/keyrings/ondrej-php.gpg' | sha256sum -c - && . /etc/os-release && printf 'deb [signed-by=/usr/share/keyrings/ondrej-php.gpg] https://ppa.setup-php.com/ondrej/php/ubuntu/ %s main\n' "$VERSION_CODENAME" > /etc/apt/sources.list.d/ondrej-php.list
RUN apt-get -o Acquire::CompressionTypes::Order=xz -o Acquire::Retries=0 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y composer php8.5-cli php8.5-fpm php8.5-mysql php8.5-curl php8.5-bcmath php8.5-gmp php8.5-intl php8.5-mbstring php8.5-xml php8.5-zip php8.5-swoole php8.5-imap php8.5-gd php8.5-bz2 php8.5-soap php8.5-redis
RUN curl --connect-timeout 30 -fsSL https://codeload.github.com/getnamingo/registry/tar.gz/a783a3c37a5614827f7141f07028e9a6a2d4f5cb -o /tmp/registry.tar.gz && echo 'f38b03276ef4e446ab1d4b8d5267b2f6008ca3be06f9193e6d6e2f81c6191a1e  /tmp/registry.tar.gz' | sha256sum -c - && mkdir -p /opt/registry && tar -xzf /tmp/registry.tar.gz -C /opt/registry --strip-components=1 && rm /tmp/registry.tar.gz
RUN cd /opt/registry/cp && COMPOSER_ALLOW_SUPERUSER=1 php8.5 /usr/bin/composer install --no-dev --prefer-dist --no-interaction
RUN cd /opt/registry/epp && COMPOSER_ALLOW_SUPERUSER=1 php8.5 /usr/bin/composer install --no-dev --prefer-dist --no-interaction
RUN cd /opt/registry/das && COMPOSER_ALLOW_SUPERUSER=1 php8.5 /usr/bin/composer install --no-dev --prefer-dist --no-interaction
RUN cd /opt/registry/automation && COMPOSER_ALLOW_SUPERUSER=1 php8.5 /usr/bin/composer install --no-dev --prefer-dist --no-interaction
RUN rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf && rm -rf /var/lib/apt/lists/*
EXPOSE 8080 700
CMD ["sleep", "infinity"]
