<?php
// Configure the site URL.

$path = '/var/www/fossbilling/config.php';
$url = URL_PLACEHOLDER;
$port = FORWARDED_PORT_PLACEHOLDER;
// Accept only local origins derived from port forwarding; internal requests and CLI keep the internal URL.
$expression = "/* SEED_LOCAL_URL_BEGIN */ (PHP_SAPI !== 'cli' && "
    . "in_array(strtolower(\$_SERVER['HTTP_HOST'] ?? ''), "
    . var_export($port === null ? [] : ["localhost:$port", "127.0.0.1:$port"], true)
    . ", true) ? strtolower(\$_SERVER['HTTP_HOST']) . '/' : " . var_export($url, true)
    . ") /* SEED_LOCAL_URL_END */";
$text = file_get_contents($path);
$prefix = '([\'"]url[\'"]\s*=>\s*)';
$pattern = '~' . $prefix . '/\* SEED_LOCAL_URL_BEGIN \*/.*?/\* SEED_LOCAL_URL_END \*/~s';
if (!str_contains($text, '/* SEED_LOCAL_URL_BEGIN */')) {
    $pattern = '~' . $prefix . '([\'"])(.*?)\2~s';
}
$updated = preg_replace_callback($pattern, static fn($m) => $m[1] . $expression, $text, -1, $count);
if ($count !== 1 || $updated === null) {
    throw new RuntimeException('Expected exactly one url entry in config.php');
}
if ($updated === $text) {
    echo "PASS FOSSBilling URLs already configured\n";
    exit(0);
}
// Nginx denies data/ so temporary configuration cannot be downloaded.
$temp = tempnam(dirname($path) . '/data', 'site-url-');
try {
    if (file_put_contents($temp, $updated, LOCK_EX) === false) {
        throw new RuntimeException('Failed to write FOSSBilling site URL');
    }
    exec(escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($temp) . ' 2>&1', $output, $status);
    if ($status !== 0) {
        throw new RuntimeException('Updated config failed PHP syntax validation');
    }
    chmod($temp, fileperms($path) & 0777);
    chown($temp, fileowner($path));
    chgrp($temp, filegroup($path));
    if (!rename($temp, $path)) {
        throw new RuntimeException('Failed to replace FOSSBilling config');
    }
} finally {
    if (is_file($temp)) { unlink($temp); }
}
echo "PASS FOSSBilling URLs configured\n";
