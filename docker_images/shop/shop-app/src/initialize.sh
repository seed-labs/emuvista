#!/bin/sh
set -eu
cd /var/www/html
until test -f wp-config.php; do sleep 1; done
wp() { php -d memory_limit=512M /usr/local/bin/wp --allow-root "$@"; }
until php -r 'mysqli_report(MYSQLI_REPORT_OFF); $db = @new mysqli(getenv("WORDPRESS_DB_HOST"), getenv("WORDPRESS_DB_USER"), getenv("WORDPRESS_DB_PASSWORD"), getenv("WORDPRESS_DB_NAME")); exit($db->connect_errno ? 1 : 0);'; do sleep 2; done
if ! wp core is-installed; then
    wp core install --url="$SHOP_ORIGIN" --title='Town Marketplace' \
        --admin_user=admin --admin_email=admin@shop.com --admin_password='ShopAdminDemo123!' --skip-email
fi
if ! wp option get emuvista_initialized >/dev/null 2>&1; then
    wp eval-file /opt/emuvista-shop/wait-mail.php
    wp plugin activate woocommerce
    wp plugin activate dc-woocommerce-multi-vendor
    wp option get multivendorx_version >/dev/null
    wp theme activate storefront
    wp eval-file /opt/emuvista-shop/initialize.php
    wp rewrite structure '/%postname%/'
    cp /opt/emuvista-shop/htaccess .htaccess
    chown -R www-data:www-data wp-content
fi
