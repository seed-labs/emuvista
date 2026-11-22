FROM handsonsecurity/seedemu-base:2.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends apache2 libapache2-mod-auth-openidc \
    && rm -rf /var/lib/apt/lists/* \
    && a2enmod auth_openidc proxy proxy_http headers

CMD ["apachectl", "-D", "FOREGROUND"]
