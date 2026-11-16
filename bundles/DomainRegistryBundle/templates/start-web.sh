#!/bin/bash
# Generate panel settings, restrict credential file permissions, then start PHP and Nginx.

php8.5 /opt/registry/configure-control-panel.php
chown root:www-data /opt/registry/cp/.env
chmod 640 /opt/registry/cp/.env
mkdir -p /run/php
service php8.5-fpm start
service nginx start
