<?php
/** Plugin Name: Emuvista Marketplace Integration */

defined('ABSPATH') || exit;
function em_shop_config() {
    static $settings;
    return $settings ??= json_decode(file_get_contents('/shop-config/config.json'), true, 512, JSON_THROW_ON_ERROR);
}
function em_payment_request($path, $body = null) {
    $settings = em_shop_config()['payment'];
    $response = wp_remote_request($settings['apiURL'] . $path, [
        'method' => $body === null ? 'GET' : 'POST', 'timeout' => 120,
        'headers' => ['Authorization' => 'Bearer ' . $settings['secret'], 'Content-Type' => 'application/json'],
        'body' => $body === null ? null : wp_json_encode($body),
    ]);
    if (is_wp_error($response)) throw new Exception('Payment is unavailable: ' . $response->get_error_message());
    $data = json_decode(wp_remote_retrieve_body($response), true);
    if (wp_remote_retrieve_response_code($response) >= 300) throw new Exception($data['errors'][0]['detail'] ?? 'Payment rejected the request');
    return $data;
}
function em_store_id($user = 0) {
    return (int) get_user_meta($user ?: get_current_user_id(), 'multivendorx_active_store', true);
}
// Preserve store filters on both legacy WordPress orders and WooCommerce HPOS.
add_filter('woocommerce_order_data_store_cpt_get_orders_query', function ($query, $arguments) {
    if (!empty($arguments['meta_query'])) $query['meta_query'][] = $arguments['meta_query'];
    return $query;
}, 10, 2);
add_filter('woocommerce_order_data_store_cpt_query_unsupported_args', function ($arguments) {
    return array_values(array_diff($arguments, ['meta_query']));
});
// Vendor management stays scoped. A seller's customer view must also see other stores.
function em_customer_queries() {
    if (!function_exists('MultiVendorX')) return;
    $callback = [MultiVendorX()->abilities, 'multivendorx_get_current_store_items'];
    remove_filter('woocommerce_product_data_store_cpt_get_products_query', $callback, 20);
    remove_filter('woocommerce_orders_table_datastore_get_orders_query', $callback, 20);
}
add_action('wp', 'em_customer_queries', 0);
add_action('rest_api_init', function () {
    $route = $GLOBALS['wp']->query_vars['rest_route'] ?? '';
    if (str_starts_with($route, '/emuvista/v1/') || str_starts_with($route, '/wc/store/')) em_customer_queries();
}, 0);
function em_create_store($name) {
    if (em_store_id()) return em_store_id();
    $store = new \MultiVendorX\Store\Store();
    $store->set('name', sanitize_text_field($name));
    $store->set('slug', sanitize_title($name) . '-' . get_current_user_id());
    $store->set('status', 'active');
    $id = $store->save();
    \MultiVendorX\Store\StoreUtil::set_primary_owner(get_current_user_id(), $id);
    \MultiVendorX\Store\StoreUtil::add_store_users(['store_id' => $id, 'users' => [get_current_user_id()], 'role_id' => 'store_owner']);
    wp_get_current_user()->set_role('store_owner');
    update_user_meta(get_current_user_id(), 'multivendorx_active_store', $id);
    $store->update_meta('store_email', ['list' => [wp_get_current_user()->user_email], 'primary' => wp_get_current_user()->user_email]);
    return $id;
}
function em_create_product($data) {
    if (!em_store_id()) throw new Exception('Open a store first');
    if ((int) ($data['priceMinor'] ?? 0) <= 0) throw new Exception('A positive price in cents is required');
    $product = new WC_Product_Simple();
    $product->set_name(sanitize_text_field($data['title']));
    $product->set_description(wp_kses_post($data['description'] ?? ''));
    $product->set_short_description(wp_kses_post($data['description'] ?? ''));
    $product->set_regular_price(wc_format_decimal($data['priceMinor'] / 100, 2));
    $product->set_status('publish');
    $product->set_virtual(true);
    $product->update_meta_data('multivendorx_store_id', em_store_id());
    $id = $product->save();
    wp_update_post(['ID' => $id, 'post_author' => get_current_user_id()]);
    if (!empty($data['content'])) {
        $upload = wp_upload_dir();
        $directory = $upload['basedir'] . '/woocommerce_uploads';
        wp_mkdir_p($directory);
        file_put_contents($directory . '/.htaccess', "deny from all\n");
        $filename = $id . '-' . wp_generate_password(24, false) . '.txt';
        file_put_contents($directory . '/' . $filename, $data['content']);
        $download = new WC_Product_Download();
        $download->set_id(wp_generate_uuid4());
        $download->set_name($product->get_name());
        $download->set_file($upload['baseurl'] . '/woocommerce_uploads/' . $filename);
        $product->set_downloadable(true);
        $product->set_downloads([$download]);
        $product->save();
    }
    return ['id' => $id, 'title' => $product->get_name(), 'url' => get_permalink($id)];
}
function em_product_owner($product) {
    $store = \MultiVendorX\Store\Store::get_store($product->get_id(), 'product');
    if (!$store) throw new Exception('Product has no store');
    $owner = \MultiVendorX\Store\StoreUtil::get_primary_owner($store->get_id());
    $wallet = get_user_meta($owner, 'em_payment_wallet', true);
    if (!$wallet) throw new Exception('Seller must connect a Payment wallet before accepting orders');
    return ['wallet' => $wallet, 'name' => $store->get('name')];
}
function em_checkout($order) {
    if ($order->is_paid()) return ['status' => 'paid'];
    $settings = em_shop_config()['payment'];
    if ($order->get_currency() !== $settings['currency']) throw new Exception('Shop and payment currency differ');
    $allocations = [];
    $total = 0;
    foreach ($order->get_items() as $item) {
        $owner = em_product_owner($item->get_product());
        $amount = (int) round(($item->get_total() + $item->get_total_tax()) * 100);
        if ($amount <= 0) throw new Exception('Zero-value purchases are not supported by this gateway');
        $wallet = $owner['wallet'];
        if (!isset($allocations[$wallet])) $allocations[$wallet] = ['payee' => $wallet, 'amountMinor' => 0, 'label' => $owner['name']];
        $allocations[$wallet]['amountMinor'] += $amount;
        $total += $amount;
    }
    if ($total !== (int) round($order->get_total() * 100)) throw new Exception('Shipping and fees need a recipient; this gateway currently supports item totals only');
    $return = add_query_arg(['em_return' => $order->get_id(), 'key' => $order->get_order_key()], home_url('/'));
    $session = em_payment_request('/checkout/merchants/' . $settings['merchant'] . '/sessions', [
        'order' => (string) $order->get_id(), 'returnURL' => $return, 'allocations' => array_values($allocations),
    ]);
    $order->update_meta_data('_em_checkout', $session['id']);
    $order->update_meta_data('_em_allocations', array_values($allocations));
    $order->save();
    update_option('em_checkout_' . $session['id'], $order->get_id(), false);
    $origin = $settings['url'];
    if (isset($_SERVER['HTTP_HOST']) && in_array('http://' . $_SERVER['HTTP_HOST'], em_shop_config()['browserOrigins'], true)) $origin = $settings['browserURL'];
    return ['id' => $session['id'], 'group' => $settings['group'], 'url' => $origin . '/checkout/' . $settings['group'] . '/' . $session['id']];
}
function em_confirm($order) {
    global $wpdb;
    $lock = 'em-confirm-' . $order->get_id();
    if (!$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 10)', $lock))) throw new Exception('Order confirmation is busy; retry shortly');
    try {
        $order->get_data_store()->read($order);
        if ($order->is_paid() || !$order->get_meta('_em_checkout')) return;
        $settings = em_shop_config()['payment'];
        $session = em_payment_request('/checkout/merchants/' . $settings['merchant'] . '/sessions/' . $order->get_meta('_em_checkout'));
        if ($session['status'] !== 'paid') return;
        $expected = $order->get_meta('_em_allocations');
        $actual = array_map(function ($item) { unset($item['transferId']); return $item; }, $session['allocations']);
        if ($session['order'] !== (string) $order->get_id() || $session['amountMinor'] !== (int) round($order->get_total() * 100)
            || $session['currency'] !== $order->get_currency() || $expected != $actual) throw new Exception('Payment receipt does not match the order');
        $order->payment_complete($session['id']);
        $order->add_order_note('Payment verified against the payment server. Recipients received their order amounts directly.');
    } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)', $lock)); }
}
function em_order_result($order) {
    $items = [];
    foreach ($order->get_items() as $item) $items[] = ['product' => $item->get_product_id(), 'title' => $item->get_name(), 'quantity' => $item->get_quantity()];
    return ['id' => $order->get_id(), 'status' => $order->get_status(), 'paid' => $order->is_paid(),
        'amountMinor' => (int) round($order->get_total() * 100), 'currency' => $order->get_currency(), 'items' => $items,
        'checkout' => $order->get_meta('_em_checkout'), 'buyer' => $order->get_billing_email()];
}
// Agent clients authenticate as their own WordPress user. Browser clients use the native cookie and REST nonce.
add_filter('determine_current_user', function ($user) {
    if ($user || !str_contains($_SERVER['REQUEST_URI'] ?? '', '/emuvista/v1/')) return $user;
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (!str_starts_with($header, 'Basic ')) return $user;
    $credentials = explode(':', base64_decode(substr($header, 6)), 2);
    $result = wp_authenticate($credentials[0], $credentials[1] ?? '');
    return is_wp_error($result) ? $user : $result->ID;
}, 30);
add_action('rest_api_init', function () {
    $register = function ($route, $method, $callback, $public = false) {
        register_rest_route('emuvista/v1', $route, ['methods' => $method,
            'permission_callback' => $public ? '__return_true' : function () { return is_user_logged_in(); },
            'callback' => function ($request) use ($callback) {
                try { return $callback($request); }
                catch (Throwable $error) { return new WP_Error('shop_request_failed', $error->getMessage(), ['status' => 400]); }
            }]);
    };
    $register('/health', 'GET', function () {
        if (!get_option('emuvista_initialized')) throw new Exception('Marketplace initialization is incomplete');
        return ['ready' => true];
    }, true);
    $register('/catalog', 'GET', function () {
        $products = [];
        foreach (wc_get_products(['status' => 'publish', 'limit' => 100]) as $product) {
            $store = \MultiVendorX\Store\Store::get_store($product->get_id(), 'product');
            $products[] = ['id' => $product->get_id(), 'title' => $product->get_name(),
                'description' => wp_strip_all_tags($product->get_short_description()), 'priceMinor' => (int) round($product->get_price() * 100),
                'currency' => get_woocommerce_currency(), 'store' => $store ? $store->get('name') : '', 'url' => get_permalink($product->get_id())];
        }
        return ['products' => $products];
    }, true);
    $register('/stores', 'POST', function ($r) { return ['id' => em_create_store($r['name'])]; });
    $register('/products', 'POST', function ($r) { return em_create_product($r->get_json_params()); });
    $register('/orders', 'POST', function ($r) {
        if (!is_array($r['items']) || !count($r['items']) || count($r['items']) > 20) throw new Exception('Choose 1 to 20 products');
        $request_id = sanitize_text_field($r['requestId']);
        if (!$request_id) throw new Exception('A unique requestId is required');
        global $wpdb;
        $lock = 'em-order-' . substr(hash('sha256', get_current_user_id() . ':' . $request_id), 0, 48);
        if (!$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 10)', $lock))) throw new Exception('Order creation is busy; retry the same requestId');
        try {
            $existing = $wpdb->get_var($wpdb->prepare(
                "SELECT option_value FROM {$wpdb->options} WHERE option_name = %s", $lock));
            if ($existing) return em_order_result(wc_get_order((int) $existing));
            $cart = [];
            foreach ($r['items'] as $item) {
                $product = wc_get_product(absint($item['product']));
                $quantity = (int) ($item['quantity'] ?? 1);
                if (!$product || !$product->is_purchasable() || !$product->is_virtual() || $quantity < 1 || $quantity > 100) throw new Exception('Choose a purchasable virtual product and quantity 1 to 100');
                em_product_owner($product);
                $cart[] = [$product, $quantity];
            }
            $order = wc_create_order(['customer_id' => get_current_user_id()]);
            foreach ($cart as [$product, $quantity]) $order->add_product($product, $quantity);
            $order->set_billing_email(wp_get_current_user()->user_email);
            $order->set_currency(get_woocommerce_currency());
            $order->set_payment_method('emuvista');
            $order->set_payment_method_title('Payment wallet or bank card');
            $order->update_meta_data('_em_request', $request_id);
            $order->calculate_totals();
            $order->save();
            add_option($lock, $order->get_id(), '', false);
            (new \MultiVendorX\Order\OrderManager())->create_store_orders($order);
            return em_order_result($order);
        } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)', $lock)); }
    });
    $owned = function ($id) {
        $order = wc_get_order(absint($id));
        if (!$order || $order->get_customer_id() !== get_current_user_id() || $order->get_parent_id()) throw new Exception('Order does not belong to this buyer');
        return $order;
    };
    $register('/orders/(?P<id>\d+)/checkout', 'POST', function ($r) use ($owned) { return em_checkout($owned($r['id'])); });
    $register('/orders', 'GET', function () {
        $orders = wc_get_orders(['customer_id' => get_current_user_id(), 'parent' => 0, 'limit' => 30]);
        foreach ($orders as $order) em_confirm($order);
        return ['orders' => array_map('em_order_result', $orders)];
    });
    $register('/sales', 'GET', function () {
        if (!em_store_id()) return ['orders' => []];
        $orders = wc_get_orders(['limit' => 30, 'meta_query' => [['key' => 'multivendorx_store_id', 'value' => em_store_id()]]]);
        return ['orders' => array_map('em_order_result', $orders)];
    });
    $register('/downloads', 'GET', function () {
        $downloads = [];
        foreach (wc_get_customer_available_downloads(get_current_user_id()) as $item) {
            $downloads[] = ['order' => $item['order_id'], 'product' => $item['product_id'], 'name' => $item['download_name'], 'url' => $item['download_url']];
        }
        return ['downloads' => $downloads];
    });
    $register('/downloads/(?P<id>\d+)', 'GET', function ($r) {
        foreach (wc_get_customer_available_downloads(get_current_user_id()) as $item) {
            if ((int) $item['product_id'] !== (int) $r['id']) continue;
            $product = wc_get_product($item['product_id']);
            $download = $product->get_downloads()[$item['download_id']] ?? null;
            if (!$download) continue;
            $upload = wp_upload_dir();
            $filename = basename(parse_url($download->get_file(), PHP_URL_PATH));
            $path = realpath($upload['basedir'] . '/woocommerce_uploads/' . $filename);
            if (!$path || !str_starts_with($path, realpath($upload['basedir'] . '/woocommerce_uploads') . '/')) continue;
            if (filesize($path) > 65536) throw new Exception('Download is too large for a text tool');
            return ['product' => $product->get_id(), 'title' => $product->get_name(), 'content' => file_get_contents($path)];
        }
        throw new Exception('This product is not available in your paid downloads');
    });
    $register('/payment-notification', 'POST', function ($r) {
        $id = get_option('em_checkout_' . sanitize_text_field($r['id']));
        $order = $id ? wc_get_order((int) $id) : null;
        if (!$order || $order->get_meta('_em_checkout') !== $r['id']) throw new Exception('Checkout not found');
        em_confirm($order);
        return ['paid' => $order->is_paid()];
    }, true);
});
add_action('template_redirect', function () {
    if (!isset($_GET['em_return'], $_GET['key'])) return;
    $order = wc_get_order(absint($_GET['em_return']));
    if (!$order || !hash_equals($order->get_order_key(), sanitize_text_field(wp_unslash($_GET['key'])))) wp_die('Order key is invalid');
    try { em_confirm($order); }
    catch (Throwable $error) { wc_add_notice($error->getMessage(), 'error'); }
    wp_safe_redirect($order->get_checkout_order_received_url()); exit;
});
// A seller proves ownership by signing in to Payment. Only the resulting wallet ID is saved.
function em_bind_wallet($email, $password) {
    $settings = em_shop_config()['payment'];
    $response = wp_remote_post($settings['authURL'] . '/token', ['timeout' => 30, 'body' => [
        'grant_type' => 'password', 'client_id' => 'komunitin-app', 'username' => $email, 'password' => $password,
        'scope' => 'email accounting:read accounting:write',
    ]]);
    if (is_wp_error($response)) throw new Exception('Payment login is unavailable');
    $token = json_decode(wp_remote_retrieve_body($response), true)['access_token'] ?? null;
    if (!$token) throw new Exception('Payment login failed');
    // This authenticated endpoint returns only wallets owned by the signed-in user.
    $response = wp_remote_get($settings['apiURL'] . '/checkout/accounts', [
        'headers' => ['Authorization' => 'Bearer ' . $token], 'timeout' => 30,
    ]);
    if (is_wp_error($response)) throw new Exception('Payment wallet lookup failed');
    $accounts = json_decode(wp_remote_retrieve_body($response), true)['accounts'] ?? [];
    if (count($accounts) !== 1) throw new Exception('This shop currently requires one wallet in the selected Payment community');
    update_user_meta(get_current_user_id(), 'em_payment_wallet', $accounts[0]['id']);
}
add_action('woocommerce_edit_account_form', function () {
    echo '<fieldset><legend>Shop receiving wallet</legend><p>Sign in to Payment once to receive sales in that wallet. The password is not saved.</p>';
    echo '<p><label>Payment email <input name="em_wallet_email" type="email" autocomplete="off"></label></p>';
    echo '<p><label>Payment password <input name="em_wallet_password" type="password" autocomplete="new-password"></label></p></fieldset>';
    if (get_user_meta(get_current_user_id(), 'em_payment_wallet', true)) echo '<p>Receiving wallet connected.</p>';
});
add_action('woocommerce_save_account_details_errors', function ($errors) {
    if (empty($_POST['em_wallet_email'])) return;
    try { em_bind_wallet(sanitize_email(wp_unslash($_POST['em_wallet_email'])), wp_unslash($_POST['em_wallet_password'] ?? '')); }
    catch (Throwable $error) { $errors->add('wallet', $error->getMessage()); }
});
add_action('plugins_loaded', function () {
    if (!class_exists('WC_Payment_Gateway')) return;
    class Emuvista_Payment_Gateway extends WC_Payment_Gateway {
        public function __construct() {
            $this->id = 'emuvista'; $this->method_title = 'Payment'; $this->title = 'Payment wallet or bank card';
            $this->description = 'Continue to Payment and choose your balance or a linked bank card.';
            $this->enabled = empty(em_shop_config()['payment']) ? 'no' : 'yes';
            $this->has_fields = false; $this->supports = ['products'];
        }
        public function process_payment($order_id) {
            try {
                $checkout = em_checkout(wc_get_order($order_id));
                return ['result' => 'success', 'redirect' => $checkout['url']];
            } catch (Throwable $error) { wc_add_notice($error->getMessage(), 'error'); return ['result' => 'failure']; }
        }
    }
    add_filter('woocommerce_payment_gateways', function ($gateways) { $gateways[] = 'Emuvista_Payment_Gateway'; return $gateways; });
}, 20);

add_action('phpmailer_init', function ($mailer) {
    $mail = em_shop_config()['mail'] ?? null;
    if (!$mail) return;
    $mailer->isSMTP(); $mailer->Host = $mail['host']; $mailer->Port = $mail['port'];
    $mailer->SMTPAuth = true; $mailer->Username = $mail['username']; $mailer->Password = $mail['password'];
    $mailer->SMTPSecure = ''; $mailer->SMTPAutoTLS = false;
    $mailer->setFrom($mail['username'], 'Town Marketplace');
});

add_action('woocommerce_thankyou_emuvista', function ($id) {
    $order = wc_get_order($id);
    echo '<p><strong>' . ($order->is_paid() ? 'Payment verified. Your order is paid.' : 'Payment has not been confirmed. This order is awaiting payment.') . '</strong></p>';
});
