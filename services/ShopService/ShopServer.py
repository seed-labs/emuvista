"""Marketplace metadata and installation for one SEED host."""

import json
import secrets
import tempfile
from pathlib import Path
from seedemu.core import Server
from bundles import urls


class ShopServer(Server):
    def __init__(self, profile, resolver=None):
        super().__init__()
        self.setBaseSystem(profile)
        self.setDisplayName('Marketplace')
        self.appendClassName('ShopService')
        self._name = 'shop'
        self._resolver = resolver
        self._hostname = 'shop.com'
        self._port = None
        self._state = None
        self._configuration = {'currency': 'USD', 'users': []}
        self._payment = None
        self._emails = []
        self._mail = None
        self._secrets = {'database': secrets.token_urlsafe(32), 'merchant': secrets.token_urlsafe(32),
                         'wordpress': secrets.token_urlsafe(32)}

    def setHostname(self, hostname):
        self._hostname = urls.hostname(hostname)
        return self

    def setInitialConfiguration(self, configuration):
        if isinstance(configuration, (str, Path)):
            configuration = json.loads(Path(configuration).read_text())
        self._configuration = {'currency': 'USD', 'users': [], **configuration}
        return self

    def addUser(self, person):
        self._configuration['users'].append(person)
        return self

    def enableHostAccess(self, port=8449):
        self._port = port
        return self

    def setSavePath(self, path):
        self._state = Path(path).expanduser().resolve()
        credentials = self._state / 'credentials.json'
        if credentials.exists():
            self._secrets = json.loads(credentials.read_text())
            self._secrets.setdefault('wordpress', secrets.token_urlsafe(32))
        return self

    def connectPayment(self, payment, group='SEED'):
        self._payment = (payment, group)
        payment.connectMerchant(self)
        return self

    def connectEmail(self, email, username=None):
        self._emails.append((email, username))
        return self

    def getURL(self):
        return 'http://' + self._hostname

    def getPaymentRegistration(self):
        origins = [self.getURL()]
        if self._port:
            origins.extend(f'http://{host}:{self._port}' for host in ('localhost', '127.0.0.1'))
        return {'id': self._name, 'name': self._name.title(), 'secret': self._secrets['merchant'],
                'returnOrigins': origins, 'notifyURL': self.getURL() + '/wp-json/emuvista/v1/payment-notification'}

    def getAgentTools(self):
        return {'name': 'shop', 'source': Path(__file__).parent / 'tools',
                'configuration': {self._name: {'name': 'Town Marketplace', 'url': self.getURL()}}}

    def configure(self, node):
        if self._resolver:
            node.setNameServers([self._resolver])
        if self._port:
            node.addPort(f'127.0.0.1:{self._port}', 80)
        if self._emails:
            email, username = self._emails[0]
            self._mail = email.getMailConnection(username or self._name + '@' + email.getDomains()[0])

    def install(self, node):
        state = self._state or Path(tempfile.mkdtemp(prefix='emuvista-shop-'))
        state.mkdir(parents=True, exist_ok=True)
        credentials = state / 'credentials.json'
        credentials.write_text(json.dumps(self._secrets) + '\n')
        credentials.chmod(0o600)
        for directory, target in [('site', '/var/www/html'), ('database', '/var/lib/mysql')]:
            path = state / directory
            path.mkdir(exist_ok=True)
            node.addSharedFolder(target, str(path))
        settings = {**self._configuration, 'url': self.getURL(), 'mail': self._mail,
                    'browserOrigins': self.getPaymentRegistration()['returnOrigins'],
                    'databasePassword': self._secrets['database'], 'wordpressKey': self._secrets['wordpress']}
        if self._payment:
            payment, group = self._payment
            settings['payment'] = {**payment.getMerchantConnection(), 'merchant': self._name,
                                   'secret': self._secrets['merchant'], 'group': group,
                                   'currency': self._configuration['currency']}
            settings['payment']['apiURL'] += '/' + group
        node.setFile('/shop-config/config.json', json.dumps(settings, indent=2) + '\n')
        node.setLabel('org.emuvista.state-path', str(state))
        node.setLabel('org.emuvista.state-persistent', 'true' if self._state else 'false')
        node.addDockerCommand('HEALTHCHECK --interval=3s --timeout=10s --start-period=15s --retries=200 '
                              'CMD curl -fsS http://127.0.0.1/wp-json/emuvista/v1/health || exit 1')
        node.appendStartCommand('bash /opt/emuvista-shop/start.sh > /var/log/shop.log 2>&1', fork=True)
