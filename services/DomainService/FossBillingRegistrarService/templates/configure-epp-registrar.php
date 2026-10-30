<?php
// Application initialization operation.
require '/var/www/fossbilling/vendor/autoload.php';
$settings = require '/var/www/fossbilling/config.php';
$db = $settings['db'];
$pdo = new PDO(
    'mysql:host=' . $db['host'] . ';port=' . $db['port'] . ';dbname=' . $db['name'] . ';charset=utf8mb4',
    $db['user'], $db['password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
);
$connection = CONNECTION_PLACEHOLDER;
$config = array_merge([
    'verify_peer' => '0',
    'cafile' => '',
    'passphrase' => '',
    'contact_postal_type' => 'int',
    'registry_profile' => 'generic',
    'ns_mode' => 'hostObj',
    'set_authinfo_on_info' => '0',
    'login_objects' => '',
    'login_extensions' => '',
    'debug_log' => '0',
], $connection);
$pdo->beginTransaction();
$find = $pdo->prepare("SELECT id FROM tld_registrar WHERE registrar = 'Namingo'");
$find->execute();
$registrarId = $find->fetchColumn();
if ($registrarId) {
    $update = $pdo->prepare('UPDATE tld_registrar SET name = ?, config = ? WHERE id = ?');
    $update->execute(['Namingo EPP', json_encode($config), $registrarId]);
} else {
    $insert = $pdo->prepare('INSERT INTO tld_registrar (name, registrar, config) VALUES (?, ?, ?)');
    $insert->execute(['Namingo EPP', 'Namingo', json_encode($config)]);
    $registrarId = $pdo->lastInsertId();
}
$prices = TLD_PRICES_PLACEHOLDER;
$find = $pdo->prepare('SELECT id FROM tld WHERE tld IN (?, ?) LIMIT 1');
$update = $pdo->prepare('UPDATE tld SET tld_registrar_id = ?, updated_at = NOW() WHERE id = ?');
$insert = $pdo->prepare('INSERT INTO tld
    (tld, tld_registrar_id, price_registration, price_renew, price_transfer,
     allow_register, allow_transfer, active, min_years, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, 1, 0, 1, 1, NOW(), NOW())');
foreach ($prices as $tld => $price) {
    $find->execute([$tld, ltrim($tld, '.')]);
    $tldId = $find->fetchColumn();
    if ($tldId) {
        $update->execute([$registrarId, $tldId]);
    } else {
        $insert->execute([$tld, $registrarId, ...$price]);
    }
}
$pdo->commit();
echo "Namingo EPP configured on port ", $connection['port'], " for configured TLDs\n";
