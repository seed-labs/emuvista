#!/bin/bash
set -euo pipefail

if [ ! -f sites/common_site_config.json ]; then
    echo '{}' > sites/common_site_config.json
fi
ls -1 apps > sites/apps.txt
bench set-config -g db_host "$DB_HOST"
bench set-config -gp db_port 3306
bench set-config -g redis_cache "redis://$REDIS_HOST:6379/0"
bench set-config -g redis_queue "redis://$REDIS_HOST:6379/1"
bench set-config -g redis_socketio "redis://$REDIS_HOST:6379/1"
bench set-config -gp socketio_port 9000
bench set-config -gp server_script_enabled 1

if [ ! -f "sites/$ERP_SITE/site_config.json" ]; then
    bench new-site "$ERP_SITE" --db-root-username root \
        --db-root-password "$ERP_DATABASE_PASSWORD" \
        --admin-password "$ERP_ADMIN_PASSWORD" \
        --mariadb-user-host-login-scope '%' \
        --set-default
fi

bench --site "$ERP_SITE" install-app erpnext
bench --site "$ERP_SITE" install-app hrms
bench --site "$ERP_SITE" set-config host_name "$ERP_PUBLIC_URL"
bench --site "$ERP_SITE" set-config maintenance_mode 0
bench --site "$ERP_SITE" enable-scheduler
env/bin/python /opt/emuvista-erp/initialize.py
