<?php
// Generate component configuration by overriding upstream defaults with instance settings.
$config = require '/opt/registry/automation/config.php.dist';
$config = array_replace($config, [
    'db_host' => '127.0.0.1',
    'db_username' => 'registry',
    'db_password' => '__DB_PASSWORD__',
    'roid' => 'COM',
]);
file_put_contents('/opt/registry/automation/config.php',
    "<?php
return " . var_export($config, true) . ";
");
