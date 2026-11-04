<?php
declare(strict_types=1);

// Initialize locally through CLI without a web endpoint or reading or printing administrator credentials.
if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    exit(1);
}
$root = '/var/www/fossbilling';
if (!is_file($root . '/config.php')) {
    exit(75);
}
chdir($root);
require $root . '/load.php';
$di = include $root . '/di.php';
$di['is_cron'] = true;
$di['translate']();
try {
    $di['pdo']->query('SELECT id FROM extension LIMIT 1');
} catch (Throwable $error) {
    // The installer has not created the database or tables; retry after application setup.
    exit(75);
}
try {
    $extensions = $di['mod_service']('extension');
    if (!$extensions->isExtensionActive('mod', 'servicedns')) {
        $extensions->activateExistingExtension(['type' => 'mod', 'id' => 'servicedns']);
    }
    if (!$extensions->isExtensionActive('mod', 'servicedns')) {
        throw new RuntimeException('DNS extension is not active');
    }
    $di['pdo']->query('SELECT id FROM service_dns LIMIT 1');
    $di['pdo']->query('SELECT id FROM service_dns_records LIMIT 1');
    echo "DNS Hosting Product enabled; DNS tables verified.\n";
} catch (Throwable $error) {
    fwrite(STDERR, 'DNS Hosting activation failed (' . get_class($error) . ").\n");
    exit(1);
}
