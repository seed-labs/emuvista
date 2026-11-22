"""Native project management with a standard OIDC authentication gateway."""

import json
from pathlib import Path
import secrets

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from bundles import company, urls
from bundles.IdentityBundle.gateway import apache_configuration


class ProjectBundle(ContainerBundle):

    def __init__(self, emulator=None, name='projects', resolver=None):
        super().__init__(emulator=emulator)
        self._name, self._resolver = name, resolver
        self._containers = {role: PreparedContainer(name=name + '-' + role, emulator=emulator)
                            for role in ('gateway', 'web', 'worker', 'initialize', 'database')}
        self._hostname = 'projects.company.com'
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

    def enableHostAccess(self, port=8087):
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
        self._addresses = company.assign_networks(self, ('gateway', 'web', 'worker', 'initialize'), ('database',))
        self._public_url = f'http://localhost:{self._host_port}' if self._host_port else self.getURL()
        self._connection = self._identity.registerClient(self._name, [
            self._public_url + '/sso/callback', self.getURL() + '/sso/callback'])
        self._api_token = 'opapi-' + self._connection['client_secret'].encode().hex()[:64]
        self._identity.registerEmployeeConsumer(self._name, Path(__file__).with_name('identity.py'),
                                                {'url': f'http://{self._addresses["web"]}:8080',
                                                 'host': self._public_url.split('://')[1],
                                                 'token': self._api_token, 'auth_source': 'Company employee directory'})

    def install(self):
        root = Path(self._name) / 'config'
        root.mkdir(parents=True)
        (root / 'initialize.rb').write_text(Path(__file__).with_name('initialize.rb').read_text())
        (root / 'company.json').write_text(json.dumps({**self._configuration,
            'ldap': self._identity.getDirectoryConnection()}, indent=2))
        (root / 'gateway.conf').write_text(apache_configuration(
            self._connection, f'http://{self._addresses["web"]}:8080', self._public_url,
            self._name + '_sso', self._connection['client_secret']))
        state = company.state_directory(self._name, self._state_path, ('database', 'assets', 'cache'))
        key = state / 'secret-key'
        if not key.exists():
            key.write_text(secrets.token_hex(64))
        environment = {
            'DATABASE_URL': f'postgres://projects:ProjectDatabaseDemo123!@{self._addresses["database"]}:5432/projects',
            'SECRET_KEY_BASE': key.read_text(), 'RAILS_ENV': 'production',
            'OPENPROJECT_HOST__NAME': self._public_url.split('://')[1],
            'OPENPROJECT_ADDITIONAL__HOST__NAMES': self._hostname,
            'OPENPROJECT_HTTPS': 'false', 'OPENPROJECT_HSTS': 'false',
            'OPENPROJECT_RAILS__CACHE__STORE': 'file_store',
            'OPENPROJECT_AUTH__SOURCE__SSO_HEADER': 'X-Authenticated-User',
            'OPENPROJECT_AUTH__SOURCE__SSO_SECRET': self._connection['client_secret'],
            'OPENPROJECT_AUTH__SOURCE__SSO_OPTIONAL': 'true',
            'OPENPROJECT_SEED__DEMO__DATA': 'false',
            'OPENPROJECT_SEED__ADMIN__USER__PASSWORD': 'ProjectAdminDemo123!',
            'DIRECTORY_API_TOKEN': self._api_token,
        }
        completed = {self.getContainer('initialize').getHostname(): {'condition': 'service_completed_successfully'}}
        for role, container in self._containers.items():
            value = {'restart': 'no' if role == 'initialize' else 'unless-stopped'}
            if self._resolver:
                value['dns'] = [self._resolver]
            if role == 'database':
                value.update(image='postgres:17-bookworm', command=['docker-entrypoint.sh', 'postgres'],
                             environment={'POSTGRES_DB': 'projects', 'POSTGRES_USER': 'projects',
                                          'POSTGRES_PASSWORD': 'ProjectDatabaseDemo123!'},
                             volumes=[f'{state / "database"}:/var/lib/postgresql/data'],
                             healthcheck={'test': ['CMD', 'pg_isready', '-U', 'projects'],
                                          'interval': '5s', 'timeout': '5s', 'retries': 60})
                company.prepare_container(container, value)
            elif role == 'gateway':
                value.update(image='handsonsecurity/emuvista-auth-gateway:1.0',
                             command=['apachectl', '-D', 'FOREGROUND'], depends_on=completed,
                             volumes=[f'./{self._name}/config/gateway.conf:/etc/apache2/sites-available/000-default.conf:ro'])
                value['depends_on'] = {**completed, self._identity.getContainer('initialize').getHostname(): {
                    'condition': 'service_completed_successfully'},
                    self.getContainer('web').getHostname(): {'condition': 'service_healthy'}}
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:80']
                company.prepare_container(container, value)
            else:
                value.update(image='handsonsecurity/emuvista-project-app:1.0', environment=environment,
                             working_dir='/app', volumes=[f'{state / "assets"}:/var/openproject/assets',
                                                         f'{state / "cache"}:/app/tmp/cache',
                                                         f'./{self._name}/config:/project-config:ro'])
                if role == 'initialize':
                    value['command'] = ['bash', '-ec', './docker/prod/seeder; bundle exec rails runner /project-config/initialize.rb']
                    value['depends_on'] = {self.getContainer('database').getHostname(): {'condition': 'service_healthy'}}
                    value['depends_on'][self._identity.getContainer('ldap').getHostname()] = {'condition': 'service_healthy'}
                    script = '#!/bin/sh\nset -eu\nchown -R app:app /var/openproject/assets /app/tmp/cache\nexec runuser -u app -- ./docker/prod/entrypoint-slim.sh "$@"\n'
                else:
                    value['command'] = ['./docker/prod/' + ('web' if role == 'web' else 'worker')]
                    value['depends_on'] = completed
                    if role == 'web':
                        value['healthcheck'] = {
                            'test': ['CMD', 'curl', '-fsS', '-H', 'Host: ' + self._public_url.split('://')[1],
                                     'http://127.0.0.1:8080/health_checks/default'],
                            'interval': '10s', 'timeout': '10s', 'retries': 60,
                        }
                    script = '#!/bin/sh\nexec runuser -u app -- ./docker/prod/entrypoint-slim.sh "$@"\n'
                company.prepare_container(container, value, script)
        return super().install()
