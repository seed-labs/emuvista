"""Company messaging with native channels, direct messages and OIDC."""

import json
from pathlib import Path
import secrets

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from bundles import company, urls


class WorkChatBundle(ContainerBundle):

    def __init__(self, emulator=None, name='work-chat', resolver=None):
        super().__init__(emulator=emulator)
        self._name, self._resolver = name, resolver
        self._containers = {role: PreparedContainer(name=name + '-' + role, emulator=emulator)
                            for role in ('web', 'initialize', 'database', 'queue', 'redis', 'cache')}
        self._hostname = 'chat.company.com'
        self._host_port = None
        self._configuration = {}
        self._identity = None
        self._state_path = None

    def setHostname(self, hostname):
        self._hostname = urls.hostname(hostname)
        return self

    def setInitialConfiguration(self, value):
        self._configuration = company.configuration(value)
        return self

    def enableHostAccess(self, port=8086):
        self._host_port = port
        return self

    def setSavePath(self, path):
        self._state_path = Path(path).expanduser().resolve()
        return self

    def connectIdentity(self, identity):
        self._identity = identity
        return self

    def getURL(self):
        return 'https://' + self._hostname

    def _browser_url(self):
        return f'https://{self._hostname.split(".")[0]}.localhost:{self._host_port}' if self._host_port else self.getURL()

    def configure(self):
        super().configure()
        self._addresses = company.assign_networks(
            self, ('web', 'initialize'), ('database', 'queue', 'redis', 'cache'))
        self._public_url = self._browser_url()
        self._connection = self._identity.registerClient(self._name, [
            self._public_url + '/complete/oidc/', self.getURL() + '/complete/oidc/'])
        self._api_key = self._connection['client_secret'].encode().hex()[:32]
        self._identity.registerEmployeeConsumer(self._name, Path(__file__).with_name('identity.py'), {
            'url': self.getURL(), 'host': self._public_url.split('://')[1],
            'email': 'admin@company.com', 'api_key': self._api_key, 'verify_tls': False,
        })

    def getNotificationConnection(self):
        public = self._browser_url()
        client = self._identity.registerClient(self._name, [
            public + '/complete/oidc/', self.getURL() + '/complete/oidc/'])
        hostname = public.split('://')[1].split(':')[0]
        return {'url': 'https://' + hostname, 'host': public.split('://')[1],
                'address': self._addresses['web'], 'certificates': str(self._certificates),
                'initializer': self.getContainer('initialize').getHostname(),
                'email': 'admin@company.com', 'api_key': client['client_secret'].encode().hex()[:32]}

    def install(self):
        root = Path(self._name) / 'config'
        root.mkdir(parents=True)
        (root / 'initialize.py').write_text(Path(__file__).with_name('initialize.py').read_text())
        (root / 'company.json').write_text(json.dumps(self._configuration, indent=2))
        secret_path = root / 'secrets'
        secret_path.mkdir()
        state = company.state_directory(self._name, self._state_path,
                                        ('database', 'data', 'queue', 'redis', 'certificates'))
        self._certificates = state / 'certificates'
        saved = state / 'secrets.json'
        values = json.loads(saved.read_text()) if saved.exists() else {
            name: secrets.token_hex(32) for name in ('postgres_password', 'rabbitmq_password',
                'redis_password', 'memcached_password', 'secret_key', 'email_password')}
        saved.write_text(json.dumps(values))
        saved.chmod(0o600)
        for name, value in values.items():
            (secret_path / ('zulip__' + name)).write_text(value)
            (secret_path / ('zulip__' + name)).chmod(0o600)
        environment = {
            'SETTING_EXTERNAL_HOST': self._public_url.split('://')[1],
            'SETTING_ZULIP_ADMINISTRATOR': 'admin@company.com',
            'SETTING_REMOTE_POSTGRES_HOST': self._addresses['database'],
            'SETTING_MEMCACHED_LOCATION': self._addresses['cache'] + ':11211',
            'SETTING_RABBITMQ_HOST': self._addresses['queue'],
            'SETTING_REDIS_HOST': self._addresses['redis'],
            'SETTING_EMAIL_BACKEND': 'django.core.mail.backends.console.EmailBackend',
            'CONFIG_http_proxy__allow_addresses': self._identity.getInternalNetworks()[0]['ip_addresses'][0],
            'ZULIP_AUTH_BACKENDS': 'EmailAuthBackend,GenericOpenIdConnectBackend',
            'AUTO_BACKUP_ENABLED': 'False', 'CERTIFICATES': 'self-signed',
            'DIRECTORY_API_KEY': self._api_key,
            'SETTING_SOCIAL_AUTH_OIDC_ENABLED_IDPS': repr({'company': {
                'oidc_url': self._connection['internal_issuer'], 'display_name': 'Company',
                'client_id': self._connection['client_id'], 'secret': self._connection['client_secret'],
                'auto_signup': True, 'enable_external_auth_id_auth': True,
            }}),
        }
        completed = {self.getContainer('initialize').getHostname(): {'condition': 'service_completed_successfully'}}
        for role, container in self._containers.items():
            value = {'restart': 'no' if role == 'initialize' else 'unless-stopped'}
            if self._resolver:
                value['dns'] = [self._resolver]
            script = '#!/bin/sh\nexec "$@"\n'
            if role == 'database':
                value.update(image='handsonsecurity/emuvista-workchat-database:1.0',
                             environment={'POSTGRES_DB': 'zulip', 'POSTGRES_USER': 'zulip',
                                          'POSTGRES_PASSWORD': values['postgres_password']},
                             command=['docker-entrypoint.sh', 'postgres'],
                             volumes=[f'{state / "database"}:/var/lib/postgresql/data'],
                             healthcheck={'test': ['CMD', 'pg_isready', '-U', 'zulip'],
                                          'interval': '5s', 'timeout': '5s', 'retries': 60})
            elif role == 'queue':
                value.update(image='rabbitmq:4.2',
                             environment={'RABBITMQ_DEFAULT_USER': 'zulip',
                                          'RABBITMQ_DEFAULT_PASS': values['rabbitmq_password']},
                             command=['docker-entrypoint.sh', 'rabbitmq-server'],
                             volumes=[f'{state / "queue"}:/var/lib/rabbitmq'],
                             healthcheck={'test': ['CMD', 'rabbitmq-diagnostics', '-q', 'ping'],
                                          'interval': '10s', 'timeout': '10s', 'retries': 60})
            elif role == 'redis':
                value.update(image='redis@sha256:de1068af6f552240dfab67bcc9bfef99bfc60f776bb4580ef077ea4c8c97e848',
                             command=['docker-entrypoint.sh', 'redis-server',
                             '--requirepass', values['redis_password']], volumes=[f'{state / "redis"}:/data'])
            elif role == 'cache':
                value.update(image='handsonsecurity/emuvista-workchat-cache:1.0',
                             environment={'CACHE_PASSWORD': values['memcached_password']},
                             command=['/usr/local/bin/cache-start'])
            else:
                value.update(image='ghcr.io/zulip/zulip-server:13.2-0', environment=environment,
                             volumes=[f'{state / "data"}:/data',
                                      f'./{self._name}/config:/chat-config:ro',
                                      f'./{self._name}/config/secrets:/run/secrets:ro'],
                             ulimits={'nofile': {'soft': 1000000, 'hard': 1048576}})
                if role == 'initialize':
                    value['volumes'].append(f'{self._certificates}:/chat-certificates')
                    value['command'] = ['bash', '-ec',
                        '/sbin/entrypoint.sh app:init; '
                        'cat /etc/ssl/certs/ca-certificates.crt /data/certs/self-signed/zulip.combined-chain.crt '
                        '> /chat-certificates/ca.pem; chmod 644 /chat-certificates/ca.pem; '
                        '/sbin/entrypoint.sh app:managepy shell < /chat-config/initialize.py']
                    value['depends_on'] = {self.getContainer(name).getHostname(): {
                        'condition': 'service_healthy' if name in ('database', 'queue') else 'service_started'}
                        for name in ('database', 'queue', 'redis', 'cache')}
                    value['depends_on'][self._identity.getContainer('initialize').getHostname()] = {
                        'condition': 'service_completed_successfully'}
                else:
                    value['command'] = ['/sbin/entrypoint.sh', 'app:run']
                    value['depends_on'] = completed
                    value['healthcheck'] = {'test': ['CMD', 'curl', '-kfsS', '-H',
                                                    'Host: ' + self._public_url.split('://')[1],
                                                    'https://127.0.0.1/health'],
                                            'interval': '10s', 'timeout': '10s', 'retries': 60}
                    if self._host_port:
                        value['ports'] = [f'127.0.0.1:{self._host_port}:443']
            company.prepare_container(container, value, script)
        return super().install()
