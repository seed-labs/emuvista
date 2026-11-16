#!/bin/bash
set -euo pipefail
export PATH=/opt/ruby/bin:/usr/local/bin:$PATH
umask 077
python3 /opt/mastodon-service/configure.py
chown -R mastodon:mastodon /var/lib/mastodon /opt/mastodon/public/system
service postgresql start
service redis-server start
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='mastodon'" | grep -qx 1; then
    runuser -u postgres -- createuser --createdb mastodon
fi
# PostgreSQL uses local peer authentication; no database password is embedded in the image.
runuser -u mastodon -- /opt/mastodon-service/run.sh bundle exec rails db:prepare
if ! grep -q '^VAPID_PRIVATE_KEY=' /var/lib/mastodon/runtime.env; then
    runuser -u mastodon -- /opt/mastodon-service/run.sh bundle exec rails mastodon:webpush:generate_vapid_key > /var/lib/mastodon/vapid.tmp
    grep -E '^VAPID_(PRIVATE|PUBLIC)_KEY=' /var/lib/mastodon/vapid.tmp >> /var/lib/mastodon/runtime.env
    rm /var/lib/mastodon/vapid.tmp
fi
runuser -u mastodon -- /opt/mastodon-service/run.sh bundle exec rails runner /opt/mastodon-service/initialize.rb
if [ "$(cat /opt/mastodon-service/token-exports.json)" != '[]' ]; then
    runuser -u mastodon -- /opt/mastodon-service/run.sh bundle exec rails runner /opt/mastodon-service/export-tokens.rb
fi

if python3 -c 'import json, sys; sys.exit(json.load(open("/opt/mastodon-service/settings.json")).get("scheme") != "http")'; then
    nginx -t
    service nginx start
    supervisord -c /opt/mastodon-service/supervisord.conf
    echo 'Mastodon HTTP services started'
    exit 0
fi

domain=$(python3 -c 'import json; print(json.load(open("/opt/mastodon-service/settings.json"))["domain"])')
acme_url=$(python3 -c 'import json; print(json.load(open("/opt/mastodon-service/settings.json")).get("acme_url") or "")')
if [ -n "$acme_url" ]; then
    # Start HTTP only so the CA can validate mastodon.com through HTTP-01.
    mkdir -p /var/www/acme
    chmod 755 /var/www/acme
    rm -f /etc/nginx/conf.d/mastodon-https.conf
    nginx -t
    service nginx start
    until curl --fail --silent "$acme_url" > /dev/null; do sleep 2; done
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt certbot certonly \
        --webroot -w /var/www/acme --server "$acme_url" \
        --non-interactive --agree-tos --email "admin@$domain" \
        --cert-name "$domain" -d "$domain"
    sed -i 's/^#\? *renew_before_expiry = .*$/renew_before_expiry = 8hours/' /etc/letsencrypt/renewal/*.conf
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    printf '#!/bin/sh\nnginx -t && service nginx reload\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
    chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
    printf 'SHELL=/bin/sh\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n0 * * * * root REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt certbot -q renew\n' > /etc/cron.d/certbot
    chmod 644 /etc/cron.d/certbot
    service cron start
else
    tls=/var/lib/mastodon/tls
    mkdir -p "$tls"
    chown root:root "$tls"
    chmod 700 "$tls"
    if [ ! -s "$tls/cert.pem" ] || [ ! -s "$tls/key.pem" ] \
        || ! openssl verify -no_check_time -CAfile "$tls/cert.pem" -verify_hostname "$domain" "$tls/cert.pem" >/dev/null 2>&1 \
        || ! openssl verify -no_check_time -CAfile "$tls/cert.pem" -verify_hostname localhost "$tls/cert.pem" >/dev/null 2>&1; then
        openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
            -keyout "$tls/key.pem" -out "$tls/cert.pem" \
            -subj "/CN=$domain" -addext "subjectAltName=DNS:$domain,DNS:localhost"
    fi
    chmod 600 "$tls/key.pem"
fi
cp /opt/mastodon-service/mastodon-https.conf /etc/nginx/conf.d/mastodon-https.conf
nginx -t
if [ -n "$acme_url" ]; then service nginx reload; else service nginx start; fi
supervisord -c /opt/mastodon-service/supervisord.conf
echo 'Mastodon services started'
