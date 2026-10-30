<?php
// Generate component configuration by overriding upstream defaults with instance settings.
$config = require '/opt/registry/epp/config.php.dist';
$config = array_replace($config, [
    'db_host' => '127.0.0.1',
    'db_username' => 'registry',
    'db_password' => '__DB_PASSWORD__',
    'roid' => 'COM',

    'epp_host' => '0.0.0.0',
    'epp_port' => __EPP_PORT__,
    'epp_pid' => '/var/run/epp.pid',
    'epp_prefix' => 'com',
    'test_tlds' => '',
]);
file_put_contents('/opt/registry/epp/config.php',
    "<?php
return " . var_export($config, true) . ";
");
