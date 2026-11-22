"""A shared identity provider for company applications."""

import json
from pathlib import Path
import secrets
import tempfile

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from bundles import urls

ADMIN_PASSWORD = 'IdentityAdminDemo123!'
DATABASE_PASSWORD = 'IdentityDatabaseDemo123!'
DEFAULT_IMAGES = {
    'application': 'handsonsecurity/emuvista-identity-server:1.0',
    'database': 'postgres:15',
    'directory': 'handsonsecurity/emuvista-identity-directory:1.0',
}


class IdentityBundle(ContainerBundle):
    """Provide one employee directory and native OIDC/SAML clients."""

    def __init__(self, emulator=None, name='identity', resolver=None, images=None):
        super().__init__(emulator=emulator)
        self._name = name
        self._resolver = resolver
        self._images = {**DEFAULT_IMAGES, **(images or {})}
        self._containers = {role: PreparedContainer(name=name + '-' + role, emulator=emulator)
                            for role in ('server', 'initialize', 'directory', 'database', 'ldap')}
        self._hostname = 'login.company.com'
        self._host_port = None
        self._configuration = {}
        self._clients = {}
        self._sources = {}
        self._consumers = {}
        self._state_path = None
        self._addresses = {}
        self._configured = False

    def setHostname(self, hostname):
        self._hostname = urls.hostname(hostname)
        return self

    def enableHostAccess(self, port=8085):
        self._host_port = port
        return self

    def setInitialConfiguration(self, configuration):
        self._configuration = json.loads(Path(configuration).read_text()) if isinstance(
            configuration, (str, Path)) else configuration
        return self

    def setSavePath(self, path):
        self._state_path = Path(path).expanduser().resolve()
        return self

    def getURL(self):
        return 'http://' + self._hostname

    def getPublicURL(self):
        return f'http://localhost:{self._host_port}' if self._host_port else self.getURL()

    def getDirectoryConnection(self):
        return {'host': str(self.getInternalNetworks()[1]['ip_addresses'][1]), 'port': 389,
                'base_dn': 'dc=company,dc=com', 'bind_dn': 'cn=admin,dc=company,dc=com',
                'password': 'DirectoryAdminDemo123!'}

    def registerClient(self, name, redirects):
        """Record a native OIDC client; installation writes the final client list."""
        if name not in self._clients:
            saved = self._state_path / 'clients.json' if self._state_path else None
            previous = json.loads(saved.read_text()) if saved and saved.exists() else {}
            self._clients[name] = {'secret': previous.get(name, {}).get('secret', secrets.token_urlsafe(32))}
        self._clients[name]['redirects'] = redirects
        internal = self.getURL() + '/realms/company'
        public = self.getPublicURL() + '/realms/company'
        return {'client_id': name, 'client_secret': self._clients[name]['secret'],
                'issuer': public, 'internal_issuer': internal,
                'authorize_url': public + '/protocol/openid-connect/auth',
                'token_url': internal + '/protocol/openid-connect/token',
                'userinfo_url': internal + '/protocol/openid-connect/userinfo',
                'jwks_url': internal + '/protocol/openid-connect/certs',
                'discovery_url': internal + '/.well-known/openid-configuration'}

    def registerEmployeeSource(self, name, source, configuration):
        self._sources[name] = {'source': str(source), 'configuration': configuration}

    def registerSAMLClient(self, name, entity_id, redirects):
        connection = self.registerClient(name, redirects)
        self._clients[name].update(protocol='saml', entity_id=entity_id)
        return {**connection, 'entity_id': self.getPublicURL() + '/realms/company',
                'sso_url': self.getPublicURL() + '/realms/company/protocol/saml',
                'metadata_url': self.getURL() + '/realms/company/protocol/saml/descriptor'}

    def registerEmployeeConsumer(self, name, source, configuration):
        self._consumers[name] = {'source': str(source), 'configuration': configuration}

    def configure(self):
        if self._configured:
            return
        super().configure()
        for network, roles in zip(self.getInternalNetworks(),
                                  (('server', 'initialize', 'directory'), ('database', 'ldap'))):
            for role, address in zip(roles, network['ip_addresses']):
                container = self.getContainer(role)
                container.joinInternalNetwork(network['asn'], network['network_name'],
                                              address, container.getHostname(), network['default_route'])
                self._addresses[role] = str(address)
        self._configured = True

    def install(self):
        root = Path(self._name) / 'config'
        root.mkdir(parents=True)
        for filename in ('initialize.py', 'directory.py', 'ldap_directory.py', 'ldap_initialize.py'):
            (root / filename).write_text(Path(__file__).with_name(filename).read_text())
        sources = {}
        consumers = {'employee-directory': {'module': 'ldap_directory.py',
                                             'configuration': self.getDirectoryConnection()}}
        for collection, output in ((self._sources, sources), (self._consumers, consumers)):
            for name, provider in collection.items():
                filename = name + '-' + Path(provider['source']).name
                (root / filename).write_text(Path(provider['source']).read_text())
                output[name] = {'module': filename, 'configuration': provider['configuration']}
        state = self._state_path or Path(tempfile.mkdtemp(prefix='emuvista-identity-'))
        state.mkdir(parents=True, exist_ok=True)
        for directory in ('database', 'directory', 'ldap-config', 'ldap-data'):
            (state / directory).mkdir(exist_ok=True)
        (state / 'clients.json').write_text(json.dumps(self._clients, indent=2))
        (state / 'clients.json').chmod(0o600)
        data = {**self._configuration, 'clients': self._clients, 'ldap': self.getDirectoryConnection(),
                'sources': sources, 'consumers': consumers}
        (root / 'identity.json').write_text(json.dumps(data, indent=2))
        (root / 'identity.json').chmod(0o600)
        environment = {
            'IDENTITY_URL': 'http://' + self._addresses['server'], 'IDENTITY_ADMIN': 'admin',
            'IDENTITY_PASSWORD': ADMIN_PASSWORD,
        }
        initialized = {self.getContainer('initialize').getHostname(): {
            'condition': 'service_completed_successfully'}}
        for role, container in self._containers.items():
            value = {'image': self._images['database'] if role == 'database' else self._images['application'],
                     'restart': 'no' if role == 'initialize' else 'unless-stopped',
                     'environment': dict(environment),
                     'volumes': [f'./{self._name}/config:/identity-config:ro']}
            if self._resolver:
                value['dns'] = [self._resolver]
            if role == 'ldap':
                value['image'] = self._images['directory']
                value['command'] = ['/usr/local/bin/directory-start']
                value['volumes'] += [f'{state / "ldap-config"}:/etc/ldap/slapd.d',
                                     f'{state / "ldap-data"}:/var/lib/ldap']
                value['healthcheck'] = {
                    'test': ['CMD-SHELL', 'test -f /var/lib/ldap/.company-initialized && ldapwhoami -x -H ldap://127.0.0.1 >/dev/null'],
                    'interval': '5s', 'timeout': '5s', 'retries': 60,
                }
            elif role == 'database':
                value['environment'] = {'POSTGRES_DB': 'identity', 'POSTGRES_USER': 'identity',
                                        'POSTGRES_PASSWORD': DATABASE_PASSWORD}
                value['command'] = ['docker-entrypoint.sh', 'postgres']
                value['volumes'] = [f'{state / "database"}:/var/lib/postgresql/data']
                value['healthcheck'] = {'test': ['CMD', 'pg_isready', '-U', 'identity'],
                                        'interval': '5s', 'timeout': '5s', 'retries': 60}
            elif role == 'server':
                value['environment'].update({
                    'KC_BOOTSTRAP_ADMIN_USERNAME': 'admin',
                    'KC_BOOTSTRAP_ADMIN_PASSWORD': ADMIN_PASSWORD,
                    'KC_DB': 'postgres',
                    'KC_DB_URL': f'jdbc:postgresql://{self._addresses["database"]}:5432/identity',
                    'KC_DB_USERNAME': 'identity', 'KC_DB_PASSWORD': DATABASE_PASSWORD,
                    'KC_HOSTNAME': self.getPublicURL(),
                    'KC_HOSTNAME_BACKCHANNEL_DYNAMIC': 'true',
                    'KC_HTTP_ENABLED': 'true', 'KC_HTTP_HOST': '0.0.0.0', 'KC_HTTP_PORT': '80',
                    'KC_HEALTH_ENABLED': 'true',
                })
                value['command'] = ['/opt/keycloak/bin/kc.sh', 'start-dev']
                value['depends_on'] = {self.getContainer('database').getHostname(): {'condition': 'service_healthy'}}
                value['healthcheck'] = {
                    'test': ['CMD', 'python3', '-c', 'import urllib.request; urllib.request.urlopen("http://127.0.0.1/realms/master/.well-known/openid-configuration", timeout=5).read()'],
                    'interval': '5s', 'timeout': '10s', 'retries': 60,
                }
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:80']
            else:
                value['command'] = ['python3', '/identity-config/' + ('initialize.py' if role == 'initialize' else 'directory.py')]
                value['depends_on'] = {self.getContainer('server').getHostname(): {'condition': 'service_healthy'}} if role == 'initialize' else initialized
                value['volumes'].append(f'{state / "directory"}:/identity-state')
                if role == 'directory':
                    value['image'] = self._images['directory']
                    value['depends_on'] = {**initialized, self.getContainer('ldap').getHostname(): {'condition': 'service_healthy'}}
            container.setFile('/application-start.sh', '#!/bin/sh\nexec "$@"\n')
            container.setEntrypointWrapper('/application-start.sh', [])
            container.updateServiceConfig(value)
        return super().install()
