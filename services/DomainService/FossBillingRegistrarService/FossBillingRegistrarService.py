"""Install the FOSSBilling registrar on an existing host."""
import json
import shlex
from decimal import Decimal
from pathlib import Path

from seedemu.core import Server, Service

from ..FakePaymentService import FakePaymentServer
from ..NamingoRegistryService import NamingoRegistryServer
from ..NamingoRegistryService.NamingoRegistryService import normalize_tlds, sql_string


FOSSBILLING_VERSION = '0.8.7'


FossBillingRegistrarFileTemplates = {
    name: (Path(__file__).resolve().parent / 'templates' / name).read_text(encoding='utf-8')
    for name in (
        'activate-dns-hosting-module.php',
        'configure-dns-hosting-product.php',
        'configure-epp-registrar.php',
        'configure-payment-gateway.php',
        'configure-site-url.php',
        'create-client.php',
        'fake-payment-adapter.php',
        'initialize-fossbilling.py',
        'initialize-payment-gateway.sh',
        'nginx-fossbilling.conf',
        'patch-checkout-order-activation.php',
        'start-database.sh',
        'start-web.sh',
    )
}


def apt_install(packages):
    """Update indexes and install packages in one Docker layer."""
    options = '-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 '
    return ('apt-get ' + options + 'update && '
            'DEBIAN_FRONTEND=noninteractive apt-get ' + options + 'install -y '
            + ' '.join(shlex.quote(package) for package in packages.split()))


class FossBillingRegistrarServer(Server):
    """Manage registrar instance settings and its Registry connection."""

    def __init__(self):
        """Set registrar simulation defaults without fixed host addresses."""
        super().__init__()
        self._forwarded_port = 18080
        self._registry = 'registry'
        self._username = 'fossbilling'
        self._password = 'fossEpp123456'
        self._prefix = 'FOSS'
        self._tlds = None
        self._prices = {}
        self._reserved = []
        self._connection = None
        self._dns_hosting = None
        self._dns_product_id = None
        self._payment_service = None
        self._payment_settings = None
        self._payment_secret = None
        self._settings = {
            'database_password': '123456',
            'admin_email': 'admin@example.com', 'admin_password': 'Aa123456',
            'client_email': 'user@example.com', 'client_password': 'Aa123456',
            'client_profile': {
                'address_1': '123 Example Street', 'city': 'Example City', 'state': 'CA',
                'postcode': '94000', 'country': 'US', 'phone_cc': '1', 'phone': '2025550123',
            },
        }
        self.appendClassName('FossBillingRegistrarService')
        self.setDisplayName('FOSSBilling Registrar')

    def setPortForwarding(self, host_port):
        """Set the host Web port; None disables forwarding."""
        self._forwarded_port = host_port
        return self

    def getPortForwarding(self):
        """Return the forwarded host Web port, or None if disabled."""
        return self._forwarded_port

    def setRegistry(self, virtual_node, username='fossbilling', password='fossEpp123456', prefix='FOSS'):
        """Select a Registry virtual node and dedicated EPP account."""
        self._registry, self._username, self._password, self._prefix = virtual_node, username, password, prefix
        return self

    def setDnsHostings(self, hosting, product_id=None):
        """Use an existing DNS hosting pair for this registrar's local product."""
        self._dns_hosting = hosting
        self._dns_product_id = product_id
        return self

    def setPaymentService(self, virtual_node):
        """Select the checkout used by this registrar's payment adapter."""
        self._payment_service = virtual_node
        return self

    def setDatabasePassword(self, password):
        """Set the initial database account password."""
        self._settings['database_password'] = password
        return self

    def setAdminAccount(self, email, password):
        """Set initial administrator credentials."""
        self._settings.update(admin_email=email, admin_password=password)
        return self

    def setClientAccount(self, email, password, profile=None):
        """Configure the demo client with optional EPP contact overrides."""
        values = dict(self._settings['client_profile'])
        if profile is not None:
            if set(profile) - set(self._settings['client_profile']):
                raise ValueError('Unsupported client contact fields')
            values.update(profile)
        self._settings.update(client_email=email, client_password=password, client_profile=values)
        return self

    def setTlds(self, tlds):
        """Select offered TLDs; inherit Registry TLDs by default."""
        self._tlds = normalize_tlds(tlds)
        return self

    def setTldPrice(self, tld, registration='11.99', renewal='11.99', transfer='11.99'):
        """Set prices for new TLDs without overwriting existing database prices."""
        name = normalize_tlds([tld])[0]
        self._prices[name] = [
            format(Decimal(str(value)), '.2f') for value in (registration, renewal, transfer)
        ]
        return self

    def setReservedDomains(self, domains):
        """Reserve domains for this registrar, validating TLDs during rendering."""
        self._reserved = list(domains)
        return self

    def getEppUsername(self):
        """Return the EPP registrar identifier without exposing its password."""
        return self._username

    def getReservedDomains(self):
        """Return a copy of reserved domain names."""
        return list(self._reserved)

    def _configureRegistry(self, registry, registry_host, host):
        """Resolve bound addresses and register account initialization with Registry."""
        if not isinstance(registry, NamingoRegistryServer):
            raise ValueError('The selected virtual node must use NamingoRegistryService')
        if registry_host is host:
            raise ValueError('FOSSBilling and Registry require separate hosts')
        tlds = list(self._tlds) if self._tlds is not None else registry.getTlds()
        if set(tlds) - set(registry.getTlds()) or set(self._prices) - set(tlds):
            raise ValueError('Offered TLDs must be managed by Registry, and prices must refer to offered TLDs')
        address = str(host.getInterfaces()[0].getAddress())
        registry.addEppRegistrar(self._username, self._password, self._prefix, address, self._reserved)
        self._connection = {
            'host': str(registry_host.getInterfaces()[0].getAddress()), 'port': registry.getEppPort(),
            'clid': self._username, 'pw': self._password, 'registrarprefix': self._prefix,
            'local_cert': '/var/www/fossbilling/ssl/namingo_cert.pem',
            'local_pk': '/var/www/fossbilling/ssl/namingo_key.pem',
        }
        self._settings['url'] = f'http://{address}:8080/'
        self._settings['prices'] = {'.' + name: list(self._prices.get(name, ['11.99'] * 3)) for name in tlds}

    def _configureFakePayment(self, payment, payment_node, host):
        """Resolve checkout settings and register this registrar's callback origin."""
        if not isinstance(payment, FakePaymentServer):
            raise ValueError('The payment node must use FakePaymentService')
        if payment_node is host:
            raise ValueError('Checkout and registrar require distinct hosts')
        payment.authorizeCallback(f'http://{host.getInterfaces()[0].getAddress()}:8080')
        self._payment_settings = payment.getConnectionSettings()
        self._payment_secret = payment.getSharedSecret()
        browser_urls = {}
        payment_port = payment.getPortForwarding()
        if self._forwarded_port is not None and payment_port is not None:
            for hostname in ('localhost', '127.0.0.1'):
                origin = hostname if self._forwarded_port == 80 else f'{hostname}:{self._forwarded_port}'
                browser_urls[origin] = f'http://{hostname}:{payment_port}/pay'
        self._payment_settings['browser_urls'] = browser_urls

    def install(self, node):
        """Generate installation and startup operations that initialize the application inside the container."""
        if self._connection is None:
            raise RuntimeError('Configure the service through emulator.render() before installing')
        self._installSoftware(node)
        if self._dns_hosting is not None:
            self._installDnsHosting(node)
            self._settings['dns_hosting'] = True
        self._settings['forwarded_port'] = self._forwarded_port
        self._installConfiguration(node)
        if self._payment_service is not None:
            self._installPayment(node)
        if self._forwarded_port is not None:
            node.addPortForwarding(self._forwarded_port, 8080)

    def _installSoftware(self, node):
        """Install the release and Namingo EPP adapter."""
        node.setFile("/opt/fossbilling/patch-checkout-order-activation.php",
                     FossBillingRegistrarFileTemplates['patch-checkout-order-activation.php'])
        node.addBuildCommandAtEnd("php8.5 /opt/fossbilling/patch-checkout-order-activation.php "
                                  "&& php8.5 -l /var/www/fossbilling/modules/Cart/Service.php")
        node.addSoftware('ca-certificates curl software-properties-common unzip openssl cron python3 '
                         'mariadb-server mariadb-client nginx')
        node.addBuildCommand('add-apt-repository --no-update -y ppa:ondrej/php')
        node.addBuildCommand(apt_install(
            'php8.5-cli php8.5-fpm php8.5-mysql php8.5-curl php8.5-gd php8.5-intl '
            'php8.5-mbstring php8.5-xml php8.5-zip php8.5-bcmath php8.5-gmp php8.5-imap'))
        node.addBuildCommand(
            "mkdir -p /var/www/fossbilling "
            "&& curl --retry 3 --connect-timeout 30 -fsSL https://github.com/FOSSBilling/FOSSBilling/releases/download/"
            f"{FOSSBILLING_VERSION}/FOSSBilling-{FOSSBILLING_VERSION}.zip "
            "-o /tmp/fossbilling.zip "
            "&& unzip -q /tmp/fossbilling.zip -d /var/www/fossbilling "
            "&& chown -R www-data:www-data /var/www/fossbilling"
        )
        # The official installer generates the Namingo adapter and checks the release hash.
        node.addBuildCommand(
            "curl --retry 3 --connect-timeout 30 -fsSL https://raw.githubusercontent.com/getnamingo/"
            f"fossbilling-epp-registrar/018911b170ee5c5542d4f29ce6e60fbb1192e95a/"
            "install-fossbilling-epp.sh "
            "-o /tmp/install-fossbilling-epp.sh "
            "&& bash /tmp/install-fossbilling-epp.sh namingo /var/www/fossbilling"
        )

    def _installConfiguration(self, node):
        """Schedule database and web startup and save setup parameters."""
        node.setFile('/opt/fossbilling/database.sql', (
            "CREATE USER IF NOT EXISTS 'fossbilling'@'localhost' IDENTIFIED BY '__DB_PASSWORD__';\n"
            "GRANT ALL PRIVILEGES ON fossbilling.* TO 'fossbilling'@'localhost';\n"
        ).replace(
            '__DB_PASSWORD__', sql_string(self._settings['database_password'])))
        for name in ('start-database.sh', 'start-web.sh'):
            node.setFile('/opt/fossbilling/' + name, FossBillingRegistrarFileTemplates[name])
            node.appendStartCommand('sh /opt/fossbilling/' + name)
        node.setFile('/etc/nginx/conf.d/nginx-fossbilling.conf', FossBillingRegistrarFileTemplates['nginx-fossbilling.conf'])
        for name, value in [('setup-config.json', self._settings), ('epp-connection.json', self._connection)]:
            path = '/opt/fossbilling/' + name
            node.setFile(path, json.dumps(value) + '\n')
            node.addBuildCommandAtEnd('chmod 600 ' + path)
            node.insertStartCommand(0, 'chmod 600 ' + path)

        # Initialize locally after web startup, without waiting for other services.
        for name in ('initialize-fossbilling.py', 'configure-site-url.php', 'configure-epp-registrar.php', 'create-client.php'):
            node.setFile('/opt/fossbilling/' + name, FossBillingRegistrarFileTemplates[name])
        node.appendStartCommand('python3 /opt/fossbilling/initialize-fossbilling.py > /var/log/fossbilling-initialize.log 2>&1')

    def _installDnsHosting(self, node):
        """Install the extension and configure its product after local initialization."""
        settings, credentials = self._dns_hosting.getConfiguration()
        credentials['product_id'] = self._dns_product_id
        node.addBuildCommand(
            'curl --retry 3 --connect-timeout 30 -fsSL '
            'https://github.com/getnamingo/fossbilling-dns/releases/download/v1.2.7/fossbilling-dns-v1.2.7.tar.gz '
            '-o /tmp/fossbilling-dns.tar.gz && echo '
            "'8b6171b985c0bae005550f3c2fac752f9c7ccfb4f3f752d62a6920adc68160de  /tmp/fossbilling-dns.tar.gz' "
            '| sha256sum -c - && tar -xzf /tmp/fossbilling-dns.tar.gz -C /var/www/fossbilling/modules '
            '--strip-components=1 fossbilling-dns-v1.2.7/Servicedns && chown -R www-data:www-data '
            '/var/www/fossbilling/modules/Servicedns && rm /tmp/fossbilling-dns.tar.gz'
        )
        node.setFile('/opt/dns-hosting/activate-dns-hosting-module.php', FossBillingRegistrarFileTemplates['activate-dns-hosting-module.php'])
        node.setFile('/opt/dns-hosting/dns-hosting.json', json.dumps(settings) + '\n')
        path = '/opt/dns-hosting/product-credentials.json'
        node.setFile(path, json.dumps(credentials) + '\n')
        node.addBuildCommandAtEnd('chmod 600 ' + path)
        node.setFile('/opt/dns-hosting/configure-dns-hosting-product.php', FossBillingRegistrarFileTemplates['configure-dns-hosting-product.php'])

    def _installPayment(self, node):
        """Install this registrar's adapter, signing settings, and gateway initialization."""
        node.setFile('/var/www/fossbilling/library/Payment/Adapter/FakePayment.php', FossBillingRegistrarFileTemplates['fake-payment-adapter.php'])
        node.setFile('/opt/fake-payment/payment-config.json', json.dumps(self._payment_settings))
        node.setFile('/opt/fake-payment/payment-secret', self._payment_secret + '\n')
        permissions = 'chown root:www-data /opt/fake-payment/payment-secret && chmod 640 /opt/fake-payment/payment-secret'
        node.addBuildCommandAtEnd(permissions)
        node.appendStartCommand(permissions)
        for name in ('configure-payment-gateway.php', 'initialize-payment-gateway.sh'):
            node.setFile('/opt/fake-payment/' + name, FossBillingRegistrarFileTemplates[name])
        node.appendStartCommand('sh /opt/fake-payment/initialize-payment-gateway.sh > /var/log/fake-payment-initialize.log 2>&1')

    def print(self, indent):
        """Return the server description."""
        return ' ' * indent + 'FOSSBilling registrar server\n'


class FossBillingRegistrarService(Service):
    """Registrar service layer depending on Registry."""

    def __init__(self):
        """Declare base layer and Registry dependencies."""
        super().__init__()
        self.addDependency('FakePaymentService', False, True)
        for name in ('Base', 'Routing', 'NamingoRegistryService'):
            self.addDependency(name, False, False)

    def configure(self, emulator):
        """Resolve instance links before standard service binding."""
        for vnode, server in self._pending_targets.items():
            host = emulator.getBindingFor(vnode)
            registry = emulator.getServerByVirtualNodeName(server._registry)
            registry_host = emulator.getBindingFor(server._registry)
            server._configureRegistry(registry, registry_host, host)
            if server._payment_service is not None:
                payment = emulator.getServerByVirtualNodeName(server._payment_service)
                payment_node = emulator.getBindingFor(server._payment_service)
                server._configureFakePayment(payment, payment_node, host)
        super().configure(emulator)

    def _createServer(self):
        """Create a registrar instance."""
        return FossBillingRegistrarServer()

    def getName(self):
        """Return the service layer name."""
        return 'FossBillingRegistrarService'

    def getConflicts(self):
        """Prevent sharing Registry's web and database configuration on the same host."""
        return ['NamingoRegistryService']

    def print(self, indent):
        """Return the layer description."""
        return ' ' * indent + 'FossBillingRegistrarServiceLayer\n'
