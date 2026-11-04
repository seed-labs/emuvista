<?php
/** Configure the Bind backend through the product service without retrying customer orders or payments. */
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { exit(1); }
try {
    $input = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
    require '/opt/dns-hosting/activate-dns-hosting-module.php';
    $hosting = json_decode(file_get_contents('/opt/dns-hosting/dns-hosting.json'), true, 512, JSON_THROW_ON_ERROR);
    $config = [
        'provider' => 'Bind', 'bindip' => $hosting['primary'], 'bindip_ns2' => $hosting['secondary'],
        'apikey' => $input['primary']['username'] . ':' . $input['primary']['password'],
        'apikey_ns2' => $input['secondary']['username'] . ':' . $input['secondary']['password'],
        'ns1' => $hosting['ns1'], 'ns2' => $hosting['ns2'], 'soaemail' => $hosting['soaemail'],
    ];
    $products = $di['mod_service']('product');
    $id = (int) ($input['product_id'] ?? 0);
    $created = false;
    if (!$id) {
        $ids = $di['pdo']->query("SELECT id FROM product WHERE type = 'dns' ORDER BY id")->fetchAll(PDO::FETCH_COLUMN);
        if (count($ids) > 1) { throw new DomainException('存在多个 DNS 产品，请使用 registrar.setDnsHostings(..., product_id=ID) 指定'); }
        $id = $ids ? (int) $ids[0] : (int) $products->createProduct('DNS Hosting', 'dns');
        $created = !$ids;
    }
    $product = $products->findProductById($id);
    if (!$product || $product->getType() !== 'dns') { throw new DomainException('指定产品不是 DNS Hosting'); }
    $existing = json_decode($product->getConfig() ?: '{}', true, 512, JSON_THROW_ON_ERROR);
    if (!empty($existing['provider']) && $existing['provider'] !== 'Bind') {
        throw new DomainException('已有产品使用其他 Provider，拒绝覆盖');
    }
    $settings = ['config' => array_replace($existing, $config)];
    // Assign a category so the product has a purchase link in the client area.
    if (!$product->getProductCategoryId()) {
        $query = $di['pdo']->prepare('SELECT id FROM product_category WHERE title = ? ORDER BY id LIMIT 1');
        $query->execute(['DNS Hosting']);
        $categoryId = $query->fetchColumn();
        if (!$categoryId) { $categoryId = $products->createCategory('DNS Hosting', '域名解析托管服务'); }
        if (!$categoryId) { throw new DomainException('无法创建 DNS Hosting 商品分类'); }
        $settings['product_category_id'] = (int) $categoryId;
    }
    // New simulation products are free; preserve existing prices, status, and activation policy.
    if ($created) {
        $settings += ['status' => 'enabled', 'setup' => 'after_payment', 'pricing' => ['type' => 'free']];
    }
    $products->updateProduct($product, $settings);
    echo 'DNS Hosting 产品 #', $id, ' 已配置 Bind 主从 API；已有订单未重试。', PHP_EOL;
} catch (Throwable $error) {
    // Do not print request bodies or credentials from third-party exceptions.
    fwrite(STDERR, $error instanceof DomainException ? $error->getMessage() . PHP_EOL
        : 'DNS Hosting 初始化失败（' . get_class($error) . '）；请核对产品选择和主从 API。' . PHP_EOL);
    exit(1);
}
