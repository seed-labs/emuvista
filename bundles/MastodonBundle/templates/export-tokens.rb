# Run inside Rails after account initialization; never print access tokens.
require 'json'
require 'digest'
settings = JSON.parse(File.read('/opt/mastodon-service/settings.json'))
exports = JSON.parse(File.read('/opt/mastodon-service/token-exports.json'))
exports.each do |entry|
  name = entry.fetch('username')
  scopes = entry.fetch('scopes').sort.join(' ')
  application_name = "SocialMediaService #{Digest::SHA256.hexdigest([name, scopes].join("\n"))[0, 32]}"
  application = Doorkeeper::Application.find_or_create_by!(name: application_name) do |app|
    app.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
    app.scopes = scopes
    app.confidential = false
  end
  account = Account.find_by!(username: name, domain: nil)
  token = Doorkeeper::AccessToken.find_or_create_by!(
    application_id: application.id, resource_owner_id: account.user.id,
    scopes: scopes, revoked_at: nil, expires_in: nil
  )
  path = entry.fetch('path')
  File.write(path, JSON.generate(instance_url: "#{settings.fetch('scheme', 'https')}://#{settings.fetch('web_domain')}", access_token: token.token), perm: 0600)
  File.chmod(0600, path)
end
