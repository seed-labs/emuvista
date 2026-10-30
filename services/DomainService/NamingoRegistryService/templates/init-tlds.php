<?php
// Clear sample accounts and initialize TLDs only after the first schema import.
$db = new PDO('mysql:host=127.0.0.1;dbname=registry', 'registry', '__DB_PASSWORD__');
$db->beginTransaction();
foreach (['registrar_users', 'registrar_whitelist', 'registrar_contact',
          'registrar_ote', 'registrar', 'users'] as $table) {
    $db->exec('DELETE FROM ' . $table);
}
// Save upstream defaults and prices before replacing sample TLDs; fresh databases only.
$tldTemplate = $db->query('SELECT idn_table, secure, launch_phase_id FROM domain_tld WHERE id = 1')->fetch(PDO::FETCH_ASSOC);
$prices = $db->query('SELECT * FROM domain_price WHERE tldid = 1')->fetchAll(PDO::FETCH_ASSOC);
$restorePrices = $db->query('SELECT * FROM domain_restore_price WHERE tldid = 1')->fetchAll(PDO::FETCH_ASSOC);
if (!$tldTemplate || count($prices) !== 3 || count($restorePrices) !== 1) {
    throw new RuntimeException('Missing upstream TLD or pricing defaults');
}
$db->exec('DELETE FROM domain_price');
$db->exec('DELETE FROM domain_restore_price');
$db->exec('DELETE FROM domain_tld');
$insertTld = $db->prepare('INSERT INTO domain_tld (id, tld, idn_table, secure, launch_phase_id) VALUES (?, ?, ?, ?, ?)');
foreach ([__TLDS__] as $index => $tld) {
    $id = $index + 1;
    $insertTld->execute([$id, $tld, $tldTemplate['idn_table'], $tldTemplate['secure'], $tldTemplate['launch_phase_id']]);
    foreach (['domain_price' => $prices, 'domain_restore_price' => $restorePrices] as $table => $rows) {
        foreach ($rows as $row) {
            unset($row['id']);
            $row['tldid'] = $id;
            // Column names come from the pinned schema; all values use bound parameters.
            $columns = '`' . implode('`, `', array_keys($row)) . '`';
            $placeholders = implode(', ', array_fill(0, count($row), '?'));
            $db->prepare("INSERT INTO `$table` ($columns) VALUES ($placeholders)")->execute(array_values($row));
        }
    }
}
$db->exec("UPDATE settings SET value = 'Namingo Registry' WHERE name = 'company_name'");
$db->commit();
