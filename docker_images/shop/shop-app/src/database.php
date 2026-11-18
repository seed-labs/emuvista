<?php
$settings = json_decode(file_get_contents('/shop-config/config.json'), true, 512, JSON_THROW_ON_ERROR);
$password = $settings['databasePassword'];
mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$last = null;
for ($attempt = 0; $attempt < 120; $attempt++) {
    try {
        $database = new mysqli('localhost', 'root', ($argv[1] ?? '') === 'new' ? '' : $password,
                               '', 0, '/run/mysqld/mysqld.sock');
        break;
    } catch (mysqli_sql_exception $error) {
        $last = $error;
        sleep(1);
    }
}
if (!isset($database)) throw $last;
$secret = $database->real_escape_string($password);
if (($argv[1] ?? '') === 'new') $database->query("ALTER USER 'root'@'localhost' IDENTIFIED BY '$secret'");
$database->query('CREATE DATABASE IF NOT EXISTS shop CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci');
foreach (['localhost', '127.0.0.1'] as $host) {
    $database->query("CREATE USER IF NOT EXISTS 'shop'@'$host' IDENTIFIED BY '$secret'");
    $database->query("ALTER USER 'shop'@'$host' IDENTIFIED BY '$secret'");
    $database->query("GRANT ALL PRIVILEGES ON shop.* TO 'shop'@'$host'");
}
