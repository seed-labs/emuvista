"""Runtime and web-server templates for CloudDriveService."""

POSTGRES_START_TEMPLATE = r'''#!/bin/sh
set -eu

PG_VERSION=$(find /etc/postgresql -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -n 1)
PG_CONFIG=/etc/postgresql/$PG_VERSION/main/postgresql.conf
PG_HBA=/etc/postgresql/$PG_VERSION/main/pg_hba.conf
PG_DATA=/var/lib/postgresql/$PG_VERSION/main

# An empty host bind hides the cluster created by the Ubuntu package at image
# build time. Initialise it once; a loaded state already contains PG_VERSION.
chown postgres:postgres /var/lib/postgresql
chmod 0700 /var/lib/postgresql
if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    install -d -o postgres -g postgres "$PG_DATA"
    runuser -u postgres -- "/usr/lib/postgresql/$PG_VERSION/bin/initdb" \
        -D "$PG_DATA" --auth-local=peer --auth-host=scram-sha-256
fi

sed -ri "s/^#?listen_addresses\s*=.*/listen_addresses = '{listen_addresses}' /" "$PG_CONFIG"
if ! grep -q "{marker}" "$PG_HBA"; then
    cat >> "$PG_HBA" <<'EOF'
# {marker}
{access_rules}
EOF
fi

{network_isolation_commands}

pg_ctlcluster "$PG_VERSION" main start

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '{db_user}'" | grep -q 1; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE {db_user} LOGIN PASSWORD '{db_password}'"
fi

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = '{db_name}'" | grep -q 1; then
    runuser -u postgres -- createdb -O {db_user} {db_name}
fi
'''


OBJECT_STORAGE_START_TEMPLATE = r'''#!/bin/sh
set -eu
mkdir -p {data_directory}
export SEEDVISTA_S3_ACCESS_KEY={access_key}
export SEEDVISTA_S3_SECRET_KEY={secret_key}
{network_isolation_commands}
exec env NODE_OPTIONS=--require=/opt/seedvista/cloud-drive/s3-credentials.js \
    /usr/local/bin/s3rver \
    --address {listen_address} \
    --port {port} \
    --directory {data_directory} \
    --configure-bucket {bucket} \
    --silent
'''


OBJECT_STORAGE_CREDENTIALS_TEMPLATE = r'''const { DUMMY_ACCOUNT } = require(
  "/usr/local/lib/node_modules/s3rver/lib/models/account"
);

DUMMY_ACCOUNT.createKeyPair(
  process.env.SEEDVISTA_S3_ACCESS_KEY,
  process.env.SEEDVISTA_S3_SECRET_KEY
);
'''


APACHE_SITE_TEMPLATE = r'''<VirtualHost *:{port}>
    ServerName {primary_server_name}
    ServerAlias {server_aliases}
    DocumentRoot /var/www/html

    <Directory /var/www/html>
        Require all granted
        AllowOverride All
        Options FollowSymLinks MultiViews
    </Directory>

    ErrorLog ${{APACHE_LOG_DIR}}/nextcloud-error.log
    CustomLog ${{APACHE_LOG_DIR}}/nextcloud-access.log combined
</VirtualHost>
'''


NGINX_PROXY_TEMPLATE = r'''server {{
    listen 80;
    server_name {server_names};
    client_max_body_size 0;

    location / {{
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:{apache_port};
    }}
}}
'''


NEXTCLOUD_INIT_TEMPLATE = r'''#!/bin/sh
set -eu

for attempt in $(seq 1 90); do
    if PGPASSWORD={db_password_q} psql -h {db_host_q} -p {db_port} \
        -U {db_user_q} -d {db_name_q} -tAc 'SELECT 1' >/dev/null 2>&1 \
        && nc -z {object_host_q} {object_port} >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

PGPASSWORD={db_password_q} psql -h {db_host_q} -p {db_port} \
    -U {db_user_q} -d {db_name_q} -tAc 'SELECT 1'
nc -z {object_host_q} {object_port}

cd /var/www/html/lib

if ! php /var/www/html/occ status 2>/dev/null | grep -q 'installed: true'; then
    php /var/www/html/occ maintenance:install \
        --database pgsql \
        --database-host {db_host_q} \
        --database-name {db_name_q} \
        --database-user {db_user_q} \
        --database-pass {db_password_q} \
        --admin-user {admin_user_q} \
        --admin-pass {admin_password_q}
fi

php /var/www/html/occ config:system:delete trusted_domains >/dev/null 2>&1 || true
{trusted_domain_commands}
php /var/www/html/occ config:system:set objectstore class --value='\OC\Files\ObjectStore\S3'
php /var/www/html/occ config:system:set objectstore arguments bucket --value={bucket_q}
php /var/www/html/occ config:system:set objectstore arguments hostname --value={object_host_q}
php /var/www/html/occ config:system:set objectstore arguments port --type=integer --value={object_port}
php /var/www/html/occ config:system:set objectstore arguments key --value={access_key_q} >/dev/null
php /var/www/html/occ config:system:set objectstore arguments secret --value={secret_key_q} >/dev/null
php /var/www/html/occ config:system:set objectstore arguments region --value={region_q}
php /var/www/html/occ config:system:set objectstore arguments use_path_style --type=boolean --value={path_style}
php /var/www/html/occ config:system:set objectstore arguments use_ssl --type=boolean --value={object_ssl}
php /var/www/html/occ config:system:set objectstore arguments autocreate --type=boolean --value=true
{https_commands}

chown -R www-data:www-data /var/www/html/config /var/www/html/data
'''
