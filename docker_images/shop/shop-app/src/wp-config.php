<?php
$settings = json_decode(file_get_contents('/shop-config/config.json'), true, 512, JSON_THROW_ON_ERROR);
define('DB_NAME', 'shop');
define('DB_USER', 'shop');
define('DB_PASSWORD', $settings['databasePassword']);
define('DB_HOST', '127.0.0.1');
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');
$table_prefix = 'wp_';
foreach (['AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY', 'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT'] as $key) {
    define($key, hash_hmac('sha256', $key, $settings['wordpressKey']));
}
$origin = $settings['url'];
$browser = 'http://' . ($_SERVER['HTTP_HOST'] ?? '');
if (in_array($browser, $settings['browserOrigins'], true)) $origin = $browser;
define('WP_HOME', $origin);
define('WP_SITEURL', $origin);
define('DISABLE_WP_CRON', true);
define('WP_ENVIRONMENT_TYPE', 'local');
if (!defined('ABSPATH')) define('ABSPATH', __DIR__ . '/');
require_once ABSPATH . 'wp-settings.php';
