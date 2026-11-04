"""Apache Fineract with customer and staff websites on SEED networks."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

from .containers import RoutedBundle, RoutedContainer

DEFAULT_IMAGES = {
    'core': 'apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7',
    'bff': 'emuvista/bank-consumer:ce2621c0fe76',
    'frontend': 'emuvista/bank-frontend:ce2621c0fe76',
    'staff': 'openmf/web-app@sha256:55ddd97b705766e3910e15f2cc260f25b5055d1c1465a668cdbed89946256f1c',
    'database': 'postgres:15.2-alpine',
    'redis': 'redis:7-alpine',
    'runtime': 'python:3.12-alpine',
    'gateway': 'nginx:stable-alpine',
}
ROLES = ('gateway', 'core', 'core-db', 'bff', 'bff-db', 'frontend',
         'redis', 'initialize', 'staff')


class BankBundle(RoutedBundle):
    """Fineract banking with customer/staff access and external SMTP/IMAP."""

    def __init__(self, emulator=None, images=None, name='bank', resolver=None):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
            raise ValueError('invalid bank bundle name')
        super().__init__(emulator=emulator)
        self._name, self._images = name, dict(DEFAULT_IMAGES)
        for role, image in (images or {}).items():
            if role not in DEFAULT_IMAGES or not isinstance(image, str) or not image or any(c.isspace() for c in image):
                raise ValueError('invalid bank image role or reference')
            self._images[role] = image
        self._containers = {r: RoutedContainer(name=name+'-'+r) for r in ROLES}
        self._required_emu_network_address_number = len(ROLES)
        self._configured = False
        self._initial = None
        self._state_path = None
        self._host_port = None
        self._staff_host_port = None
        self._mail = None
        self._resolver = resolver

    def setInitialConfiguration(self, configuration):
        if self._configured:
            raise RuntimeError('set bank configuration before compilation')
        data = json.loads(Path(configuration).read_text()) if isinstance(configuration, (str, Path)) else json.loads(json.dumps(configuration))
        products, customers, accounts, emails, loans = set(), set(), set(), set(), set()
        for p in data['savingsProducts']:
            if not re.fullmatch(r'[A-Z0-9]{4}', p['id']) or p['id'] in products:
                raise ValueError('savings product IDs require four unique uppercase letters/digits')
            if not re.fullmatch(r'[A-Z]{3}', p['currency']):
                raise ValueError('bank currency codes require three uppercase letters')
            products.add(p['id'])
        for c in data['customers']:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}', c['id']) or c['id'] in customers:
                raise ValueError('bank customer IDs must be unique and contain 1 to 50 letters, digits, underscores or hyphens')
            customers.add(c['id'])
            for field in ('firstName', 'lastName'):
                if not isinstance(c.get(field), str) or not 1 <= len(c[field]) <= 50:
                    raise ValueError('bank customer names require 1 to 50 characters')
            if c.get('email') and len(c.get('password', '')) < 12:
                raise ValueError('bank customer passwords require at least 12 characters')
            if c.get('email') and not c.get('emailPassword'):
                raise ValueError('initial customer registration requires emailPassword for IMAP verification')
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
                    raise ValueError('opening balances require nonnegative amounts with at most two decimals')
                accounts.add(a['id'])
            for loan in c.get('loans', []):
                if loan['id'] in loans or not re.fullmatch(r'[A-Z]{3}', loan['currency']):
                    raise ValueError('loan IDs must be unique and currencies must use three uppercase letters')
                principal = Decimal(str(loan['principal']))
                if not principal.is_finite() or principal <= 0 or principal != principal.quantize(Decimal('.01')):
                    raise ValueError('loan principals require positive amounts with at most two decimals')
                loans.add(loan['id'])
        self._initial = data
        return self

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

    def setEmailServer(self, host, username, password, certificate, port=587, imap_port=993):
        """Use an external mailbox service; certificate paths resolve during compilation."""
        if self._configured:
            raise RuntimeError('set the email server before compilation')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or not username or not password:
            raise ValueError('email server requires a host and authenticated mailbox credentials')
        if any(type(value) is not int or not 1 <= value <= 65535 for value in (port, imap_port)):
            raise ValueError('invalid email server port')
        self._mail = {'host': host, 'port': port, 'imapPort': imap_port,
                      'username': username, 'password': password, 'certificate': str(certificate)}
        return self

    def getAPIURL(self):
        return 'https://'+self.getAddress()+'/fineract-provider/api/v1'

    def configure(self):
        if self._initial is None:
            raise ValueError('BankBundle requires an explicit initial configuration')
        if self._mail is None:
            raise ValueError('BankBundle requires an external email server')
        super().configure()

    def install(self):
        if not self._configured:
            raise RuntimeError('configure BankBundle before installation')
        root = Path(self._name)
        cfg = root/'config'
        cfg.mkdir(parents=True, mode=0o700)
        source = Path(__file__).parent
        shutil.copy2(source/'initialize.py', cfg/'initialize.py')
        shutil.copy2(self._mail['certificate'], cfg/'mail-ca.pem')
        state = self._state_path or Path(tempfile.mkdtemp(prefix='seedemu-bank-'))
        if state == Path.cwd() or Path.cwd() in state.parents:
            raise ValueError('bank state must be outside compiler output')
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        credentials = state/'credentials.json'
        if credentials.exists():
            key = json.loads(credentials.read_text())
        else:
            key = {'database': secrets.token_hex(24)}
            credentials.write_text(json.dumps(key)+'\n')
            credentials.chmod(0o600)
        identity = {'addresses': self._addresses, 'initial': self._initial, 'email': {k:v for k,v in self._mail.items() if k!='certificate'}, 'resolver': self._resolver}
        stamp = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        # Adding the staff frontend does not change existing bank accounts or data.
        legacy_identity = {**identity, 'addresses': {role: address for role, address in self._addresses.items() if role != 'staff'}}
        legacy_stamp = hashlib.sha256(json.dumps(legacy_identity, sort_keys=True).encode()).hexdigest()
        if (state/'configuration.sha256').exists() and (state/'configuration.sha256').read_text() not in (stamp, legacy_stamp):
            raise ValueError('saved bank state uses a different configuration or network; use a new state directory')
        (state/'configuration.sha256').write_text(stamp)
        for f in ('server.key', 'server.crt', 'staff.key', 'staff.crt', 'jwt.pem'):
            if (state/f).exists():
                shutil.copy2(state/f, cfg/f)
        if not (cfg/'server.key').exists():
            subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '365',
                '-keyout', str(cfg/'server.key'), '-out', str(cfg/'server.crt'), '-subj', '/CN=SEED BankBundle',
                '-addext', f'subjectAltName=IP:{self.getAddress()},IP:127.0.0.1,DNS:localhost'], check=True, capture_output=True)
        if not (cfg/'staff.key').exists():
            subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '365',
                '-keyout', str(cfg/'staff.key'), '-out', str(cfg/'staff.crt'), '-subj', '/CN=SEED Bank Staff',
                '-addext', f'subjectAltName=IP:{self.getAddress("staff")},IP:127.0.0.1,DNS:localhost'], check=True, capture_output=True)
        if not (cfg/'jwt.pem').exists():
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256',
                            '-out', str(cfg/'jwt.pem')], check=True, capture_output=True)
            pub = subprocess.run(['openssl', 'pkey', '-in', str(cfg/'jwt.pem'), '-pubout'], check=True, capture_output=True).stdout
            with (cfg/'jwt.pem').open('ab') as f:
                f.write(pub)
        for f in ('server.key', 'server.crt', 'staff.key', 'staff.crt', 'jwt.pem'):
            (cfg/f).chmod(0o600)
            shutil.copy2(cfg/f, state/f)
        url = lambda role, port: f'http://{self.getAddress(role)}:{port}'
        configuration = {'initial': self._initial, 'coreURL': url('core', 8080)+'/fineract-provider/api/v1',
            'coreUsername': 'mifos', 'corePassword': 'password', 'bffURL': url('bff', 8080),
            'mail': {k:v for k,v in self._mail.items() if k!='certificate'}}
        (cfg/'config.json').write_text(json.dumps(configuration, indent=2)+'\n')
        (cfg/'config.json').chmod(0o600)
        (cfg/'init.sql').write_text('CREATE DATABASE fineract_default;\nGRANT ALL PRIVILEGES ON DATABASE fineract_default TO fineract;\n')
        (cfg/'frontend.conf').write_text('server { listen 80; server_name _; root /usr/share/nginx/html; '
            'location / { try_files $uri $uri/ /index.html; } }\n')
        (cfg/'staff-env.js').write_text('''window.env = {
  fineractApiUrls: window.location.origin, fineractApiUrl: window.location.origin,
  apiProvider: '/fineract-provider/api', apiVersion: '/v1', apiActuator: '/fineract-provider',
  fineractPlatformTenantId: 'default', fineractPlatformTenantIds: 'default',
  oauthServerEnabled: false, defaultLanguage: 'en-US', supportedLanguages: 'en-US',
  preloadClients: true, enableCopilot: false, sessionIdleTimeout: 1800000
};
''')
        (cfg/'staff-nginx.conf').write_text(f'''events {{}}
http {{
  include /etc/nginx/mime.types;
  server {{
    listen 443 ssl;
    server_name _;
    root /usr/share/nginx/html;
    ssl_certificate /bank/staff.crt;
    ssl_certificate_key /bank/staff.key;
    location = /healthz {{ return 200 'OK'; }}
    location = /assets/env.js {{ add_header Cache-Control "no-store"; }}
    location /fineract-provider/ {{ proxy_pass {url('core',8080)}/fineract-provider/; proxy_set_header Host $http_host; }}
    location / {{ try_files $uri $uri/ /index.html; }}
  }}
}}
''')
        host = self._host_port or 443
        (cfg/'nginx.conf').write_text(f'''events {{}}
http {{
  server {{
    listen 443 ssl;
    {f'listen {host} ssl;' if host != 443 else ''}
    server_name _;
    ssl_certificate /bank/server.crt;
    ssl_certificate_key /bank/server.key;
    location = /healthz {{ return 200 'OK'; }}
    location /api/ {{ proxy_pass {url('bff',8080)}/api/; proxy_set_header Host $http_host; proxy_set_header X-Forwarded-Proto https; proxy_set_header X-Forwarded-For $remote_addr; }}
    location /fineract-provider/ {{ proxy_pass {url('core',8080)}/fineract-provider/; proxy_set_header Host $http_host; }}
    location / {{ proxy_pass {url('frontend',80)}; proxy_set_header Host $http_host; }}
  }}
}}
''')
        images = self._images
        mount = f'./{self._name}/config:/bank:ro'

        def create(role, image, command, env=None, deps=(), **extra):
            c = self.getContainer(role)
            value = {'image': image, 'entrypoint': ['/bin/sh', '/bank-route.sh'], 'command': command,
                'cap_add': ['NET_ADMIN'], 'restart': 'unless-stopped', 'volumes': [mount],
                'labels': {'org.emuvista.bundle': 'BankBundle', 'org.emuvista.component': role}}
            if self._resolver:
                value['dns'] = [self._resolver]
            if env:
                value['environment'] = {k: str(v).replace('$', '$$') for k, v in env.items()}
            if deps:
                value['depends_on'] = {self.getContainer(d).getHostname(): {'condition': 'service_healthy'} for d in deps}
            value.update(extra)
            c.setContentAttribute(value)
            c._start_script_name = '/bank-route.sh'
            c._start_commands = ['#!/bin/sh', 'set -eu', 'exec "$@"']
            return c.service

        def volume(service, name, target):
            p = state/name
            p.mkdir(exist_ok=True)
            service['volumes'].append(f'{p}:{target}')

        health = lambda command: {'test': ['CMD-SHELL', command], 'interval': '4s', 'timeout': '5s', 'retries': 180}
        for role, username, dbname in [('core-db', 'fineract', 'fineract_tenants'), ('bff-db', 'consumerapp', 'consumerapp')]:
            v = create(role, images['database'], ['docker-entrypoint.sh', 'postgres'],
                {'POSTGRES_USER': username, 'POSTGRES_PASSWORD': key['database'], 'POSTGRES_DB': dbname},
                healthcheck=health(f'pg_isready -U {username} -d {dbname}'))
            volume(v, role, '/var/lib/postgresql/data')
            if role == 'core-db':
                v['volumes'].append(f'./{self._name}/config/init.sql:/docker-entrypoint-initdb.d/01-bank.sql:ro')
        v = create('redis', images['redis'], ['docker-entrypoint.sh', 'redis-server', '--appendonly', 'yes'], healthcheck=health('redis-cli ping'))
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
        create('bff', images['bff'], ['/bin/bash', '-ec',
            'rm -f /tmp/mail-trust.p12; '
            'keytool -importcert -noprompt -alias seed-mail -file /bank/mail-ca.pem '
            '-keystore /tmp/mail-trust.p12 -storetype PKCS12 -storepass changeit; '
            'exec java -Djavax.net.ssl.trustStore=/tmp/mail-trust.p12 '
            '-Djavax.net.ssl.trustStorePassword=changeit -jar /app/app.jar'],
            {'SPRING_DATASOURCE_URL': f'jdbc:postgresql://{self.getAddress("bff-db")}:5432/consumerapp',
             'SPRING_DATASOURCE_USERNAME': 'consumerapp', 'SPRING_DATASOURCE_PASSWORD': key['database'],
             'FINERACT_BASE_URL': url('core', 8080)+'/fineract-provider/api',
             'SPRING_DATA_REDIS_HOST': self.getAddress('redis'),
             'SPRING_MAIL_HOST': self._mail['host'], 'SPRING_MAIL_PORT': self._mail['port'],
             'SPRING_MAIL_USERNAME': self._mail['username'], 'SPRING_MAIL_PASSWORD': self._mail['password'],
             'OTP_EMAIL_FROM': self._mail['username'],
             'SPRING_MAIL_PROPERTIES_MAIL_SMTP_AUTH': 'true',
             'SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_ENABLE': 'true',
             'SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED': 'true',
             'SPRING_MAIL_PROPERTIES_MAIL_SMTP_SSL_CHECKSERVERIDENTITY': 'true',
             'JWT_KEY_LOCATION': 'file:/bank/jwt.pem', 'JWT_ISSUER': 'https://'+self.getAddress(),
             'AUTH_COOKIE_SECURE': 'true', 'SERVER_FORWARD_HEADERS_STRATEGY': 'framework',
             'JAVA_TOOL_OPTIONS': '-Xmx768m -Duser.timezone=UTC'}, ['core', 'bff-db', 'redis'],
            healthcheck=health("bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080'"))
        frontend = create('frontend', images['frontend'], ['/docker-entrypoint.sh', 'nginx', '-g', 'daemon off;'],
            healthcheck=health('wget -q --spider http://127.0.0.1/'))
        frontend['volumes'].append(f'./{self._name}/config/frontend.conf:/etc/nginx/conf.d/default.conf:ro')
        v = create('initialize', images['runtime'], ['python3', '/bank/initialize.py'],
                   deps=['core', 'bff'], restart='on-failure:3', healthcheck={'disable': True})
        volume(v, 'initialization', '/bank-state')
        v = create('gateway', images['gateway'], ['/docker-entrypoint.sh', 'nginx', '-c', '/bank/nginx.conf', '-g', 'daemon off;'],
                   deps=['frontend', 'bff'], healthcheck=health('wget -q --no-check-certificate --spider https://127.0.0.1/healthz'))
        v['depends_on'][self.getContainer('initialize').getHostname()] = {'condition': 'service_completed_successfully'}
        if self._host_port:
            v['ports'] = [f'127.0.0.1:{host}:{host}/tcp']
        v = create('staff', images['staff'], ['/docker-entrypoint.sh', 'nginx', '-c', '/bank/staff-nginx.conf', '-g', 'daemon off;'],
                   deps=['core'], healthcheck=health('wget -q --no-check-certificate --spider https://127.0.0.1/healthz'))
        v['volumes'].append(f'./{self._name}/config/staff-env.js:/usr/share/nginx/html/assets/env.js:ro')
        if self._staff_host_port:
            v['ports'] = [f'127.0.0.1:{self._staff_host_port}:443/tcp']
        (root/'deployment.json').write_text(json.dumps({'addresses': self._addresses, 'state_path': str(state),
            'images': images, 'browser': f'https://localhost:{host}',
            'staff_browser': f'https://localhost:{self._staff_host_port}' if self._staff_host_port else None,
            'persistent': self._state_path is not None}, indent=2)+'\n')
        Path('docker-compose.yml').touch(mode=0o600, exist_ok=True)
        Path('docker-compose.yml').chmod(0o600)
        return super().install()
