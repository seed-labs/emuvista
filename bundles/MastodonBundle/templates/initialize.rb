# Create initial accounts and synchronize explicitly configured login credentials.
require 'json'
path = '/var/lib/mastodon/accounts.json'
credentials = File.exist?(path) ? JSON.parse(File.read(path)) : {}
accounts = JSON.parse(File.read('/opt/mastodon-service/accounts.json'))
accounts.each do |account|
  name = account.fetch('username')
  password = account.fetch('password')
  email = account.fetch('email')
  existing = Account.find_local(name)&.user
  if existing
    if existing.email != email
      existing.skip_reconfirmation!
      existing.update!(email: email, unconfirmed_email: nil)
    end
    existing.update!(password: password, password_confirmation: password) unless existing.valid_password?(password)
    credentials[name] = { 'email' => existing.email, 'password' => password }
    File.write(path, JSON.pretty_generate(credentials), perm: 0600)
    next
  end
  credentials[name] = { 'email' => email, 'password' => password }
  File.write(path, JSON.pretty_generate(credentials), perm: 0600)
  user = User.new(email: email, password: password, agreement: true,
                  confirmed_at: Time.now.utc, bypass_registration_checks: true)
  user.account = Account.new(username: name)
  user.role = UserRole.find_by!(name: 'Owner') if account.fetch('admin')
  user.save!
  user.approve!
end
Setting.site_title = 'H16 Mastodon'
owner = accounts.find { |account| account.fetch('admin') }
if owner
  Setting.site_contact_username = owner.fetch('username')
  Setting.site_contact_email = Account.find_local(owner.fetch('username')).user.email
end
Setting.registrations_mode = 'open'
puts 'Initial accounts are ready; passwords are in /var/lib/mastodon/accounts.json'
