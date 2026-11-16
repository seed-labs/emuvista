<?php
/** Create the FOSSBilling EPP registrar account. */
declare(strict_types=1);

$db = new PDO(
    'mysql:host=127.0.0.1;dbname=registry;charset=utf8mb4',
    'registry',
    '__REGISTRY_DB_PASSWORD__',
    [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
);

$clid = '__EPP_USERNAME__';
$prefix = '__EPP_PREFIX__';
$db->beginTransaction();
$query = $db->prepare('SELECT id, prefix, pw FROM registrar WHERE clid = ?');
$query->execute([$clid]);
$existing = $query->fetch(PDO::FETCH_ASSOC);
if ($existing) {
    if ($existing['prefix'] !== $prefix) {
        throw new RuntimeException('Existing FOSSBilling EPP prefix differs from scenario config');
    }
    if (!password_verify('__EPP_PASSWORD__', $existing['pw'])) {
        throw new RuntimeException('Existing EPP password differs; refusing to overwrite it');
    }
    $registrarId = (int) $existing['id'];
} else {
    $options = ['memory_cost' => 64 * 1024, 'time_cost' => 3, 'threads' => 1];
    $hash = password_hash('__EPP_PASSWORD__', PASSWORD_ARGON2ID, $options);
    $insert = $db->prepare('INSERT INTO registrar '
        . '(name, clid, pw, prefix, email, whois_server, rdap_server, url, '
        . 'abuse_email, abuse_phone, accountBalance, creditLimit, creditThreshold, '
        . 'thresholdType, currency, companyNumber, crdate) '
        . "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 10000, 10000, 10000, 'fixed', 'EUR', ?, NOW(3))");
    $insert->execute([
        'FOSSBilling Registrar', $clid, $hash, $prefix,
        'fossbilling.registrar@example.net', '__EPP_SOURCE_IP__',
        'http://__EPP_SOURCE_IP__:8080/rdap', 'http://__EPP_SOURCE_IP__:8080',
        'fossbilling-abuse@example.net', '+1.2025550123', 'FOSSBILLING0001',
    ]);
    $registrarId = (int) $db->lastInsertId();

    $contact = $db->prepare('INSERT INTO registrar_contact '
        . '(registrar_id, type, first_name, last_name, city, cc, email) '
        . 'VALUES (?, ?, ?, ?, ?, ?, ?)');
    foreach (['owner', 'billing', 'tech', 'abuse'] as $type) {
        $contact->execute([
            $registrarId, $type, 'FOSSBilling', 'Demo', 'Example City', 'us',
            'fossbilling.registrar@example.net',
        ]);
    }
}

$allow = $db->prepare('INSERT IGNORE INTO registrar_whitelist (registrar_id, addr) VALUES (?, ?)');
$allow->execute([$registrarId, '__EPP_SOURCE_IP__']);
// Reserve domains against configured TLDs and refuse to overwrite another registrar's ownership.
$findDomain = $db->prepare('SELECT clid FROM domain WHERE name = ?');
$findTld = $db->prepare('SELECT id FROM domain_tld WHERE tld IN (?, ?)');
$addDomain = $db->prepare("INSERT INTO domain (name, tldid, crdate, exdate, clid, crid) VALUES (?, ?, NOW(3), '2099-12-31 23:59:59', ?, ?)");
foreach (json_decode('__RESERVED_DOMAINS__', true, 512, JSON_THROW_ON_ERROR) as $name) {
    $suffix = substr($name, strrpos($name, '.') + 1);
    $findTld->execute(['.' . $suffix, $suffix]);
    $tld = $findTld->fetchColumn();
    if ($tld === false) { throw new RuntimeException('Reserved domain TLD is not initialized'); }
    $findDomain->execute([$name]);
    $owner = $findDomain->fetchColumn();
    if ($owner !== false && (int)$owner !== $registrarId) {
        throw new RuntimeException('Reserved domain belongs to another registrar');
    }
    if ($owner === false) { $addDomain->execute([$name, $tld, $registrarId, $registrarId]); }
}
$db->commit();
