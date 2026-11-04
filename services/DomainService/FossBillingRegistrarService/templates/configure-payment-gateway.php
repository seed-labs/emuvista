<?php
// Enable the gateway without creating payments or orders.
require '/var/www/fossbilling/load.php';
try {
$checkOnly = getenv('FAKE_PAYMENT_CHECK_ONLY') === '1';
$service = $di['mod_service']('Invoice', 'PayGateway');
$gateway = $di['db']->findOne('PayGateway', 'gateway = ?', ['FakePayment']);
if (!$gateway && !$checkOnly) {
    $service->install('FakePayment');
    $gateway = $di['db']->findOne('PayGateway', 'gateway = ?', ['FakePayment']);
}
if (!$gateway) { throw new RuntimeException('FakePayment installation failed'); }
if (!$checkOnly) {
$service->update($gateway, [
    'title' => 'fakePayment', 'enabled' => 1, 'allow_single' => 1,
    'allow_recurrent' => 0, 'test_mode' => 0, 'accepted_currencies' => ['USD'],
]);
}
$gateway = $di['db']->load('PayGateway', $gateway->id);
if (!$gateway->enabled || !$gateway->allow_single || $gateway->allow_recurrent) {
    throw new RuntimeException('FakePayment settings were not persisted');
}
$adapter = $service->getPaymentAdapter($gateway);
if (!$adapter instanceof Payment_Adapter_FakePayment) {
    throw new RuntimeException('Unexpected payment adapter');
}
echo "PASS FakePayment enabled for USD single payments; gateway #", $gateway->id, "\n";
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . "\n");
    exit(1);
}
