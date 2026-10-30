#!/bin/bash
# Start the database; import and initialize only when the registrar table is absent.

mkdir -p /run/mysqld /var/lib/namingo /var/log/namingo
chown mysql:mysql /run/mysqld
chown www-data:www-data /var/log/namingo
service mariadb start
mariadb < /opt/registry/init-database.sql
if [ "$(mariadb -N -B -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='registry' AND table_name='registrar'")" = "0" ]; then
    mariadb < /opt/registry/database/registry.mariadb.sql
    php8.5 /opt/registry/init-tlds.php
fi
