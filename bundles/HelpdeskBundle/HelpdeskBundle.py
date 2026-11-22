"""A native helpdesk backend with shared company identities."""

import json
from pathlib import Path

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from bundles import company, urls
from bundles.IdentityBundle.gateway import apache_configuration


class HelpdeskBundle(ContainerBundle):

    def __init__(self, emulator=None, name='helpdesk', resolver=None):
        super().__init__(emulator=emulator)
        self._name, self._resolver = name, resolver
        self._containers = {role: PreparedContainer(name=name + '-' + role, emulator=emulator)
                            for role in ('gateway', 'web', 'initialize', 'database')}
        self._hostname = 'helpdesk.company.com'
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

    def enableHostAccess(self, port=8089):
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
        self._addresses = company.assign_networks(self, ('gateway', 'web', 'initialize'), ('database',))
        self._public_url = f'http://localhost:{self._host_port}' if self._host_port else self.getURL()
        self._connection = self._identity.registerClient(self._name, [
            self._public_url + '/sso/callback', self.getURL() + '/sso/callback'])
        self._identity.registerEmployeeConsumer(self._name, Path(__file__).with_name('identity.py'), {
            'url': f'http://{self._addresses["web"]}', 'user': 'glpi',
            'password': 'HelpdeskAdminDemo123!', 'app_token': self._connection['client_secret'],
        })

    def install(self):
        root = Path(self._name) / 'config'
        root.mkdir(parents=True)
        (root / 'initialize.php').write_text(Path(__file__).with_name('initialize.php').read_text())
        (root / 'company.json').write_text(json.dumps(self._configuration, indent=2))
        (root / 'gateway.conf').write_text(apache_configuration(
            self._connection, f'http://{self._addresses["web"]}', self._public_url, self._name + '_sso'))
        state = company.state_directory(self._name, self._state_path, ('database', 'data'))
        environment = {'GLPI_DB_HOST': self._addresses['database'], 'GLPI_DB_PORT': '3306',
                       'GLPI_DB_NAME': 'helpdesk', 'GLPI_DB_USER': 'helpdesk',
                       'GLPI_DB_PASSWORD': 'HelpdeskDatabaseDemo123!',
                       'GLPI_SKIP_AUTOINSTALL': 'false',
                       'DIRECTORY_APP_TOKEN': self._connection['client_secret']}
        initialized = {self.getContainer('initialize').getHostname(): {'condition': 'service_completed_successfully'}}
        for role, container in self._containers.items():
            value = {'restart': 'no' if role == 'initialize' else 'unless-stopped'}
            if self._resolver:
                value['dns'] = [self._resolver]
            if role == 'database':
                value.update(image='mariadb:10.6.22', command=['docker-entrypoint.sh', 'mariadbd'],
                             environment={'MARIADB_DATABASE': 'helpdesk', 'MARIADB_USER': 'helpdesk',
                                          'MARIADB_PASSWORD': environment['GLPI_DB_PASSWORD'],
                                          'MARIADB_ROOT_PASSWORD': 'HelpdeskRootDemo123!'},
                             volumes=[f'{state / "database"}:/var/lib/mysql'],
                             healthcheck={'test': ['CMD', 'healthcheck.sh', '--connect', '--innodb_initialized'],
                                          'interval': '5s', 'timeout': '5s', 'retries': 60})
                company.prepare_container(container, value)
            elif role == 'gateway':
                value.update(image='handsonsecurity/emuvista-auth-gateway:1.0',
                             command=['apachectl', '-D', 'FOREGROUND'],
                             volumes=[f'./{self._name}/config/gateway.conf:/etc/apache2/sites-available/000-default.conf:ro'],
                             depends_on={**initialized, self._identity.getContainer('initialize').getHostname(): {
                                 'condition': 'service_completed_successfully'}})
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:80']
                company.prepare_container(container, value)
            else:
                value.update(image='handsonsecurity/emuvista-helpdesk-app:1.0',
                             working_dir='/var/www/glpi', environment=environment,
                             volumes=[f'{state / "data"}:/var/glpi', f'./{self._name}/config:/helpdesk-config:ro'])
                if role == 'web':
                    value['command'] = ['/opt/glpi/entrypoint.sh', '/usr/bin/supervisord', '-c', '/etc/supervisor/supervisord.conf']
                    value['depends_on'] = {self.getContainer('database').getHostname(): {'condition': 'service_healthy'}}
                    value['healthcheck'] = {'test': ['CMD', 'curl', '-fsS', 'http://127.0.0.1/front/login.php'],
                                            'interval': '10s', 'timeout': '10s', 'retries': 60}
                    container.setFile('/etc/apache2/conf-enabled/company-sso.conf',
                                      'SetEnvIfExpr "req(\'X-Company-SSO\') == \'' + self._connection['client_secret']
                                      + '\' && req(\'Remote-User\') =~ m#^([A-Za-z0-9_.-]+)$#" COMPANY_AUTH_USER=$1\n'
                                      'RequestHeader unset Remote-User env=!COMPANY_AUTH_USER\n')
                else:
                    value['command'] = ['php', '/helpdesk-config/initialize.php']
                    value['depends_on'] = {self.getContainer('web').getHostname(): {'condition': 'service_healthy'}}
                script = ('#!/bin/sh\nset -eu\nchown -R www-data:www-data /var/glpi\n'
                          'chown www-data:www-data /proc/self/fd/1 /proc/self/fd/2\n'
                          'exec runuser -u www-data -- "$@"\n')
                company.prepare_container(container, value, script)
        return super().install()
