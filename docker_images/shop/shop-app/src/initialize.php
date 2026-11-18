<?php
update_option('blogname', 'Emuvista Marketplace');
update_option('blogdescription', 'Town marketplace');
update_option('users_can_register', 1);
update_option('default_role', 'customer');
update_option('woocommerce_store_address', '1 Market Street');
update_option('woocommerce_store_city', 'Virtual Town');
update_option('woocommerce_default_country', 'US:CA');
update_option('woocommerce_store_postcode', '94105');
update_option('woocommerce_currency', em_shop_config()['currency']);
update_option('woocommerce_calc_taxes', 'no');
update_option('woocommerce_enable_myaccount_registration', 'yes');
update_option('woocommerce_registration_generate_username', 'no');
update_option('woocommerce_registration_generate_password', 'no');
update_option('woocommerce_enable_guest_checkout', 'no');
update_option('woocommerce_cod_settings', ['enabled' => 'no']);
update_option('woocommerce_onboarding_profile', ['completed' => true]);
update_option('woocommerce_task_list_hidden', 'yes');
update_option('woocommerce_allow_tracking', 'no');
update_option('woocommerce_coming_soon', 'no');
update_option('woocommerce_store_pages_only', 'no');
WC_Install::create_pages();
$checkout = wc_get_page_id('checkout');
wp_update_post(['ID' => $checkout, 'post_content' => '[woocommerce_checkout]']);
$cart = wc_get_page_id('cart');
wp_update_post(['ID' => $cart, 'post_content' => '[woocommerce_cart]']);
$existing = get_page_by_path('marketplace');
$home = wp_insert_post([
    'ID' => $existing ? $existing->ID : 0,
    'post_type' => 'page', 'post_status' => 'publish', 'post_title' => 'Marketplace',
    'post_content' => '[products limit="12" columns="3"]',
]);
update_option('show_on_front', 'page');
update_option('page_on_front', $home);
$stores = get_page_by_path('stores');
wp_insert_post([
    'ID' => $stores ? $stores->ID : 0,
    'post_type' => 'page', 'post_status' => 'publish', 'post_title' => 'Stores',
    'post_name' => 'stores', 'post_content' => '[marketplace_stores]',
]);
echo "Marketplace initialized.\n";
MultiVendorX()->setting->update_setting('approve_store', 'automatically');
MultiVendorX()->setting->update_setting('disable_setup_wizard', 'skip_to_dashboard');
foreach (em_shop_config()['users'] as $person) {
    $user = get_user_by('email', $person['email']);
    $id = $user ? $user->ID : wp_insert_user([
        'user_login' => $person['id'], 'user_email' => $person['email'],
        'user_pass' => $person['password'], 'display_name' => $person['name'], 'role' => 'customer',
    ]);
    if (is_wp_error($id)) throw new Exception($id->get_error_message());
    if (!empty($person['wallet'])) update_user_meta($id, 'em_payment_wallet', $person['wallet']);
    if (!empty($person['store'])) {
        wp_set_current_user($id);
        $store = em_create_store($person['store']['name']);
        foreach ($person['store']['products'] ?? [] as $product) em_create_product($product);
    }
}
wp_set_current_user(0);
update_option('emuvista_initialized', true);
