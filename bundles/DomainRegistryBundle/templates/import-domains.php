<?php
/** Initialize domain records against the pinned Namingo Registry schema. */
declare(strict_types=1);
$config = require '/opt/registry/epp/config.php';
$db = new PDO('mysql:host=127.0.0.1;dbname=registry;charset=utf8mb4',
    'registry', $config['db_password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$records = json_decode(file_get_contents('/opt/registry/import-domains.json'), true, 512, JSON_THROW_ON_ERROR);
function row(PDO $db, string $sql, array $args): array|false {
    $q = $db->prepare($sql); $q->execute($args); return $q->fetch(PDO::FETCH_ASSOC);
}
function insert(PDO $db, string $table, array $data): int {
    $columns = implode(',', array_map(fn($key) => '`' . $key . '`', array_keys($data)));
    $q = $db->prepare("INSERT INTO `$table` ($columns) VALUES (" . implode(',', array_fill(0, count($data), '?')) . ')');
    $q->execute(array_values($data)); return (int)$db->lastInsertId();
}
// The ledger prevents re-seeding records changed by users after initial import.
$db->exec('CREATE TABLE IF NOT EXISTS seedemu_domain_import (name VARCHAR(253) PRIMARY KEY, digest CHAR(64) NOT NULL)');
$db->beginTransaction();
try {
    $pending = [];
    foreach ($records as $d) {
        $digest = hash('sha256', json_encode($d, JSON_THROW_ON_ERROR));
        $done = row($db, 'SELECT digest FROM seedemu_domain_import WHERE name = ?', [$d['name']]);
        if ($done) {
            if ($done['digest'] !== $digest) { throw new RuntimeException('Changed import for ' . $d['name']); }
            continue;
        }
        if (row($db, 'SELECT id FROM domain WHERE name = ?', [$d['name']])) {
            throw new RuntimeException('Domain already exists: ' . $d['name']);
        }
        $registrar = row($db, 'SELECT id FROM registrar WHERE clid = ?', [$d['registrar']]);
        if (!$registrar) { throw new RuntimeException('Missing EPP registrar: ' . $d['registrar']); }
        $owner = (int)$registrar['id'];
        $suffix = substr($d['name'], strrpos($d['name'], '.') + 1);
        $tld = row($db, 'SELECT id FROM domain_tld WHERE tld IN (?, ?)', [$suffix, '.' . $suffix]);
        if (!$tld) { throw new RuntimeException('Missing TLD: ' . $suffix); }
        $c = $d['contact']; $a = $c['address'];
        $identifier = 'import-' . substr(hash('sha256', $d['registrar'] . '/' . $d['registrant']), 0, 32);
        $contact = row($db, 'SELECT id, clid FROM contact WHERE identifier = ?', [$identifier]);
        if ($contact) {
            if ((int)$contact['clid'] !== $owner) { throw new RuntimeException('Contact ownership conflict'); }
            $contactId = (int)$contact['id'];
        } else {
            $contactId = insert($db, 'contact', ['identifier' => $identifier, 'voice' => $c['phone'],
                'email' => $c['email'], 'clid' => $owner, 'crid' => $owner, 'crdate' => $d['created_at']]);
            insert($db, 'contact_postalInfo', ['contact_id' => $contactId, 'type' => 'int',
                'name' => $c['name'], 'org' => $c['organization'] ?? null,
                'street1' => $a['street'][0], 'street2' => $a['street'][1] ?? null,
                'street3' => $a['street'][2] ?? null, 'city' => $a['city'],
                'sp' => $a['province'] ?? null, 'pc' => $a['postal_code'] ?? null, 'cc' => $a['country_code']]);
            insert($db, 'contact_authInfo', ['contact_id' => $contactId, 'authinfo' => bin2hex(random_bytes(12))]);
            insert($db, 'contact_status', ['contact_id' => $contactId, 'status' => 'linked']);
        }
        $id = insert($db, 'domain', ['name' => $d['name'], 'tldid' => $tld['id'], 'registrant' => $contactId,
            'crdate' => $d['created_at'], 'exdate' => $d['expires_at'], 'clid' => $owner, 'crid' => $owner]);
        insert($db, 'domain_authInfo', ['domain_id' => $id, 'authinfo' => bin2hex(random_bytes(12))]);
        foreach ($d['statuses'] as $status) { insert($db, 'domain_status', ['domain_id' => $id, 'status' => $status]); }
        $pending[] = [$d, $id, $owner, $digest];
    }
    // All domains exist before in-domain host objects are resolved.
    foreach ($pending as [$d, $id, $owner, $digest]) {
        foreach ($d['nameservers'] as $name => $address) {
            $host = row($db, 'SELECT id FROM host WHERE name = ?', [$name]);
            if ($host) {
                $hostId = (int)$host['id'];
                if (!row($db, "SELECT id FROM host_addr WHERE host_id = ? AND addr = ? AND ip = 'v4'", [$hostId, $address])) {
                    throw new RuntimeException('Nameserver address conflict: ' . $name);
                }
            } else {
                $parent = row($db, 'SELECT id, clid FROM domain WHERE ? LIKE CONCAT("%.", name) ORDER BY LENGTH(name) DESC LIMIT 1', [$name]);
                $suffix = substr($name, strrpos($name, '.') + 1);
                if (!$parent && row($db, 'SELECT id FROM domain_tld WHERE tld IN (?, ?)', [$suffix, '.' . $suffix])) {
                    throw new RuntimeException('Nameserver parent domain must be registered first: ' . $name);
                }
                $hostOwner = $parent ? (int)$parent['clid'] : $owner;
                $hostId = insert($db, 'host', ['name' => $name, 'domain_id' => $parent ? $parent['id'] : null,
                    'clid' => $hostOwner, 'crid' => $hostOwner, 'crdate' => $d['created_at']]);
                insert($db, 'host_addr', ['host_id' => $hostId, 'addr' => $address, 'ip' => 'v4']);
                insert($db, 'host_status', ['host_id' => $hostId, 'status' => 'ok']);
            }
            insert($db, 'domain_host_map', ['domain_id' => $id, 'host_id' => $hostId]);
        }
        insert($db, 'seedemu_domain_import', ['name' => $d['name'], 'digest' => $digest]);
    }
    $db->commit();
    echo 'Registry domain import complete', PHP_EOL;
} catch (Throwable $error) {
    if ($db->inTransaction()) { $db->rollBack(); }
    throw $error;
}
