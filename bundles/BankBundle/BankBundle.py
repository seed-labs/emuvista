"""Apache Fineract with customer and staff websites on SEED networks."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer
from bundles import urls

DEFAULT_IMAGES = {
    'core': 'apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7',
    'bff': 'handsonsecurity/emuvista-bank-consumer:1.0',
    'frontend': 'handsonsecurity/emuvista-bank-frontend:1.0',
    'staff': 'openmf/web-app@sha256:55ddd97b705766e3910e15f2cc260f25b5055d1c1465a668cdbed89946256f1c',
    'database': 'postgres:15.2-alpine',
    'redis': 'redis:7-alpine',
    'runtime': 'python:3.12-alpine',
    'gateway': 'nginx:stable-alpine',
}
ROLES = ('gateway', 'core', 'core-db', 'bff', 'bff-db', 'frontend',
         'redis', 'initialize', 'staff')


class BankBundle(ContainerBundle):
    """Fineract banking with customer/staff access and external SMTP/IMAP."""

    def getAgentTools(self):
        """Export bank tools and this instance's private connection settings."""
        sender = (self._mail or {}).get('username')
        if self._mail_sources:
            provider, username = self._mail_sources[0]
            sender = username or (self._initial or {}).get(
                'sender') or 'bank@' + provider.getDomains()[0]
        return {'name': 'bank', 'source': Path(__file__).parent / 'tools',
                'configuration': {self._name: {'name': self._display_name,
                                               'url': self.getURL(), 'browserURL': self.getURL(), 'sender': sender}}}

    def __init__(self, emulator=None, images=None, name='bank', resolver=None):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
            raise ValueError('invalid bank bundle name')
        super().__init__(emulator=emulator)
        self._name, self._images = name, dict(DEFAULT_IMAGES)
        for role, image in (images or {}).items():
            if role not in DEFAULT_IMAGES or not isinstance(image, str) or not image or any(c.isspace() for c in image):
                raise ValueError('invalid bank image role or reference')
            self._images[role] = image
        self._containers = {r: PreparedContainer(
            name=name + '-' + r, emulator=self._emulator) for r in ROLES}
        self._required_internal_address_count = len(ROLES)
        self._configured = False
        self._addresses = {}
        self._initial = None
        self._state_path = None
        self._host_port = None
        self._staff_host_port = None
        self._mail = None
        self._mail_sources = []
        self._mailboxes = {}
        self._mail_dependencies = []
        self._mail_initializer = None
        self._resolver = resolver
        self._api_clients = {}
        self._payment_services = {}
        self._display_name = name.replace('-', ' ').title()
        self._secrets = None
        self._hostname = None

    def setHostname(self, hostname):
        self._hostname = urls.hostname(hostname)
        return self

    def setDisplayName(self, name):
        self._display_name = name
        return self

    def connectPayment(self, payment):
        """Record a payment partnership; configure() registers the API client."""
        if self._configured:
            raise RuntimeError('set payment partnerships before compilation')
        self._payment_services[payment.getClientId()] = payment
        return self

    def getURL(self):
        return 'http://' + (self._hostname or self.getAddress())

    def registerAPIClient(self, client_id, redirect_uris):
        """Register a third-party API client, without linking any customer.

        Customers authorize card access in the bank website.
        """
        if self._configured:
            raise RuntimeError('register API clients before compilation')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', client_id):
            raise ValueError('invalid API client identifier')
        from urllib.parse import urlsplit
        uris = list(redirect_uris)
        if not uris or any(urlsplit(uri).scheme != 'http' or not urlsplit(uri).hostname
                           or any(c in uri for c in ',\n\r') for uri in uris):
            raise ValueError('API callbacks require HTTP URLs')
        self._api_clients[client_id] = {'clientId': client_id, 'redirectURIs': uris}
        return self

    def _credentials(self):
        if self._secrets is None:
            saved = self._state_path / 'credentials.json' if self._state_path else None
            if saved and saved.exists():
                self._secrets = json.loads(saved.read_text())
            else:
                self._secrets = {'database': secrets.token_hex(24)}
        return self._secrets

    def getOpenBankingConnection(self, client_id=None):
        """Export server-side OAuth settings and API addresses."""
        if not self._configured and self._payment_services:
            self.configure()
        if not self._api_clients:
            raise ValueError('register an API client before exporting its connection')
        if client_id is None:
            if len(self._api_clients) != 1:
                raise ValueError('select a client ID when multiple payment clients are registered')
            client_id = next(iter(self._api_clients))
        client = self._api_clients[client_id]
        secret = hashlib.sha256(
            (self._credentials()['database'] + ':' + client['clientId']).encode()).hexdigest()
        return {'id': self._name, 'name': self._display_name,
                'currencies': sorted({product['currency'] for product in self._initial['savingsProducts']}),
                'apiURL': self.getURL() + '/api/v1',
                'browserURL': self.getURL() if self._hostname else ('http://localhost:' + str(self._host_port) if self._host_port else self.getURL()),
                'clientId': client['clientId'], 'clientSecret': secret,
                'redirectURIs': list(client['redirectURIs']),
                'readyServices': [self.getContainer('gateway').getHostname()],
                'hostURL': 'http://localhost:' + str(self._host_port) if self._host_port else None}

    def setInitialConfiguration(self, configuration):
        if self._configured:
            raise RuntimeError('set bank configuration before compilation')
        data = json.loads(Path(configuration).read_text()) if isinstance(
            configuration, (str, Path)) else json.loads(json.dumps(configuration))
        data.setdefault('customers', [])
        products, customers, accounts, emails, loans = set(), set(), set(), set(), set()
        card_ids, card_numbers = set(), set()

        def valid_card_number(number):
            if not re.fullmatch(r'[0-9]{16,19}', number):
                return False
            digits = [int(digit) for digit in reversed(number)]
            return sum(digit if i % 2 == 0 else (digit * 2 - 9 if digit > 4 else digit * 2)
                       for i, digit in enumerate(digits)) % 10 == 0
        for p in data['savingsProducts']:
            if not re.fullmatch(r'[A-Z0-9]{4}', p['id']) or p['id'] in products:
                raise ValueError('savings product IDs require four unique uppercase letters/digits')
            if not re.fullmatch(r'[A-Z]{3}', p['currency']):
                raise ValueError('bank currency codes require three uppercase letters')
            products.add(p['id'])
        for c in data['customers']:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}', c['id']) or c['id'] in customers:
                raise ValueError(
                    'bank customer IDs must be unique and contain 1 to 50 letters, digits, underscores or hyphens')
            customers.add(c['id'])
            for field in ('firstName', 'lastName'):
                if not isinstance(c.get(field), str) or not 1 <= len(c[field]) <= 50:
                    raise ValueError('bank customer names require 1 to 50 characters')
            if c.get('email') and len(c.get('password', '')) < 12:
                raise ValueError('bank customer passwords require at least 12 characters')
            if c.get('email') and not c.get('emailPassword'):
                raise ValueError(
                    'initial customer registration requires emailPassword for IMAP verification')
            if c.get('email'):
                email = c['email'].lower()
                if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', email) or email in emails:
                    raise ValueError('bank customer emails must be valid and unique')
                emails.add(email)
            for a in c['accounts']:
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}', a['id']) or a['id'] in accounts or a['product'] not in products:
                    raise ValueError('duplicate account ID or unknown savings product')
                balance = Decimal(str(a['balance']))
                if not balance.is_finite() or balance < 0 or balance != balance.quantize(Decimal('.01')):
                    raise ValueError(
                        'opening balances require nonnegative amounts with at most two decimals')
                accounts.add(a['id'])
            owned_accounts = {account['id'] for account in c['accounts']}
            for card in c.get('cards', []):
                number = str(card.get('number', '')).replace(' ', '').replace('-', '')
                if (not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}', card.get('id', ''))
                        or card['id'] in card_ids or number in card_numbers
                        or not valid_card_number(number)):
                    raise ValueError(
                        'cards require unique IDs and valid 16 to 19 digit simulated card numbers')
                if not c.get('email') or card.get('account') not in owned_accounts:
                    raise ValueError(
                        'cards require a registered customer and an account owned by that customer')
                card['number'] = number
                card.setdefault('name', card['id'])
                card.setdefault('status', 'active')
                card.setdefault('expires', '2035-12')
                if (not isinstance(card['name'], str) or not 1 <= len(card['name']) <= 100
                        or card['status'] not in ('active', 'blocked')
                        or not re.fullmatch(r'[0-9]{4}-[0-9]{2}', card['expires'])):
                    raise ValueError('invalid card name, status or expiry month')
                date.fromisoformat(card['expires'] + '-01')
                card_ids.add(card['id'])
                card_numbers.add(number)
            for loan in c.get('loans', []):
                if loan['id'] in loans or not re.fullmatch(r'[A-Z]{3}', loan['currency']):
                    raise ValueError(
                        'loan IDs must be unique and currencies must use three uppercase letters')
                principal = Decimal(str(loan['principal']))
                if not principal.is_finite() or principal <= 0 or principal != principal.quantize(Decimal('.01')):
                    raise ValueError(
                        'loan principals require positive amounts with at most two decimals')
                loans.add(loan['id'])
        self._initial = data
        return self

    def addCustomer(self, customer):
        """Add one initial customer and their accounts before compilation."""
        return self.setInitialConfiguration({**self._initial,
                                             'customers': [*self._initial['customers'], customer]})

    def setSavePath(self, path):
        if self._configured:
            raise RuntimeError('set bank state before compilation')
        self._state_path = Path(path).expanduser().resolve()
        return self

    def enableHostAccess(self, port=8444, staff_port=8446):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('invalid bank browser port')
        if staff_port is not None and (type(staff_port) is not int or not 1 <= staff_port <= 65535 or staff_port == port):
            raise ValueError('invalid or duplicate bank staff browser port')
        self._host_port = port
        self._staff_host_port = staff_port
        return self

    def connectEmail(self, host, username=None, password=None, port=587, imap_port=143, *, initializer=None):
        """Record mail partners; the first supplies outgoing SMTP."""
        if self._configured:
            raise RuntimeError('set the email server before compilation')
        if not isinstance(host, str):
            for index, (provider, _) in enumerate(self._mail_sources):
                if provider is host:
                    self._mail_sources[index] = (host, username)
                    break
            else:
                self._mail_sources.append((host, username))
            return self
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or not username or not password:
            raise ValueError('email server requires a host and authenticated mailbox credentials')
        if any(type(value) is not int or not 1 <= value <= 65535 for value in (port, imap_port)):
            raise ValueError('invalid email server port')
        self._mail = {'host': host, 'port': port, 'imapPort': imap_port,
                      'username': username, 'password': password}
        self._mail_sources = []
        self._mailboxes = {}
        self._mail_dependencies = [initializer] if initializer else []
        self._mail_initializer = initializer
        return self

    def getAPIURL(self):
        return self.getURL() + '/fineract-provider/api/v1'

    def getAPIConnection(self):
        """Export server-side API access and readiness information."""
        if not self._configured:
            self.configure()
        return {'url': self.getAPIURL(), 'username': 'mifos', 'password': 'password',
                'readyServices': [self.getContainer('gateway').getHostname()]}

    def getInitialAccount(self, external_id):
        """Return account ownership and currency metadata without user secrets."""
        if self._initial is None:
            raise ValueError('set bank initial configuration before resolving accounts')
        products = {product['id']: product for product in self._initial['savingsProducts']}
        for customer in self._initial['customers']:
            for account in customer['accounts']:
                if account['id'] == external_id:
                    return {'id': external_id, 'customerId': customer['id'],
                            'email': customer.get('email', '').lower(),
                            'currency': products[account['product']]['currency']}
        raise ValueError('bank account is not defined in the initial configuration')

    def configure(self):
        if self._configured:
            return
        if self._initial is None:
            raise ValueError('BankBundle requires an explicit initial configuration')
        if self._mail_sources:
            source, username = self._mail_sources[0]
            username = username or self._initial.get('sender') or 'bank@' + source.getDomains()[0]
            connection = source.getMailConnection(
                username, initializer=self.getContainer('initialize').getHostname())
            self._mail_initializer = connection.pop('initializer')
            self._mail = connection
            self._mail_dependencies = [self._mail_initializer]
            for provider, _ in self._mail_sources:
                mailbox = provider.getMailboxConnection()
                self._mail_dependencies.extend(mailbox['readyServices'])
                for domain in provider.getDomains():
                    self._mailboxes.setdefault(
                        domain, {key: mailbox[key] for key in ('host', 'imapPort')})
        if self._mail is None:
            raise ValueError('BankBundle requires an external email server')
        for client_id, payment in self._payment_services.items():
            self.registerAPIClient(client_id, payment.getAuthorizationCallbacks())
        super().configure()
        net, = self.getInternalNetworks()
        for (role, container), address in zip(self._containers.items(), net['ip_addresses']):
            container.joinInternalNetwork(net['asn'], net['network_name'], address,
                                          container.getHostname(), net['default_route'])
            self._addresses[role] = address
        self._configured = True

    def getAddress(self, role='gateway'):
        if not self._configured:
            self.configure()
        return self._addresses[role]

    def install(self):
        if not self._configured:
            raise RuntimeError('configure BankBundle before installation')
        root = Path(self._name)
        cfg = root / 'config'
        cfg.mkdir(parents=True, mode=0o700)
        source = Path(__file__).parent
        shutil.copy2(source / 'initialize.py', cfg / 'initialize.py')
        state = self._state_path or Path(tempfile.mkdtemp(prefix='seedemu-bank-'))
        if state == Path.cwd() or Path.cwd() in state.parents:
            raise ValueError('bank state must be outside compiler output')
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        credentials = state / 'credentials.json'
        key = self._credentials()
        if not credentials.exists():
            credentials.write_text(json.dumps(key) + '\n')
            credentials.chmod(0o600)
        identity = {'addresses': self._addresses, 'initial': self._initial, 'email': dict(self._mail),
                    'mailboxes': self._mailboxes, 'resolver': self._resolver}
        stamp = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        # Adding the staff frontend does not change existing bank accounts or data.
        legacy_identity = {**identity, 'addresses': {role: address for role,
                                                     address in self._addresses.items() if role != 'staff'}}
        legacy_stamp = hashlib.sha256(json.dumps(
            legacy_identity, sort_keys=True).encode()).hexdigest()
        if (state / 'configuration.sha256').exists() and (state / 'configuration.sha256').read_text() not in (stamp, legacy_stamp):
            raise ValueError(
                'saved bank state uses a different configuration or network; use a new state directory')
        (state / 'configuration.sha256').write_text(stamp)
        if (state / 'jwt.pem').exists():
            shutil.copy2(state / 'jwt.pem', cfg / 'jwt.pem')
        if not (cfg / 'jwt.pem').exists():
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256',
                            '-out', str(cfg / 'jwt.pem')], check=True, capture_output=True)
            pub = subprocess.run(['openssl', 'pkey', '-in', str(cfg / 'jwt.pem'),
                                 '-pubout'], check=True, capture_output=True).stdout
            with (cfg / 'jwt.pem').open('ab') as f:
                f.write(pub)
        (cfg / 'jwt.pem').chmod(0o600)
        shutil.copy2(cfg / 'jwt.pem', state / 'jwt.pem')
        url = lambda role, port: f'http://{self.getAddress(role)}:{port}'
        api = self.getAPIConnection()
        configuration = {'initial': self._initial, 'coreURL': url('core', 8080) + '/fineract-provider/api/v1',
                         'coreUsername': api['username'], 'corePassword': api['password'], 'bffURL': url('bff', 8080),
                         'mail': dict(self._mail), 'mailboxes': self._mailboxes}
        (cfg / 'config.json').write_text(json.dumps(configuration, indent=2) + '\n')
        (cfg / 'config.json').chmod(0o600)
        card_configuration = []
        products = {product['id']: product for product in self._initial['savingsProducts']}
        for customer in self._initial['customers']:
            accounts = {account['id']: account for account in customer['accounts']}
            for card in customer.get('cards', []):
                card_configuration.append({**card, 'id': self._name + ':' + card['id'],
                                           'email': customer['email'].lower(),
                                           'currency': products[accounts[card['account']]['product']]['currency']})
        (cfg / 'cards.json').write_text(json.dumps(card_configuration) + '\n')
        (cfg / 'cards.json').chmod(0o600)
        (cfg / 'init.sql').write_text('CREATE DATABASE fineract_default;\nGRANT ALL PRIVILEGES ON DATABASE fineract_default TO fineract;\n')
        (cfg / 'frontend.conf').write_text('server { listen 80; server_name _; root /usr/share/nginx/html; '
                                           'location / { try_files $uri $uri/ /index.html; } }\n')
        (cfg / 'staff-env.js').write_text('''window.env = {
  fineractApiUrls: window.location.origin, fineractApiUrl: window.location.origin,
  apiProvider: '/fineract-provider/api', apiVersion: '/v1', apiActuator: '/fineract-provider',
  fineractPlatformTenantId: 'default', fineractPlatformTenantIds: 'default',
  oauthServerEnabled: false, defaultLanguage: 'en-US', supportedLanguages: 'en-US',
  preloadClients: true, enableCopilot: false, sessionIdleTimeout: 1800000
};
''')
        (cfg / 'staff-nginx.conf').write_text(f'''events {{}}
http {{
  include /etc/nginx/mime.types;
  server {{
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    location = /healthz {{ return 200 'OK'; }}
    location = /assets/env.js {{ add_header Cache-Control "no-store"; }}
    location /fineract-provider/ {{ proxy_pass {url('core',8080)}/fineract-provider/; proxy_set_header Host $http_host; }}
    location / {{ try_files $uri $uri/ /index.html; }}
  }}
}}
''')
        host = self._host_port or 80
        (cfg / 'nginx.conf').write_text(f'''events {{}}
http {{
  server {{
    listen 80;
    {f'listen {host};' if host != 80 else ''}
    server_name _;
    location = /healthz {{ return 200 'OK'; }}
    location /api/ {{ proxy_pass {url('bff',8080)}/api/; proxy_set_header Host $http_host; proxy_set_header X-Forwarded-Proto http; proxy_set_header X-Forwarded-For $remote_addr; proxy_redirect {self.getURL()}/ http://$http_host/; }}
    location /fineract-provider/ {{ proxy_pass {url('core',8080)}/fineract-provider/; proxy_set_header Host $http_host; }}
    location / {{ proxy_pass {url('frontend',80)}; proxy_set_header Host $http_host; }}
  }}
}}
''')
        images = self._images
        mount = f'./{self._name}/config:/bank:ro'

        services = {}

        def create(role, image, command, env=None, deps=(), **extra):
            c = self.getContainer(role)
            value = {'image': image, 'command': command,
                     'cap_add': ['NET_ADMIN'], 'restart': 'unless-stopped', 'volumes': [mount],
                     'labels': {'org.emuvista.bundle': 'BankBundle', 'org.emuvista.component': role}}
            if self._resolver:
                value['dns'] = [self._resolver]
            if env:
                value['environment'] = {k: str(v).replace('$', '$$') for k, v in env.items()}
            if deps:
                value['depends_on'] = {self.getContainer(d).getHostname(
                ): {'condition': 'service_healthy'} for d in deps}
            value.update(extra)
            c.setFile('/application-start.sh', '#!/bin/sh\nexec "$@"\n')
            c.setEntrypointWrapper('/application-start.sh', [])
            services[role] = value
            return value

        def volume(service, name, target):
            p = state / name
            p.mkdir(exist_ok=True)
            service['volumes'].append(f'{p}:{target}')

        health = lambda command: {'test': ['CMD-SHELL', command],
                                  'interval': '4s', 'timeout': '5s', 'retries': 180}
        for role, username, dbname in [('core-db', 'fineract', 'fineract_tenants'), ('bff-db', 'consumerapp', 'consumerapp')]:
            v = create(role, images['database'], ['docker-entrypoint.sh', 'postgres'],
                       {'POSTGRES_USER': username,
                           'POSTGRES_PASSWORD': key['database'], 'POSTGRES_DB': dbname},
                       healthcheck=health(f'pg_isready -U {username} -d {dbname}'))
            volume(v, role, '/var/lib/postgresql/data')
            if role == 'core-db':
                v['volumes'].append(
                    f'./{self._name}/config/init.sql:/docker-entrypoint-initdb.d/01-bank.sql:ro')
        v = create('redis', images['redis'], ['docker-entrypoint.sh', 'redis-server',
                   '--appendonly', 'yes'], healthcheck=health('redis-cli ping'))
        volume(v, 'redis', '/data')
        create('core', images['core'], ['java', '-cp', '@/app/jib-classpath-file', 'org.apache.fineract.ServerApplication'],
               {'FINERACT_HIKARI_DRIVER_SOURCE_CLASS_NAME': 'org.postgresql.Driver',
                'FINERACT_HIKARI_JDBC_URL': f'jdbc:postgresql://{self.getAddress("core-db")}:5432/fineract_tenants',
                'FINERACT_HIKARI_USERNAME': 'fineract', 'FINERACT_HIKARI_PASSWORD': key['database'],
                'FINERACT_DEFAULT_TENANTDB_HOSTNAME': self.getAddress('core-db'), 'FINERACT_DEFAULT_TENANTDB_PORT': 5432,
                'FINERACT_DEFAULT_TENANTDB_UID': 'fineract', 'FINERACT_DEFAULT_TENANTDB_PWD': key['database'],
                'FINERACT_SERVER_SSL_ENABLED': 'false', 'FINERACT_SERVER_PORT': 8080,
                'JAVA_TOOL_OPTIONS': '-Xmx1536m -Duser.timezone=UTC'}, ['core-db'],
               healthcheck=health('wget -q --spider http://127.0.0.1:8080/fineract-provider/actuator/health'))
        bff = create('bff', images['bff'], ['java', '-jar', '/app/app.jar'],
                     {'SPRING_DATASOURCE_URL': f'jdbc:postgresql://{self.getAddress("bff-db")}:5432/consumerapp',
                      'SPRING_DATASOURCE_USERNAME': 'consumerapp', 'SPRING_DATASOURCE_PASSWORD': key['database'],
                      'FINERACT_BASE_URL': url('core', 8080) + '/fineract-provider/api',
                      'SPRING_DATA_REDIS_HOST': self.getAddress('redis'),
                      'SPRING_MAIL_HOST': self._mail['host'], 'SPRING_MAIL_PORT': self._mail['port'],
                      'SPRING_MAIL_USERNAME': self._mail['username'], 'SPRING_MAIL_PASSWORD': self._mail['password'],
                      'OTP_EMAIL_FROM': self._mail['username'],
                      'SPRING_MAIL_PROPERTIES_MAIL_SMTP_AUTH': 'true',
                      'SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_ENABLE': 'false',
                      'SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED': 'false',
                      'JWT_KEY_LOCATION': 'file:/bank/jwt.pem', 'JWT_ISSUER': 'http://' + self.getAddress(),
                      'AUTH_COOKIE_SECURE': 'false', 'SERVER_FORWARD_HEADERS_STRATEGY': 'framework',
                      'AUTH_COOKIE_PREFIX': self._name + '_', 'CONSUMER_CARDS_CONFIG': '/bank/cards.json',
                      'JAVA_TOOL_OPTIONS': '-Xmx768m -Duser.timezone=UTC'}, ['core', 'bff-db', 'redis'],
                     healthcheck=health("bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080'"))
        if self._api_clients:
            clients = []
            for client_id, client in self._api_clients.items():
                connection = self.getOpenBankingConnection(client_id)
                clients.append({key: connection[key] for key in (
                    'clientId', 'clientSecret', 'redirectURIs')})
            (cfg / 'payment-clients.json').write_text(json.dumps(clients) + '\n')
            (cfg / 'payment-clients.json').chmod(0o600)
            bff['environment']['CONSUMER_PAYMENTS_CLIENTS_CONFIG'] = '/bank/payment-clients.json'
            if len(clients) == 1:
                connection = clients[0]
                bff['environment'].update({
                    'CONSUMER_PAYMENTS_CLIENT_ID': connection['clientId'],
                    'CONSUMER_PAYMENTS_CLIENT_SECRET': connection['clientSecret'],
                    'CONSUMER_PAYMENTS_REDIRECT_URIS': ','.join(connection['redirectURIs']),
                })
            bff['environment']['OB_FRONTEND_BASE_URL'] = self.getOpenBankingConnection(clients[0]['clientId'])[
                'browserURL']
        frontend = create('frontend', images['frontend'], ['/docker-entrypoint.sh', 'nginx', '-g', 'daemon off;'],
                          healthcheck=health('wget -q --spider http://127.0.0.1/'))
        frontend['volumes'].append(
            f'./{self._name}/config/frontend.conf:/etc/nginx/conf.d/default.conf:ro')
        v = create('initialize', images['runtime'], ['python3', '/bank/initialize.py'],
                   deps=['core', 'bff'], restart='on-failure:3', healthcheck={'disable': True})
        for dependency in self._mail_dependencies:
            v['depends_on'][dependency] = {'condition': 'service_completed_successfully'}
        volume(v, 'initialization', '/bank-state')
        v = create('gateway', images['gateway'], ['/docker-entrypoint.sh', 'nginx', '-c', '/bank/nginx.conf', '-g', 'daemon off;'],
                   deps=['frontend', 'bff'], healthcheck=health('wget -q --spider http://127.0.0.1/healthz'))
        v['depends_on'][self.getContainer('initialize').getHostname()] = {
            'condition': 'service_completed_successfully'}
        if self._host_port:
            v['ports'] = [f'127.0.0.1:{host}:{host}/tcp']
        v = create('staff', images['staff'], ['/docker-entrypoint.sh', 'nginx', '-c', '/bank/staff-nginx.conf', '-g', 'daemon off;'],
                   deps=['core'], healthcheck=health('wget -q --spider http://127.0.0.1/healthz'))
        v['volumes'].append(
            f'./{self._name}/config/staff-env.js:/usr/share/nginx/html/assets/env.js:ro')
        if self._staff_host_port:
            v['ports'] = [f'127.0.0.1:{self._staff_host_port}:80/tcp']
        (root / 'deployment.json').write_text(json.dumps({'addresses': self._addresses, 'state_path': str(state),
                                                          'images': images, 'browser': f'http://localhost:{host}',
                                                         'staff_browser': f'http://localhost:{self._staff_host_port}' if self._staff_host_port else None,
                                                          'persistent': self._state_path is not None}, indent=2) + '\n')
        Path('docker-compose.yml').touch(mode=0o600, exist_ok=True)
        Path('docker-compose.yml').chmod(0o600)
        for role, value in services.items():
            self.getContainer(role).updateServiceConfig(value)
        return super().install()
