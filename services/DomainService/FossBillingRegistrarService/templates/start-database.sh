#!/bin/sh
# Start MariaDB before creating the installer account.
set -e
mkdir -p /run/mysqld
chown mysql:mysql /run/mysqld
service mariadb start
mariadb < /opt/fossbilling/database.sql
