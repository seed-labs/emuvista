"""A shared ERPNext and Frappe HR site using upstream container images."""

import json
from pathlib import Path
import tempfile

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from bundles import urls

APP_ROLES = ('frontend', 'backend', 'websocket', 'worker', 'scheduler', 'initialize')
DATA_ROLES = ('database', 'redis')
DEFAULT_IMAGES = {
    'application': 'handsonsecurity/emuvista-erp-app:1.0',
    'database': 'mariadb:10.6.22',
    'redis': 'redis@sha256:de1068af6f552240dfab67bcc9bfef99bfc60f776bb4580ef077ea4c8c97e848',
}
ADMIN_PASSWORD = 'ERPAdminDemo123!'
DATABASE_PASSWORD = 'ERPDatabaseDemo123!'
BENCH = '/home/frappe/frappe-bench'


class ERPBundle(ContainerBundle):
    """One employee directory, login system, and database for both applications."""

    def __init__(self, emulator=None, name='erp', resolver=None, images=None):
        super().__init__(emulator=emulator)
        self._name = name
        self._resolver = resolver
        self._images = {**DEFAULT_IMAGES, **(images or {})}
        self._containers = {role: PreparedContainer(name=name + '-' + role, emulator=emulator)
                            for role in (*APP_ROLES, *DATA_ROLES)}
        self._required_internal_address_count = len(DATA_ROLES)
        self._hostname = 'erp.company.com'
        self._host_port = None
        self._configuration = None
        self._state_path = None
        self._addresses = {}
        self._configured = False
        self._identity = None
        self._identity_configuration = None
        self._chat = None

    def setHostname(self, hostname):
        self._hostname = urls.hostname(hostname)
        return self

    def setInitialConfiguration(self, configuration):
        self._configuration = json.loads(Path(configuration).read_text()) if isinstance(
            configuration, (str, Path)) else configuration
        return self

    def enableHostAccess(self, port=8082):
        self._host_port = port
        return self

    def setSavePath(self, path):
        self._state_path = Path(path).expanduser().resolve()
        return self

    def getURL(self):
        return 'http://' + self._hostname

    def connectIdentity(self, identity):
        self._identity = identity
        return self

    def connectChat(self, chat):
        self._chat = chat
        return self

    def configure(self):
        if self._configured:
            return
        super().configure()
        networks = self.getInternalNetworks()
        if len(networks) != 2 or self._configuration is None:
            raise ValueError('ERPBundle requires initial configuration, an application network, and a data network')
        for network, roles in zip(networks, (APP_ROLES, DATA_ROLES)):
            if len(network['ip_addresses']) < len(roles):
                raise ValueError('ERPBundle network address pool is too small')
            for role, address in zip(roles, network['ip_addresses']):
                container = self.getContainer(role)
                container.joinInternalNetwork(network['asn'], network['network_name'],
                                              address, container.getHostname(), network['default_route'])
                self._addresses[role] = str(address)
        if self._identity:
            callback = '/api/method/frappe.integrations.oauth2_logins.custom/company'
            public = f'http://localhost:{self._host_port}' if self._host_port else self.getURL()
            self._identity_configuration = self._identity.registerClient(
                self._name, [public + callback, self.getURL() + callback])
            self._identity.registerEmployeeSource(self._name, Path(__file__).with_name('identity.py'),
                                                  {'url': self.getURL(), 'password': ADMIN_PASSWORD})
        self._configured = True

    def install(self):
        config_path = Path(self._name) / 'config'
        config_path.mkdir(parents=True)
        source = Path(__file__).parent
        for filename in ('initialize.sh', 'initialize.py', 'business.py'):
            (config_path / filename).write_text((source / filename).read_text())
        chat = self._chat.getNotificationConnection() if self._chat else None
        configuration = {**self._configuration, 'identity': self._identity_configuration, 'chat': chat}
        (config_path / 'company.json').write_text(json.dumps(configuration, indent=2) + '\n')
        (config_path / 'company.json').chmod(0o644)
        state = self._state_path or Path(tempfile.mkdtemp(prefix='emuvista-erp-'))
        for directory in ('sites', 'database', 'redis'):
            (state / directory).mkdir(parents=True, exist_ok=True)
        site_volume = f'{state / "sites"}:{BENCH}/sites'
        config_volume = f'./{self._name}/config:/opt/emuvista-erp:ro'
        completed = {self.getContainer('initialize').getHostname(): {
            'condition': 'service_completed_successfully'}}
        environment = {
            'ERP_SITE': self._hostname,
            'ERP_ADMIN_PASSWORD': ADMIN_PASSWORD,
            'ERP_DATABASE_PASSWORD': DATABASE_PASSWORD,
            'DB_HOST': self._addresses['database'],
            'REDIS_HOST': self._addresses['redis'],
            'ERP_PUBLIC_URL': f'http://localhost:{self._host_port}' if self._host_port else self.getURL(),
        }
        commands = {
            'frontend': ['nginx-entrypoint.sh'],
            'backend': [BENCH + '/env/bin/gunicorn', '--chdir=' + BENCH + '/sites',
                        '--bind=0.0.0.0:8000', '--workers=2', '--threads=4',
                        '--worker-class=gthread', '--worker-tmp-dir=/dev/shm',
                        '--timeout=120', '--preload', 'frappe.app:application'],
            'websocket': ['node', BENCH + '/apps/frappe/socketio.js'],
            'worker': ['bench', 'worker', '--queue', 'long,default,short'],
            'scheduler': ['bench', 'schedule'],
            'initialize': ['bash', '/opt/emuvista-erp/initialize.sh'],
            'database': ['docker-entrypoint.sh', 'mariadbd', '--character-set-server=utf8mb4',
                         '--collation-server=utf8mb4_unicode_ci', '--skip-character-set-client-handshake'],
            'redis': ['docker-entrypoint.sh', 'redis-server', '--appendonly', 'yes'],
        }
        healthcheck = lambda port: {
            'test': ['CMD', BENCH + '/env/bin/python', '-c',
                     'import urllib.request; '
                     f'urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:{port}/api/method/ping", '
                     f'headers={{"Host": "{self._hostname}"}}), timeout=5).read()'],
            'interval': '10s', 'timeout': '10s', 'retries': 30,
        }
        for role, container in self._containers.items():
            value = {
                'image': self._images.get(role, self._images['application']),
                'command': commands[role],
                'restart': 'no' if role == 'initialize' else 'unless-stopped',
                'environment': dict(environment),
            }
            if self._resolver:
                value['dns'] = [self._resolver]
            if role in APP_ROLES:
                value['working_dir'] = BENCH
                value['volumes'] = [site_volume, config_volume]
                value['depends_on'] = completed
                if chat:
                    value['volumes'].append(f'{chat["certificates"]}:/chat-certificates:ro')
                    value['environment']['REQUESTS_CA_BUNDLE'] = '/chat-certificates/ca.pem'
                    value['extra_hosts'] = [chat['url'].split('://')[1] + ':' + chat['address']]
                container.setFile('/application-start.sh',
                                  '#!/bin/sh\nexec runuser -u frappe -- /usr/local/bin/entrypoint.sh "$@"\n')
            else:
                value['volumes'] = [f'{state / role}:/var/lib/mysql' if role == 'database'
                                    else f'{state / role}:/data']
                container.setFile('/application-start.sh', '#!/bin/sh\nexec "$@"\n')
            if role == 'database':
                value['environment'] = {'MARIADB_ROOT_PASSWORD': DATABASE_PASSWORD,
                                        'MARIADB_ROOT_HOST': '%'}
                value['healthcheck'] = {'test': ['CMD', 'healthcheck.sh', '--connect', '--innodb_initialized'],
                                        'interval': '5s', 'timeout': '5s', 'retries': 60}
            elif role == 'redis':
                value['healthcheck'] = {'test': ['CMD', 'redis-cli', 'ping'],
                                        'interval': '5s', 'timeout': '5s', 'retries': 60}
            elif role == 'initialize':
                value['depends_on'] = {self.getContainer(name).getHostname(): {
                    'condition': 'service_healthy'} for name in DATA_ROLES}
                if self._identity:
                    value['depends_on'][self._identity.getContainer('initialize').getHostname()] = {
                        'condition': 'service_completed_successfully'}
                if chat:
                    value['depends_on'][chat['initializer']] = {'condition': 'service_completed_successfully'}
                container.setFile('/application-start.sh',
                                  '#!/bin/sh\nset -eu\n'
                                  f'chown -R frappe:0 {BENCH}/sites\n'
                                  'exec runuser -u frappe -- /usr/local/bin/entrypoint.sh "$@"\n')
            elif role == 'frontend':
                container.setFile('/application-start.sh', '#!/bin/sh\nexec /usr/local/bin/entrypoint.sh "$@"\n')
                value['environment'].update({
                    'BACKEND': self._addresses['backend'] + ':8000',
                    'SOCKETIO': self._addresses['websocket'] + ':9000',
                    'FRAPPE_SITE_NAME_HEADER': self._hostname,
                    'NGINX_LISTEN_PORT': '80',
                    'UPSTREAM_REAL_IP_ADDRESS': '127.0.0.1',
                    'UPSTREAM_REAL_IP_HEADER': 'X-Forwarded-For',
                    'UPSTREAM_REAL_IP_RECURSIVE': 'off',
                })
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:80/tcp']
                value['depends_on'] = {**completed, self.getContainer('backend').getHostname(): {
                    'condition': 'service_healthy'}, self.getContainer('websocket').getHostname(): {
                        'condition': 'service_started'}}
                value['healthcheck'] = healthcheck(80)
            elif role == 'backend':
                value['healthcheck'] = healthcheck(8000)
            container.updateServiceConfig(value)
            container.setEntrypointWrapper('/application-start.sh', [])
        return super().install()
