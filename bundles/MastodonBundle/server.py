"""Application configuration and startup templates owned by MastodonBundle."""
import json
from pathlib import Path
import re

from seedemu.core import Server


class SocialMediaServer(Server):
    """Configure one self-contained Mastodon instance."""

    def __init__(self):
        super().__init__()
        self._domain = 'mastodon.com'
        self._port = 443
        self._forwarded_port = None
        self._accounts = []
        self._token_exports = []
        self._acme_url = None
        self._scheme = 'https'
        self.appendClassName('MastodonBundle')
        self.setDisplayName('Mastodon')

    def setDomain(self, domain):
        """Set the stable account domain; create its DNS record in the scenario."""
        if (not isinstance(domain, str) or len(domain) > 253 or '.' not in domain
                or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                       for label in domain.split('.'))):
            raise ValueError('Expected a DNS hostname without a scheme or port')
        self._domain = domain.lower()
        return self

    def setAcmeUrl(self, url):
        """Use an ACME CA trusted by the node for HTTPS certificate issuance."""
        self._acme_url = url
        return self

    def setHttp(self, port=8080):
        """Use HTTP with an application image that explicitly supports it."""
        self.setPort(port)
        self._scheme = 'http'
        self._acme_url = None
        return self

    def setHttps(self, port=443):
        """Use HTTPS, optionally with the CA configured through setAcmeUrl()."""
        self.setPort(port)
        self._scheme = 'https'
        return self

    def setPort(self, port):
        """Set the canonical HTTPS port, also used inside the simulation."""
        if type(port) is not int or not 1 <= port <= 65535 or port in (80, 3000, 4000):
            raise ValueError('Invalid HTTPS port (80, 3000 and 4000 are reserved)')
        self._port = port
        return self

    def setPortForwarding(self, host_port):
        """Forward HTTPS; use the canonical port to preserve browser URLs."""
        if host_port is not None and (type(host_port) is not int or not 1 <= host_port <= 65535):
            raise ValueError('Expected a TCP port or None')
        self._forwarded_port = host_port
        return self

    def addAccount(self, username, password, *, email, admin=False):
        """Configure a public username, login email and password; synchronize credentials at startup."""
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_]{1,30}', username):
            raise ValueError('Expected a username of 1-30 letters, digits or underscores')
        if not isinstance(password, str) or not password:
            raise ValueError('Expected a non-empty password')
        if not isinstance(email, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Expected a valid login email address')
        if any(account['email'].lower() == email.lower() for account in self._accounts):
            raise ValueError('Email already configured: ' + email)
        if type(admin) is not bool:
            raise ValueError('Expected a boolean admin flag')
        if any(account['username'].lower() == username.lower() for account in self._accounts):
            raise ValueError('Account already configured: ' + username)
        self._accounts.append({'username': username, 'password': password, 'email': email, 'admin': admin})
        return self

    def exportToken(self, username, *, scopes, path):
        """Export an account's API token at startup to a private Mastodon data file."""
        if not any(account['username'] == username for account in self._accounts):
            raise ValueError('Configure the account with addAccount() first')
        if (not isinstance(scopes, (list, tuple)) or not scopes
                or any(not isinstance(scope, str) or not re.fullmatch(r'[a-z]+(?::[a-z_]+)?', scope)
                       for scope in scopes)):
            raise ValueError('Expected a non-empty list of OAuth scopes')
        destination = Path(path)
        if destination.parent != Path('/var/lib/mastodon') or destination.suffix != '.json':
            raise ValueError('Token file must be a JSON file directly in /var/lib/mastodon')
        if destination.name == 'accounts.json':
            raise ValueError('Token file must not overwrite account credentials')
        if any(item['path'] == str(destination) for item in self._token_exports):
            raise ValueError('Token export path already configured')
        self._token_exports.append({'username': username, 'scopes': list(dict.fromkeys(scopes)),
                                    'path': str(destination)})
        return self

    def install(self, node):
        if self._scheme == 'http' and self._acme_url:
            raise ValueError('HTTP does not use an ACME CA')
        if self._forwarded_port is not None and self._forwarded_port != self._port:
            raise ValueError('Forwarded and canonical HTTPS ports must match; call setPort()')
        files = Path(__file__).parent / 'templates'
        for path in sorted(files.iterdir()):
            if path.is_file():
                node.setFile('/opt/mastodon-service/' + path.name, path.read_text())
        default_port = 443 if self._scheme == 'https' else 80
        web_domain = self._domain + (f':{self._port}' if self._port != default_port else '')
        node.setFile('/opt/mastodon-service/settings.json', json.dumps({
            'domain': self._domain, 'web_domain': web_domain,
            'port': self._port, 'acme_url': self._acme_url,
            **({'scheme': 'http'} if self._scheme == 'http' else {}),
        }) + '\n')
        node.setFile('/opt/mastodon-service/accounts.json', json.dumps(self._accounts) + '\n')
        node.setFile('/opt/mastodon-service/token-exports.json', json.dumps(self._token_exports) + '\n')
        packages = ('ca-certificates curl git build-essential pkg-config '
                         'libssl-dev libyaml-dev libreadline-dev zlib1g-dev libgmp-dev '
                         'libgdbm-dev libffi-dev libicu-dev libidn-dev libpq-dev '
                         'libvips-dev ffmpeg imagemagick postgresql postgresql-contrib '
                         'redis-server nginx openssl supervisor python3 xz-utils')
        if self._acme_url:
            packages += ' certbot cron'
            node.addPersistentStorage('/etc/letsencrypt',
                                      name=f'mastodon-{node.getAsn()}-{node.getName()}-letsencrypt')
        # Install packages in a normal Docker layer for both legacy and BuildKit builds.
        apt_options = '-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 '
        # Retain the base image's official Ubuntu package sources.
        node.addBuildCommand(
            'apt-get ' + apt_options + 'update && '
            'DEBIAN_FRONTEND=noninteractive apt-get ' + apt_options +
            'install -y --no-install-recommends ' + packages)
        # 构建时安装依赖，启动时初始化数据 / Build software, initialize data at startup.
        node.addBuildCommandAtEnd('bash /opt/mastodon-service/install.sh')
        for path in ('/var/lib/postgresql', '/var/lib/redis', '/var/lib/mastodon',
                     '/opt/mastodon/public/system'):
            name = f'mastodon-{node.getAsn()}-{node.getName()}-' + path.rsplit('/', 1)[-1]
            node.addPersistentStorage(path, name=name)
        node.appendStartCommand('bash /opt/mastodon-service/start.sh > /var/log/mastodon-initialize.log 2>&1')
        if self._forwarded_port is not None:
            node.addPortForwarding(self._forwarded_port, self._port)

    def print(self, indent):
        return ' ' * indent + f'Mastodon server: {self._domain}\n'
