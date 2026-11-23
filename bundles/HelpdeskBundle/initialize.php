<?php
require '/var/www/glpi/vendor/autoload.php';
$kernel = new Glpi\Kernel\Kernel();
$kernel->boot();

$admin = new User();
$admin->getFromDBByCrit(['name' => 'glpi']);
$authentication = new Auth();
$authentication->user = $admin;
$authentication->auth_succeded = true;
Session::init($authentication);
if (!Auth::checkPassword('HelpdeskAdminDemo123!', $admin->fields['password'])) {
    $admin->update(['id' => $admin->getID(), 'password' => 'HelpdeskAdminDemo123!',
                    'password2' => 'HelpdeskAdminDemo123!']);
}
$_SESSION['glpiID'] = $admin->getID();

$variable = new SsoVariable();
if (!$variable->getFromDBByCrit(['name' => 'COMPANY_AUTH_USER'])) {
    $variable->getFromDB($variable->add(['name' => 'COMPANY_AUTH_USER']));
}
Config::setConfigurationValues('core', [
    'ssovariables_id' => $variable->getID(), 'is_users_auto_add' => 1,
    'existing_auth_server_field_clean_domain' => 0,
    'enable_api' => 1, 'enable_api_login_credentials' => 1,
]);
$client = new APIClient();
$values = ['name' => 'Company directory', 'is_active' => 1,
           'app_token' => getenv('DIRECTORY_APP_TOKEN'), 'is_recursive' => 1,
           'ipv4_range_start' => '0.0.0.0', 'ipv4_range_end' => '255.255.255.255'];
if ($client->getFromDBByCrit(['name' => 'Company directory'])) {
    $client->update(['id' => $client->getID()] + $values);
} else {
    $client->add($values);
}
$profile = new Profile();
$profile->getFromDBByCrit(['interface' => 'helpdesk']);
$configuration = json_decode(file_get_contents('/helpdesk-config/company.json'), true);
$administrator = ['id' => 'admin', 'firstName' => 'Company', 'lastName' => 'Administrator',
                   'email' => 'admin@company.com'];
foreach (array_merge([$administrator], $configuration['employees']) as $person) {
    $user = new User();
    $values = ['name' => strtolower($person['id']), 'registration_number' => $person['id'],
               'firstname' => $person['firstName'], 'realname' => $person['lastName'],
               '_useremails' => [$person['email']], 'is_active' => 1, 'authtype' => Auth::EXTERNAL];
    if (!$user->getFromDBByCrit(['name' => $values['name']])) {
        $user->getFromDB($user->add($values));
    }
    $membership = new Profile_User();
    $selected_profile = $profile;
    if ($person['id'] === 'admin') {
        $selected_profile = new Profile();
        $selected_profile->getFromDBByCrit(['name' => 'Super-Admin']);
    }
    $values = ['users_id' => $user->getID(), 'profiles_id' => $selected_profile->getID(),
               'entities_id' => 0, 'is_recursive' => 1];
    if (!$membership->getFromDBByCrit($values)) {
        $membership->add($values);
    }
    if ($person['id'] === 'admin') {
        $user->update(['id' => $user->getID(), 'profiles_id' => $selected_profile->getID(),
                        'entities_id' => 0]);
    }
}
echo "Company helpdesk accounts, external authentication and API are ready.\n";
