#!/bin/bash
set -eu
mkdir -p /run/mysqld /var/lib/mysql /var/lib/mysql-files /var/www/html
chown mysql:mysql /run/mysqld /var/lib/mysql-files
chown -R mysql:mysql /var/lib/mysql
fresh='saved'
if ! test -d /var/lib/mysql/mysql; then
    mysqld --initialize-insecure --user=mysql --datadir=/var/lib/mysql
    fresh='new'
fi
mysqld --user=mysql --datadir=/var/lib/mysql --bind-address=127.0.0.1 \
    --socket=/run/mysqld/mysqld.sock --pid-file=/run/mysqld/mysqld.pid \
    --log-bin-trust-function-creators=1 --skip-log-bin --mysqlx=OFF &
database_pid=$!
web_pid=''
shutdown() {
    trap - EXIT TERM INT
    if test -n "$web_pid"; then kill "$web_pid" 2>/dev/null || true; fi
    kill "$database_pid" 2>/dev/null || true
    wait "$database_pid" 2>/dev/null || true
}
trap shutdown EXIT
trap 'exit 0' TERM INT
php /opt/emuvista-shop/database.php "$fresh"
if ! test -f /var/www/html/wp-includes/version.php; then
    cp -a /usr/src/wordpress/. /var/www/html/
    chown -R www-data:www-data /var/www/html
fi
mkdir -p /var/www/html/wp-content/mu-plugins
cp /opt/emuvista-shop/loader.php /var/www/html/wp-content/mu-plugins/emuvista.php
cp /opt/emuvista-shop/wp-config.php /var/www/html/wp-config.php
cp /opt/emuvista-shop/htaccess /var/www/html/.htaccess
export WORDPRESS_DB_HOST=127.0.0.1 WORDPRESS_DB_USER=shop WORDPRESS_DB_NAME=shop
export WORDPRESS_DB_PASSWORD="$(php -r 'echo json_decode(file_get_contents("/shop-config/config.json"), true)["databasePassword"];')"
export SHOP_ORIGIN="$(php -r 'echo json_decode(file_get_contents("/shop-config/config.json"), true)["url"];')"
sh /opt/emuvista-shop/initialize.sh
apache2-foreground &
web_pid=$!
wait -n "$database_pid" "$web_pid"
