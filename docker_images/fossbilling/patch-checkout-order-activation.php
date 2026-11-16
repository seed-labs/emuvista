<?php
/** Defer activation until commit so legacy connections can read orders. */
declare(strict_types=1);
$path = $argv[1] ?? '/var/www/fossbilling/modules/Cart/Service.php';
$source = file_get_contents($path);
if (str_contains($source, '// Activate orders through legacy models after the transaction commits.')) { exit(0); }
$replace = function (string $before, string $after) use (&$source): void {
    if (substr_count($source, $before) !== 1) {
        throw new RuntimeException('结账代码不匹配，拒绝应用补丁');
    }
    $source = str_replace($before, $after, $source);
};
$replace('        $reservedOrderIds = [];', "        \$activationIds = [];\n        \$reservedOrderIds = [];");
$replace("            return \$this->di['em']->wrapInTransaction(function () use (", "            \$result = \$this->di['em']->wrapInTransaction(function () use (&\$activationIds, ");
$start = strpos($source, '                // Activate orders after the checkout state is durably persisted.');
$end = strpos($source, "\n                return [\n                    \$master_order,", $start ?: 0);
if ($start === false || $end === false) { throw new RuntimeException('找不到结账开通代码'); }
$old = substr($source, $start, $end - $start);
$new = <<<'CODE'
                // Collect activation IDs in the transaction without calling external services or legacy connections.
                $orderService = $this->di['mod_service']('Order');
                $ids = [];
                foreach ($orders as $order) {
                    $ids[] = $order->getId();
                    $oa = $orderService->toApiArray($order, false, $client);
                    $product = $this->getProductService()->findProductById((int) $oa['product_id']);
                    $isPaid = $invoiceModel instanceof \Model_Invoice
                        && $invoiceModel->status === \Model_Invoice::STATUS_PAID;
                    if ($product->getSetup() == \Box\Mod\Product\Service::SETUP_AFTER_ORDER
                        || ($product->getSetup() == \Box\Mod\Product\Service::SETUP_AFTER_PAYMENT
                            && (($ca['total'] <= 0 && $oa['total'] - $oa['discount'] <= 0)
                                || ($ca['total'] > 0 && $isPaid)))) {
                        $activationIds[] = $order->getId();
                    }
                }
CODE;
$replace($old, $new . "\n");
$before = <<<'CODE'
            throw $e;
        }
    }

    public function usePromo(Promo $promo): void
CODE;
$after = <<<'CODE'
            throw $e;
        }

        // Activate orders through legacy models after the transaction commits.
        // Activation failures do not roll back committed checkout or compensate coupons.
        $orderService = $this->di['mod_service']('Order');
        foreach (array_unique($activationIds) as $id) {
            $order = null;
            try {
                $order = $this->di['db']->getExistingModelById('ClientOrder', $id);
                $orderService->activateOrder($order);
            } catch (\Throwable $e) {
                $this->di['logger']->error('Order #%s activation failed after checkout commit: %s', $id, $e->getMessage());
                if ($order !== null) {
                    $orderService->orderStatusAdd($order, Order::STATUS_FAILED_SETUP,
                        'Order activation failed after checkout commit: ' . $e->getMessage());
                }
            }
        }

        return $result;
    }

    public function usePromo(Promo $promo): void
CODE;
$replace($before, $after);
if (file_put_contents($path, $source) === false) {
    throw new RuntimeException('无法写入结账代码');
}
