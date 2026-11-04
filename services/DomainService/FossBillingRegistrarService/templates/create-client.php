<?php
// Application initialization operation.
require '/var/www/fossbilling/vendor/autoload.php';
$settings = require '/var/www/fossbilling/config.php';
$db = $settings['db'];
$pdo = new PDO(
    'mysql:host=' . $db['host'] . ';port=' . $db['port'] . ';dbname=' . $db['name'] . ';charset=utf8mb4',
    $db['user'], $db['password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
);
$email = EMAIL_PLACEHOLDER;
$password = PASSWORD_PLACEHOLDER;
$profile = PROFILE_PLACEHOLDER;
$stmt = $pdo->prepare('SELECT id, pass FROM client WHERE email = ?');
$stmt->execute([$email]);
$row = $stmt->fetch(PDO::FETCH_ASSOC);
if ($row) {
    if (!password_verify($password, $row['pass'])) {
        fwrite(STDERR, "Existing demo account has a different password; refusing to change it.\n");
        exit(2);
    }
    $clientId = (int) $row['id'];
    $action = 'existing';
} else {
    $hash = (new FOSSBilling\PasswordManager())->hashIt($password);
    $stmt = $pdo->prepare("INSERT INTO client
        (role, email, pass, status, email_approved, first_name, last_name, created_at, updated_at)
        VALUES ('client', ?, ?, 'active', 1, 'Demo', 'Buyer', NOW(), NOW())");
    $stmt->execute([$email, $hash]);
    $clientId = (int) $pdo->lastInsertId();
    $action = 'created';
}
$updates = [];
$values = [];
foreach ($profile as $column => $value) {
    $updates[] = "$column = CASE WHEN $column IS NULL OR TRIM($column) = '' THEN ? ELSE $column END";
    $values[] = $value;
}
$values[] = $clientId;
$pdo->prepare('UPDATE client SET ' . implode(', ', $updates) . ' WHERE id = ?')->execute($values);
echo $action, " client #", $clientId, "; EPP contact profile ready\n";
