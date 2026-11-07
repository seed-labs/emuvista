"""Independent Mailu containers on rendered SEED networks."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
from ipaddress import IPv4Address
from pathlib import Path

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer

from .templates import INITIALIZE

VERSION = '2024.06.67'
DEFAULT_IMAGES = {role: f'ghcr.io/mailu/{image}:{VERSION}' for role, image in {
    'front': 'nginx', 'admin': 'admin', 'smtp': 'postfix', 'imap': 'dovecot',
    'webmail': 'webmail', 'antispam': 'rspamd', 'initialize': 'admin',
}.items()}
DEFAULT_IMAGES['redis'] = 'redis:7-alpine'
ROLES = ('front', 'admin', 'smtp', 'imap', 'redis', 'webmail', 'antispam', 'initialize')





class EmailBundle(ContainerBundle):
    """Mailu with native SMTP/IMAP, Roundcube and API-driven mailbox setup."""

    @staticmethod
    def getAgentTools():
        """Export service-owned tool source without importing an agent framework."""
        return {'name':'email','source':Path(__file__).parent/'tools'}

    def __init__(self, emulator=None, images=None, name='email', resolver=None):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
            raise ValueError('invalid email bundle name')
        super().__init__(emulator=emulator)
        self._name = name
        self._images = dict(DEFAULT_IMAGES)
        for role, image in (images or {}).items():
            if role not in self._images or not isinstance(image, str) or not image or any(c.isspace() for c in image):
                raise ValueError('invalid email image role or reference')
            self._images[role] = image
        if resolver is None:
            raise ValueError('EmailBundle requires an external DNSSEC-validating resolver')
        self._resolver = str(IPv4Address(resolver))
        self._containers = {r: PreparedContainer(name=name+'-'+r, emulator=self._emulator) for r in ROLES}
        self._required_internal_address_count = len(ROLES)
        self._configuration = None
        self._state_path = None
        self._host_port = None
        self._configured = False
        self._addresses = {}

    def setInitialConfiguration(self, configuration):
        """Supply domains, hostname, administrator and users in JSON or a mapping."""
        if self._configured:
            raise RuntimeError('set email configuration before compilation')
        data = json.loads(Path(configuration).read_text()) if isinstance(configuration, (str, Path)) else json.loads(json.dumps(configuration))
        def domain(value):
            return isinstance(value, str) and len(value) <= 253 and re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*', value)
        if not domain(data.get('hostname')) or not data.get('domains') or not all(domain(d) for d in data['domains']):
            raise ValueError('hostname and domains require lowercase fully qualified DNS names')
        if len(set(data['domains'])) != len(data['domains']):
            raise ValueError('duplicate email domain')
        if not isinstance(data.get('admin'), dict) or not isinstance(data.get('users'), list):
            raise ValueError('email configuration requires admin and users')
        emails = set()
        for user in [data['admin']]+data['users']:
            address = user.get('email', '')
            if (not isinstance(address, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._+-]*@[^@]+', address)
                    or address.rsplit('@', 1)[1] not in data['domains'] or address in emails):
                raise ValueError('users require unique lowercase email addresses in configured domains')
            password = user.get('password')
            if not isinstance(password, str) or len(password) < 8 or any(c in password for c in "\x00\r\n'"):
                raise ValueError('email passwords require at least eight characters and no quotes or newlines')
            if 'quota_bytes' in user and (type(user['quota_bytes']) is not int or user['quota_bytes'] < 0):
                raise ValueError('quota_bytes must be a nonnegative integer')
            if 'change_password_on_login' in user and type(user['change_password_on_login']) is not bool:
                raise ValueError('change_password_on_login must be boolean')
            emails.add(address)
        aliases = set()
        for alias in data.get('aliases', []):
            address, destinations = alias.get('email', ''), alias.get('destination')
            if (not re.fullmatch(r'[a-z0-9][a-z0-9._+-]*@[^@]+', address)
                    or address.rsplit('@', 1)[1] not in data['domains'] or address in emails or address in aliases
                    or not isinstance(destinations, list) or not destinations or any(d not in emails for d in destinations)):
                raise ValueError('aliases require unique configured addresses and existing user destinations')
            aliases.add(address)
        self._configuration = data
        return self

    def setSavePath(self, path):
        if self._configured:
            raise RuntimeError('set email state before compilation')
        self._state_path = Path(path).expanduser().resolve()
        return self

    def enableHostAccess(self, port=8445):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('invalid email browser port')
        self._host_port = port
        return self

    def getAddress(self, role='front'):
        if role not in self._addresses:
            raise RuntimeError('configure EmailBundle before reading component addresses')
        return self._addresses[role]

    def getURL(self):
        return 'https://'+self.getAddress()

    def getImages(self):
        return dict(self._images)

    def configure(self):
        if self._configured:
            return
        if self._configuration is None:
            raise ValueError('EmailBundle requires an explicit initial configuration')
        if self._emulator is None or not self._emulator.rendered():
            raise RuntimeError('Render the emulator before configuring EmailBundle')
        super().configure()
        networks = self.getInternalNetworks()
        if len(networks) != 1:
            raise ValueError('Configure one emulated network with addInternalNetwork()')
        net = networks[0]
        for (role, container), address in zip(self._containers.items(), net['ip_addresses']):
            container.joinInternalNetwork(net['asn'], net['network_name'], address,
                                          container.getHostname(), net['default_route'])
            self._addresses[role] = address
        self._subnet = self._emulator.getLayer('Base').getAutonomousSystem(int(net['asn'])).getNetwork(net['network_name']).getPrefix()
        self._configured = True


    def install(self):
        if not self._configured:
            raise RuntimeError('configure EmailBundle before installation')
        root = Path(self._name)
        cfg = root/'config'
        cfg.mkdir(parents=True, mode=0o700)
        state = self._state_path or Path(tempfile.mkdtemp(prefix='seedemu-email-'))
        if Path.cwd() == state or Path.cwd() in state.parents:
            raise ValueError('email state must be outside the compilation output directory')
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        identity = {'configuration': self._configuration, 'addresses': self._addresses, 'resolver': self._resolver}
        stamp = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        record = state/'deployment.sha256'
        if record.exists() and record.read_text() != stamp:
            raise ValueError('saved email state uses another configuration or network; use a new state directory')
        record.write_text(stamp)
        credentials = state/'credentials.json'
        if credentials.exists():
            keys = json.loads(credentials.read_text())
        else:
            keys = {'secret': secrets.token_hex(24), 'api': secrets.token_hex(24)}
            credentials.write_text(json.dumps(keys)+'\n')
            credentials.chmod(0o600)
        for file in ('cert.pem', 'key.pem'):
            if (state/file).exists():
                shutil.copy2(state/file, cfg/file)
        if not (cfg/'cert.pem').exists():
            subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '365',
                '-keyout', str(cfg/'key.pem'), '-out', str(cfg/'cert.pem'),
                '-subj', '/CN='+self._configuration['hostname'], '-addext',
                f'subjectAltName=DNS:{self._configuration["hostname"]},DNS:localhost,IP:{self.getAddress()},IP:127.0.0.1'],
                check=True, capture_output=True)
        (cfg/'key.pem').chmod(0o600)
        for file in ('cert.pem', 'key.pem'):
            shutil.copy2(cfg/file, state/file)
        admin = self._configuration['admin']
        localpart, domain = admin['email'].split('@')
        env = {'SECRET_KEY': keys['secret'], 'API_TOKEN': keys['api'], 'API': 'true',
            'DOMAIN': domain, 'HOSTNAMES': self._configuration['hostname'], 'POSTMASTER': localpart,
            'SUBNET': str(self._subnet), 'TLS_FLAVOR': 'cert', 'ADMIN': 'true',
            'WEBMAIL': 'roundcube', 'WEBDAV': 'none', 'ANTIVIRUS': 'none', 'ANTISPAM': 'rspamd',
            'SCAN_MACROS': 'false', 'DISABLE_STATISTICS': 'true', 'CPU_COUNT': '2', 'LOG_LEVEL': 'WARNING',
            'WEB_ADMIN': '/admin', 'WEB_WEBMAIL': '/webmail', 'WEBROOT_REDIRECT': '/webmail',
            'SITENAME': 'SEED Mail', 'INITIAL_ADMIN_ACCOUNT': localpart, 'INITIAL_ADMIN_DOMAIN': domain,
            'INITIAL_ADMIN_PW': admin['password'], 'INITIAL_ADMIN_MODE': 'ifmissing', 'FULL_TEXT_SEARCH': 'off',
            'MESSAGE_SIZE_LIMIT': '25000000',
            'PORTS': '25,80,443,143,993,465,587,4190'}
        for role in ('front', 'admin', 'smtp', 'imap', 'redis', 'webmail', 'antispam'):
            env[role.upper()+'_ADDRESS'] = self.getAddress(role)
        (cfg/'initialize.py').write_text(INITIALIZE)
        (cfg/'initial.json').write_text(json.dumps({'configuration': self._configuration,
            'url': f'http://{self.getAddress("admin")}:8080', 'token': keys['api']})+'\n')
        (cfg/'initial.json').chmod(0o600)
        commands = {r: ['/start.py'] for r in self._containers}
        commands['redis'] = ['docker-entrypoint.sh', 'redis-server', '--appendonly', 'yes']
        commands['initialize'] = ['python3', '/mailu-config/initialize.py']
        targets = {'admin': {'data': '/data', 'dkim': '/dkim'}, 'imap': {'mail': '/mail', 'dovecot': '/var/lib/dovecot'},
            'smtp': {'queue': '/queue'}, 'redis': {'redis': '/data'}, 'webmail': {'webmail': '/data'},
            'antispam': {'filter': '/var/lib/rspamd', 'dkim': '/dkim'}, 'initialize': {'initialization': '/mailu-state'}}
        for role, c in self._containers.items():
            value = {'image': self._images[role], 'command': commands[role],
                'cap_add': ['NET_ADMIN'], 'restart': 'on-failure:3' if role == 'initialize' else 'unless-stopped',
                'dns': [self._resolver], 'volumes': [f'./{self._name}/config:/mailu-config:ro'],
                'environment': {k: str(v).replace('$', '$$') for k, v in env.items()},
                'labels': {'org.emuvista.bundle': 'EmailBundle', 'org.emuvista.component': role}}
            if role == 'front':
                value['volumes'].append(f'./{self._name}/config:/certs:ro')
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:443/tcp']
            if role == 'redis':
                value['healthcheck'] = {'test': ['CMD', 'redis-cli', 'ping'], 'interval': '5s', 'timeout': '5s', 'retries': 20}
            if role == 'admin':
                value['depends_on'] = {self.getContainer('redis').getHostname(): {'condition': 'service_healthy'}}
            if role == 'initialize':
                value['depends_on'] = {self.getContainer('admin').getHostname(): {'condition': 'service_healthy'}}
                value['healthcheck'] = {'disable': True}
            for name, target in targets.get(role, {}).items():
                directory = state/name
                directory.mkdir(exist_ok=True, mode=0o755)
                value['volumes'].append(f'{directory}:{target}')
            c.updateServiceConfig(value)
            c.setFile('/application-start.sh', '#!/bin/sh\nexec "$@"\n')
            c.setEntrypointWrapper('/application-start.sh', [])
        (root/'deployment.json').write_text(json.dumps({'addresses': self._addresses, 'resolver': self._resolver,
            'images': self._images, 'state_path': str(state), 'persistent': self._state_path is not None,
            'hostname': self._configuration['hostname'], 'browser': f'https://localhost:{self._host_port}/webmail/' if self._host_port else None}, indent=2)+'\n')
        Path('docker-compose.yml').touch(mode=0o600, exist_ok=True)
        Path('docker-compose.yml').chmod(0o600)
        return super().install()
