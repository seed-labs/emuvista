<?php
/** Seed customers and active services without performing checkout, payment or EPP registration. */
declare(strict_types=1);
require '/var/www/fossbilling/vendor/autoload.php';
$settings = require '/var/www/fossbilling/config.php';
$config = $settings['db'];
$db = new PDO('mysql:host=' . $config['host'] . ';port=' . $config['port'] . ';dbname=' . $config['name'] . ';charset=utf8mb4',
    $config['user'], $config['password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$records = json_decode(file_get_contents('/opt/fossbilling/import-domains.json'), true, 512, JSON_THROW_ON_ERROR);
function row(PDO $db, string $sql, array $args): array|false {
    $q = $db->prepare($sql); $q->execute($args); return $q->fetch(PDO::FETCH_ASSOC);
}
function insert(PDO $db, string $table, array $data): int {
    $columns = implode(',', array_map(fn($key) => '`' . $key . '`', array_keys($data)));
    $q = $db->prepare("INSERT INTO `$table` ($columns) VALUES (" . implode(',', array_fill(0, count($data), '?')) . ')');
    $q->execute(array_values($data)); return (int)$db->lastInsertId();
}
function profile(array $c): array {
    $names = explode(' ', $c['name'], 2);
    $phone = explode('.', ltrim($c['phone'], '+'), 2);
    $a = $c['address'];
    return ['first_name' => $names[0], 'last_name' => $names[1] ?? '', 'email' => $c['email'],
        'company' => $c['organization'] ?? '', 'address1' => $a['street'][0],
        'address2' => implode(', ', array_slice($a['street'], 1)), 'city' => $a['city'],
        'state' => $a['province'] ?? '', 'postcode' => $a['postal_code'] ?? '',
        'country' => $a['country_code'], 'phone_cc' => $phone[0], 'phone' => $phone[1] ?? ''];
}
$db->exec('CREATE TABLE IF NOT EXISTS seedemu_domain_import (name VARCHAR(253) PRIMARY KEY, digest CHAR(64) NOT NULL)');
$db->beginTransaction();
try {
    foreach ($records as $d) {
        $digest = hash('sha256', json_encode($d, JSON_THROW_ON_ERROR));
        $done = row($db, 'SELECT digest FROM seedemu_domain_import WHERE name = ?', [$d['name']]);
        if ($done) {
            if ($done['digest'] !== $digest) { throw new RuntimeException('Changed import for ' . $d['name']); }
            continue;
        }
        [$sld, $suffix] = explode('.', $d['name'], 2);
        if (row($db, 'SELECT id FROM service_domain WHERE sld = ? AND tld IN (?, ?)', [$sld, $suffix, '.' . $suffix])) {
            throw new RuntimeException('Domain service already exists: ' . $d['name']);
        }
        $tld = row($db, 'SELECT tld_registrar_id, price_renew FROM tld WHERE tld IN (?, ?)', [$suffix, '.' . $suffix]);
        if (!$tld) { throw new RuntimeException('Registrar does not offer ' . $suffix); }
        $client = $d['client'];
        $existing = row($db, 'SELECT id, pass FROM client WHERE email = ?', [$client['email']]);
        if ($existing) {
            if (!password_verify($client['password'], $existing['pass'])) {
                throw new RuntimeException('Existing client password differs: ' . $client['email']);
            }
            $clientId = (int)$existing['id'];
        } else {
            $fields = profile($client['contact']);
            $fields['address_1'] = $fields['address1']; $fields['address_2'] = $fields['address2'];
            unset($fields['address1'], $fields['address2']);
            $fields['email'] = $client['email'];
            $clientId = insert($db, 'client', array_merge($fields, ['role' => 'client',
                'pass' => (new FOSSBilling\PasswordManager())->hashIt($client['password']),
                'status' => 'active', 'email_approved' => 1,
                'created_at' => $d['created_at'], 'updated_at' => $d['created_at']]));
        }
        $fields = ['client_id' => $clientId, 'tld_registrar_id' => $tld['tld_registrar_id'],
            'sld' => $sld, 'tld' => '.' . $suffix, 'period' => 1, 'privacy' => 0, 'locked' => 0,
            'action' => 'register', 'registered_at' => $d['created_at'], 'expires_at' => $d['expires_at'],
            'created_at' => $d['created_at'], 'updated_at' => $d['created_at']];
        foreach (profile($d['contact']) as $key => $value) { $fields['contact_' . $key] = $value; }
        foreach (array_keys($d['nameservers']) as $i => $ns) { $fields['ns' . ($i + 1)] = $ns; }
        $serviceId = insert($db, 'service_domain', $fields);
        $product = row($db, "SELECT id FROM product WHERE type = 'domain' ORDER BY id LIMIT 1", []);
        if (!$product) { throw new RuntimeException('Domain product is not initialized'); }
        $currency = row($db, 'SELECT code FROM currency WHERE is_default = 1', []);
        if (!$currency) { throw new RuntimeException('Default currency is not initialized'); }
        // auto_renew is retained as an import preference; it does not authorize payment.
        insert($db, 'client_order', ['client_id' => $clientId, 'product_id' => $product['id'],
            'title' => $d['name'], 'service_id' => $serviceId, 'service_type' => 'domain',
            'status' => $d['status'], 'period' => '1Y', 'quantity' => 1, 'price' => $tld['price_renew'],
            'currency' => $currency['code'],
            'invoice_option' => 'no-invoice', 'config' => json_encode(['action' => 'register',
                'register_sld' => $sld, 'register_tld' => '.' . $suffix, 'register_years' => 1,
                'auto_renew' => $d['auto_renew']], JSON_THROW_ON_ERROR),
            'activated_at' => $d['created_at'], 'expires_at' => $d['expires_at'],
            'created_at' => $d['created_at'], 'updated_at' => $d['created_at']]);
        insert($db, 'seedemu_domain_import', ['name' => $d['name'], 'digest' => $digest]);
    }
    $db->commit();
    echo 'Registrar customer and domain import complete', PHP_EOL;
} catch (Throwable $error) {
    if ($db->inTransaction()) { $db->rollBack(); }
    throw $error;
}
