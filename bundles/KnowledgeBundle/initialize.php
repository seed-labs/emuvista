<?php
// Configure native models after the upstream migrations have completed.
require '/var/www/bookstack/vendor/autoload.php';
$app = require '/var/www/bookstack/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
set_exception_handler(static function (Throwable $error): void {
    fwrite(STDERR, $error->getMessage() . "\n");
    exit(1);
});

$metadata = simplexml_load_string(file_get_contents(getenv('IDENTITY_METADATA')));
$certificates = $metadata->xpath('//*[local-name()="KeyDescriptor"][@use="signing"]//*[local-name()="X509Certificate"]');
$certificate = preg_replace('/\s+/', '', (string) $certificates[0]);
file_put_contents('/knowledge-keys/certificate.pem', "-----BEGIN CERTIFICATE-----\n"
    . chunk_split($certificate, 64, "\n") . "-----END CERTIFICATE-----\n");

$admin = BookStack\Users\Models\User::whereIn('email', ['admin@admin.com', 'admin@company.com'])->firstOrFail();
$admin->external_auth_id = 'admin';
$admin->email = 'admin@company.com';
$admin->name = 'Company Administrator';
$admin->save();
Illuminate\Support\Facades\DB::table('api_tokens')->updateOrInsert(
    ['token_id' => 'company-directory'],
    ['name' => 'Company employee directory', 'user_id' => $admin->id,
     'secret' => Illuminate\Support\Facades\Hash::make(getenv('DIRECTORY_TOKEN_SECRET')),
     'expires_at' => now()->addYears(5)->toDateString(),
     'created_at' => now(), 'updated_at' => now()]
);

$configuration = json_decode(file_get_contents('/knowledge-config/company.json'), true);
$editor = BookStack\Users\Models\Role::where('display_name', 'Editor')->firstOrFail();
$users = app(BookStack\Users\UserRepo::class);
foreach ($configuration['employees'] as $person) {
    $user = BookStack\Users\Models\User::where('external_auth_id', $person['id'])->first();
    if (!$user) {
        $user = $users->createWithoutActivity([
            'name' => $person['firstName'] . ' ' . $person['lastName'],
            'email' => $person['email'], 'external_auth_id' => $person['id'],
            'roles' => [$editor->id],
        ], true);
    } elseif (!$user->slug) {
        $users->updateWithoutActivity($user, ['name' => $user->name], true);
    }
}
echo "Company knowledge accounts and directory API are ready.\n";
