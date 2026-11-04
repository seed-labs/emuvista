<?php
/** Fix SOA types in the pinned upstream version: stored strings must be integers for the DNS library. */
declare(strict_types=1);
$changes = [
    'start_bind9_api.php' => ['            $serialNumber,', '            (int) $serialNumber,'],
    'helpers.php' => ['$soa->setSerial($newSerial);', '$soa->setSerial((int) $newSerial);'],
];
foreach ($changes as $file => [$before, $after]) {
    $path = '/opt/bind9-api/' . $file;
    $source = file_get_contents($path);
    if (str_contains($source, $after)) { continue; }
    if (substr_count($source, $before) !== 1) {
        throw new RuntimeException('上游 SOA 代码不匹配，拒绝应用补丁：' . $file);
    }
    file_put_contents($path, str_replace($before, $after, $source));
}
