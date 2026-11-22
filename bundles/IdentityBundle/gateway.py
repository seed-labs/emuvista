"""Configure a standard OIDC gateway for backends with trusted-header login."""


def apache_configuration(identity, upstream, public_url, cookie, header_secret=''):
    value = f'''<VirtualHost *:80>
    ServerName {public_url}
    ProxyPreserveHost On
    OIDCProviderMetadataURL {identity['discovery_url']}
    OIDCClientID {identity['client_id']}
    OIDCClientSecret {identity['client_secret']}
    OIDCRedirectURI {public_url}/sso/callback
    OIDCCryptoPassphrase {identity['client_secret']}
    OIDCScope "openid profile email"
    OIDCRemoteUserClaim preferred_username
    OIDCCookie {cookie}
    OIDCSSLValidateServer Off

    <Location />
        AuthType openid-connect
        Require valid-user
        RequestHeader unset X-Authenticated-User
        RequestHeader unset Remote-User
        RequestHeader unset X-Company-SSO
        RequestHeader set X-Authenticated-User "expr=%{{REMOTE_USER}}{(':' + header_secret) if header_secret else ''}"
        RequestHeader set Remote-User "expr=%{{REMOTE_USER}}"
        RequestHeader set X-Company-SSO "{identity['client_secret']}"
    </Location>

    # These endpoints use the backend's own API credentials.
    <LocationMatch "^/(api/|apirest.php|health_checks/)">
        AuthType None
        Require all granted
        RequestHeader unset X-Authenticated-User
        RequestHeader unset Remote-User
        RequestHeader unset X-Company-SSO
    </LocationMatch>

    ProxyPass / {upstream}/
    ProxyPassReverse / {upstream}/
    ErrorLog /proc/self/fd/2
    CustomLog /proc/self/fd/1 combined
</VirtualHost>
'''
    return value
