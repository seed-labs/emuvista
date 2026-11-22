"""A company knowledge base with native SAML authentication."""

import base64
import json
from pathlib import Path
import secrets

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from bundles import company, urls


class KnowledgeBundle(ContainerBundle):

    def __init__(self, emulator=None, name='knowledge', resolver=None):
        super().__init__(emulator=emulator)
        self._name, self._resolver = name, resolver
        self._containers = {role: PreparedContainer(name=name + '-' + role, emulator=emulator)
                            for role in ('web', 'initialize', 'database')}
        self._hostname = 'knowledge.company.com'
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

    def enableHostAccess(self, port=8088):
        self._host_port = port
        return self

    def setSavePath(self, path):
        self._state_path = Path(path).expanduser().resolve()
        return self

    def connectIdentity(self, identity):
        self._identity = identity
        return self

    def getURL(self):
        return 'http://' + self._hostname

    def configure(self):
        super().configure()
        self._addresses = company.assign_networks(self, ('web', 'initialize'), ('database',))
        self._public_url = f'http://localhost:{self._host_port}' if self._host_port else self.getURL()
        self._connection = self._identity.registerSAMLClient(
            self._name, self._public_url + '/saml2/metadata', [origin + path
                for origin in (self._public_url, self.getURL())
                for path in ('/saml2/acs', '/saml2/sls')])
        self._identity.registerEmployeeConsumer(self._name, Path(__file__).with_name('identity.py'),
                                                {'url': self.getURL(), 'token_id': 'company-directory',
                                                 'token_secret': self._connection['client_secret']})

    def install(self):
        root = Path(self._name) / 'config'
        root.mkdir(parents=True)
        (root / 'initialize.php').write_text(Path(__file__).with_name('initialize.php').read_text())
        (root / 'company.json').write_text(json.dumps(self._configuration, indent=2))
        state = company.state_directory(self._name, self._state_path, ('database', 'uploads', 'storage', 'keys'))
        key = state / 'app-key'
        if not key.exists():
            key.write_text('base64:' + base64.b64encode(secrets.token_bytes(32)).decode())
        environment = {
            'APP_URL': self._public_url, 'APP_KEY': key.read_text(), 'APP_ENV': 'production',
            'DB_HOST': self._addresses['database'], 'DB_DATABASE': 'knowledge',
            'DB_USERNAME': 'knowledge', 'DB_PASSWORD': 'KnowledgeDatabaseDemo123!',
            'AUTH_METHOD': 'saml2', 'AUTH_AUTO_INITIATE': 'true',
            'SAML2_NAME': 'Company', 'SAML2_IDP_ENTITYID': self._connection['entity_id'],
            'SAML2_IDP_SSO': self._connection['sso_url'],
            'SAML2_IDP_SLO': self._connection['sso_url'],
            'SAML2_EXTERNAL_ID_ATTRIBUTE': 'employee_id',
            'SAML2_EMAIL_ATTRIBUTE': 'email',
            'SAML2_DISPLAY_NAME_ATTRIBUTES': 'firstName|lastName',
            'IDENTITY_METADATA': self._connection['metadata_url'],
            'DIRECTORY_TOKEN_SECRET': self._connection['client_secret'],
        }
        completed = {self.getContainer('initialize').getHostname(): {'condition': 'service_completed_successfully'}}
        volumes = [f'./{self._name}/config:/knowledge-config:ro',
                   f'{state / "uploads"}:/var/www/bookstack/public/uploads',
                   f'{state / "storage"}:/var/www/bookstack/storage/uploads',
                   f'{state / "keys"}:/knowledge-keys']
        for role, container in self._containers.items():
            value = {'restart': 'no' if role == 'initialize' else 'unless-stopped'}
            if self._resolver:
                value['dns'] = [self._resolver]
            if role == 'database':
                value.update(image='mariadb:10.6.22', command=['docker-entrypoint.sh', 'mariadbd'],
                             environment={'MARIADB_DATABASE': 'knowledge', 'MARIADB_USER': 'knowledge',
                                          'MARIADB_PASSWORD': environment['DB_PASSWORD'],
                                          'MARIADB_ROOT_PASSWORD': 'KnowledgeRootDemo123!'},
                             volumes=[f'{state / "database"}:/var/lib/mysql'],
                             healthcheck={'test': ['CMD', 'healthcheck.sh', '--connect', '--innodb_initialized'],
                                          'interval': '5s', 'timeout': '5s', 'retries': 60})
                company.prepare_container(container, value)
                continue
            value.update(image='handsonsecurity/emuvista-knowledge-app:1.0', environment=environment, volumes=volumes,
                         working_dir='/var/www/bookstack')
            if role == 'initialize':
                value['command'] = ['sh', '-ec', 'php artisan migrate --force; php /knowledge-config/initialize.php']
                value['depends_on'] = {
                    self.getContainer('database').getHostname(): {'condition': 'service_healthy'},
                    self._identity.getContainer('initialize').getHostname(): {'condition': 'service_completed_successfully'},
                }
                script = '#!/bin/sh\nset -eu\nchown -R www-data:www-data /var/www/bookstack/public/uploads /var/www/bookstack/storage/uploads /knowledge-keys\nexec runuser -u www-data -- "$@"\n'
            else:
                value['command'] = ['/bin/docker-entrypoint.sh']
                value['depends_on'] = completed
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:80']
                script = ('#!/bin/sh\nset -eu\n'
                          'export SAML2_IDP_x509="$(cat /knowledge-keys/certificate.pem)"\n'
                          'exec "$@"\n')
            company.prepare_container(container, value, script)
        return super().install()
