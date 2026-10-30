-- Create the local account and grant access to Registry, audit, and transaction databases.

CREATE DATABASE IF NOT EXISTS registry CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'registry'@'127.0.0.1' IDENTIFIED BY '__DB_PASSWORD__';
GRANT ALL PRIVILEGES ON registry.* TO 'registry'@'127.0.0.1';
GRANT ALL PRIVILEGES ON registryTransaction.* TO 'registry'@'127.0.0.1';
GRANT ALL PRIVILEGES ON registryAudit.* TO 'registry'@'127.0.0.1';
