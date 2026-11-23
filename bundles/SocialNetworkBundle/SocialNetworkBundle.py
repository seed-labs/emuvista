"""Independent Mastodon development containers on rendered SEED networks."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import string
import tempfile
from ipaddress import IPv4Address
from pathlib import Path

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer
from bundles import urls

from .templates import APPLICATION_START, INITIALIZE, INITIALIZE_SH, SOURCE, gateway_config

# Mastodon's development seed (db/seeds/04_admin.rb) creates this Owner as admin@<hostname>.
DEFAULT_ADMIN = {'username': 'admin', 'password': 'mastodonadmin'}
# Built from the local Mastodon checkout and its .devcontainer by docker_images/social.
MASTODON_IMAGE = 'handsonsecurity/emuvista-mastodon-dev:main'
# The devcontainer's PostgreSQL 14 and Redis 7, as Debian images: SEED's derived
# Dockerfiles install routing tools with apt-get.
DEFAULT_IMAGES = {'gateway': 'nginx:stable-bookworm', 'web': MASTODON_IMAGE, 'streaming': MASTODON_IMAGE,
                  'sidekiq': MASTODON_IMAGE, 'db': 'postgres:14-bookworm', 'redis': 'redis:7-bookworm',
                  'initialize': MASTODON_IMAGE}
ROLES = ('gateway', 'web', 'streaming', 'sidekiq', 'db', 'redis', 'initialize')
MASTODON_ROLES = ('web', 'streaming', 'sidekiq', 'initialize')
USER_FIELDS = {'username', 'email', 'password', 'display_name', 'note', 'role', 'follows', 'posts'}


class SocialNetworkBundle(ContainerBundle):
    """Mastodon's development version with web, streaming, Sidekiq and account setup."""

    def __init__(self, emulator=None, images=None, name='social', resolver=None):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
            raise ValueError('invalid social network bundle name')
        super().__init__(emulator=emulator)
        self._name = name
        self._images = dict(DEFAULT_IMAGES)
        for role, image in (images or {}).items():
            # "mastodon" selects one image for all four Mastodon components.
            roles = MASTODON_ROLES if role == 'mastodon' else (role,)
            if (any(r not in self._images for r in roles) or not isinstance(image, str) or not image
                    or any(c.isspace() for c in image)):
                raise ValueError('invalid social network image role or reference')
            self._images.update(dict.fromkeys(roles, image))
        if resolver is None:
            raise ValueError('SocialNetworkBundle requires an external DNS resolver')
        self._resolver = str(IPv4Address(resolver))
        self._containers = {r: PreparedContainer(
            name=name + '-' + r, emulator=self._emulator) for r in ROLES}
        self._required_internal_address_count = len(ROLES)
        self._configuration = None
        self._hostname = 'social.com'
        self._state_path = None
        self._host_port = None
        self._configured = False
        self._addresses = {}

    def setHostname(self, hostname):
        """Choose Mastodon's LOCAL_DOMAIN, the canonical hostname of emulated clients."""
        if self._configured:
            raise RuntimeError('set the social network hostname before compilation')
        self._hostname = urls.hostname(hostname)
        return self

    def setInitialConfiguration(self, configuration):
        """Supply the site title, registration mode and users; the administrator is built in."""
        if self._configured:
            raise RuntimeError('set social network configuration before compilation')
        data = json.loads(Path(configuration).read_text()) if isinstance(
            configuration, (str, Path)) else json.loads(json.dumps(configuration))
        data.pop('hostname', None)
        if set(data) - {'title', 'registrations', 'users'}:
            raise ValueError('social network configuration supports title, registrations and users')
        title = data.get('title')
        if title is not None and (not isinstance(title, str) or not 1 <= len(title) <= 100 or '\n' in title):
            raise ValueError('title requires 1 to 100 characters on one line')
        if data.get('registrations') not in (None, 'open', 'approved', 'none'):
            raise ValueError('registrations must be open, approved or none')
        if not isinstance(data.get('users'), list):
            raise ValueError('social network configuration requires users')
        usernames, emails = set(), set()
        for user in data['users']:
            if not isinstance(user, dict) or set(user) - USER_FIELDS:
                raise ValueError('users support ' + ', '.join(sorted(USER_FIELDS)))
            username, email, password = user.get('username'), user.get('email'), user.get('password')
            if (not isinstance(username, str) or not re.fullmatch(r'[a-z0-9_]{1,30}', username)
                    or username == DEFAULT_ADMIN['username'] or username in usernames):
                raise ValueError(
                    'users require unique lowercase usernames of 1 to 30 letters, digits or underscores; admin is built in')
            if (not isinstance(email, str) or len(email) > 320 or email in emails
                    or not re.fullmatch(r'[a-z0-9][a-z0-9._+-]*@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*', email)):
                raise ValueError('users require unique lowercase email addresses')
            if not isinstance(password, str) or not 8 <= len(password) <= 72 or any(c in password for c in '\x00\r\n'):
                raise ValueError('passwords require 8 to 72 characters on one line')
            for field, limit in (('display_name', 40), ('note', 500)):
                if field in user and (not isinstance(user[field], str) or len(user[field]) > limit):
                    raise ValueError(f'{field} must be text of at most {limit} characters')
            if user.get('role') not in (None, 'Owner', 'Admin', 'Moderator'):
                raise ValueError('role must be Owner, Admin or Moderator')
            posts = user.get('posts', [])
            if not isinstance(posts, list) or any(not isinstance(p, str) or not p.strip() for p in posts):
                raise ValueError('posts require nonempty texts')
            # Mastodon strips status text; stored text identifies posts on resume.
            user['posts'] = [p.strip() for p in posts]
            if any(len(p) > 500 for p in user['posts']) or len(set(user['posts'])) != len(posts):
                raise ValueError('posts require distinct texts of at most 500 characters')
            usernames.add(username)
            emails.add(email)
        for user in data['users']:
            follows = user.get('follows', [])
            if (not isinstance(follows, list) or len(set(follows)) != len(follows) or user['username'] in follows
                    or any(name not in usernames | {DEFAULT_ADMIN['username']} for name in follows)):
                raise ValueError('follows require distinct configured usernames other than the user')
        self._configuration = data
        return self

    def addUser(self, user):
        """Add one initial account before compilation."""
        if self._configuration is None:
            raise ValueError('set the initial configuration before adding users')
        return self.setInitialConfiguration({**self._configuration,
                                             'users': [*self._configuration['users'], user]})

    def setSavePath(self, path):
        if self._configured:
            raise RuntimeError('set social network state before compilation')
        self._state_path = Path(path).expanduser().resolve()
        return self

    def enableHostAccess(self, port=8450):
        if type(port) is not int or not 1 <= port <= 65535 or port == 80:
            raise ValueError('invalid social network browser port; port 80 serves emulated clients')
        self._host_port = port
        return self

    def getAddress(self, role='gateway'):
        if role not in self._addresses:
            raise RuntimeError('configure SocialNetworkBundle before reading component addresses')
        return self._addresses[role]

    def getURL(self):
        return 'http://' + self._hostname

    def getImages(self):
        return dict(self._images)

    def getAdminCredentials(self):
        """Mastodon's built-in development administrator; sign in with the email."""
        return {**DEFAULT_ADMIN, 'email': 'admin@' + self._hostname}

    def configure(self):
        if self._configured:
            return
        if self._configuration is None:
            raise ValueError('SocialNetworkBundle requires an explicit initial configuration')
        if any(user['email'] == self.getAdminCredentials()['email'] for user in self._configuration['users']):
            raise ValueError('admin@<hostname> belongs to the built-in administrator')
        if self._emulator is None or not self._emulator.rendered():
            raise RuntimeError('Render the emulator before configuring SocialNetworkBundle')
        if len(self.getInternalNetworks()) != 1:
            raise ValueError('SocialNetworkBundle requires exactly one addInternalNetwork() call')
        super().configure()
        net, = self.getInternalNetworks()
        for (role, container), address in zip(self._containers.items(), net['ip_addresses']):
            container.joinInternalNetwork(net['asn'], net['network_name'], address,
                                          container.getHostname(), net['default_route'])
            self._addresses[role] = address
        self._configured = True

    def install(self):
        if not self._configured:
            raise RuntimeError('configure SocialNetworkBundle before installation')
        root = Path(self._name)
        cfg = root / 'config'
        cfg.mkdir(parents=True, mode=0o700)
        state = self._state_path or Path(tempfile.mkdtemp(prefix='seedemu-social-'))
        if Path.cwd() == state or Path.cwd() in state.parents:
            raise ValueError('social network state must be outside the compilation output directory')
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        configuration = {**self._configuration, 'hostname': self._hostname}
        identity = {'configuration': configuration,
                    'addresses': self._addresses, 'resolver': self._resolver}
        stamp = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        record = state / 'deployment.sha256'
        if record.exists() and record.read_text() != stamp:
            raise ValueError(
                'saved social network state uses another configuration or network; use a new state directory')
        record.write_text(stamp)
        credentials = state / 'credentials.json'
        if credentials.exists():
            keys = json.loads(credentials.read_text())
        else:
            # Same formats as Rails' local secret and `bin/rails db:encryption:init`.
            alphanumeric = lambda: ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            keys = {'database': secrets.token_hex(24), 'secret_key_base': secrets.token_hex(64),
                    'deterministic_key': alphanumeric(), 'key_derivation_salt': alphanumeric(),
                    'primary_key': alphanumeric()}
            credentials.write_text(json.dumps(keys) + '\n')
            credentials.chmod(0o600)
        fingerprint = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
        for filename, content in [('initialize.sh', INITIALIZE_SH), ('initialize.rb', INITIALIZE),
                                  ('nginx.conf', gateway_config(self._addresses, self._hostname, self._host_port)),
                                  ('initial.json', json.dumps({'fingerprint': fingerprint, 'admin': DEFAULT_ADMIN['username'],
                                                               'configuration': configuration}) + '\n'),
                                  # Rails development reads secret_key_base from tmp/local_secret.txt.
                                  ('local_secret.txt', keys['secret_key_base'])]:
            (cfg / filename).write_text(content)
            (cfg / filename).chmod(0o600 if filename in ('initial.json', 'local_secret.txt') else 0o644)
        # Runtime settings merged from mastodon/.devcontainer/compose.yaml.
        env = {'RAILS_ENV': 'development', 'NODE_ENV': 'development', 'BIND': '0.0.0.0',
               'BOOTSNAP_CACHE_DIR': '/tmp', 'LOCAL_DOMAIN': self._hostname,
               'STREAMING_API_BASE_URL': 'ws://' + self._hostname,
               'DB_HOST': self.getAddress('db'), 'DB_PORT': 5432, 'DB_USER': 'postgres',
               'DB_PASS': keys['database'], 'DB_NAME': 'mastodon_development',
               'REDIS_HOST': self.getAddress('redis'), 'REDIS_PORT': 6379,
               # Development mail is kept for /letter_opener; search and translation are not deployed.
               'REMOTE_DEV': 'true', 'ES_ENABLED': 'false', 'SKIP_TEST_DATABASE': 'true',
               'UPDATE_CHECK_URL': '', 'ALLOWED_PRIVATE_ADDRESSES': '10.0.0.0/8',
               'ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY': keys['deterministic_key'],
               'ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT': keys['key_derivation_salt'],
               'ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY': keys['primary_key']}
        commands = {'gateway': ['/docker-entrypoint.sh', 'nginx', '-c', '/social-config/nginx.conf', '-g', 'daemon off;'],
                    'web': ['bundle', 'exec', 'puma', '-C', 'config/puma.rb'],
                    'streaming': ['node', './streaming/index.js'],
                    'sidekiq': ['bundle', 'exec', 'sidekiq'],
                    'db': ['docker-entrypoint.sh', 'postgres'],
                    'redis': ['docker-entrypoint.sh', 'redis-server', '--appendonly', 'yes'],
                    'initialize': ['/bin/sh', '/social-config/initialize.sh']}
        health = lambda command, retries=120: {'test': ['CMD-SHELL', command], 'interval': '5s',
                                               'timeout': '10s', 'retries': retries}
        checks = {'gateway': health('curl -fsS http://127.0.0.1/healthz >/dev/null || wget -q -O /dev/null http://127.0.0.1/healthz'),
                  # Development boots and loads code on first use; allow it up to 20 minutes.
                  'web': health('curl -fsS http://127.0.0.1:3000/health >/dev/null', 240),
                  'streaming': health('curl -fsS http://127.0.0.1:4000/api/v1/streaming/health >/dev/null', 240),
                  'db': health('pg_isready -h 127.0.0.1 -U postgres'),
                  'redis': {'test': ['CMD', 'redis-cli', 'ping'], 'interval': '5s', 'timeout': '5s', 'retries': 20},
                  'initialize': {'disable': True}}
        # Fresh mappings per entry: shared objects become YAML anchors that PyYAML rejects.
        wait = lambda condition, *roles: {self.getContainer(r).getHostname(): {'condition': condition} for r in roles}
        dependencies = {'gateway': wait('service_healthy', 'web', 'streaming'),
                        'initialize': wait('service_healthy', 'db', 'redis'),
                        **{role: wait('service_completed_successfully', 'initialize')
                           for role in ('web', 'streaming', 'sidekiq')}}
        shared = {'system': SOURCE + '/public/system', 'letters': SOURCE + '/tmp/letter_opener'}
        targets = {'web': shared, 'sidekiq': shared, 'db': {'postgres': '/var/lib/postgresql/data'},
                   'redis': {'redis': '/data'}, 'initialize': {'initialization': '/social-state'}}
        for role, c in self._containers.items():
            # Keep the Internet Map labels added by joinInternalNetwork().
            labels = {**c._service.get('labels', {}),
                      'org.emuvista.bundle': 'SocialNetworkBundle', 'org.emuvista.component': role}
            value = {'image': self._images[role], 'command': commands[role],
                     'cap_add': ['NET_ADMIN'], 'restart': 'on-failure:3' if role == 'initialize' else 'unless-stopped',
                     'dns': [self._resolver], 'volumes': [], 'healthcheck': checks.get(role, {'disable': True}),
                     'labels': labels}
            environment = {}
            if role in MASTODON_ROLES:
                environment = {**env, 'PORT': 4000 if role == 'streaming' else 3000}
                if role == 'initialize':
                    value['volumes'].append(f'./{self._name}/config:/social-config:ro')
                if role != 'streaming':
                    value['volumes'].append(f'./{self._name}/config/local_secret.txt:{SOURCE}/tmp/local_secret.txt:ro')
            elif role == 'db':
                environment = {'POSTGRES_USER': 'postgres', 'POSTGRES_PASSWORD': keys['database'],
                               'POSTGRES_DB': 'postgres'}
            elif role == 'gateway':
                value['volumes'].append(f'./{self._name}/config/nginx.conf:/social-config/nginx.conf:ro')
                if self._host_port:
                    value['ports'] = [f'127.0.0.1:{self._host_port}:{self._host_port}/tcp']
            if environment:
                value['environment'] = {k: str(v).replace('$', '$$') for k, v in environment.items()}
            if role in dependencies:
                value['depends_on'] = dependencies[role]
            for directory, target in targets.get(role, {}).items():
                path = state / directory
                path.mkdir(exist_ok=True, mode=0o755)
                value['volumes'].append(f'{path}:{target}')
            c.updateServiceConfig(value)
            c.setFile('/application-start.sh',
                      APPLICATION_START if role in MASTODON_ROLES else '#!/bin/sh\nexec "$@"\n')
            c.setEntrypointWrapper('/application-start.sh', [])
        (root / 'deployment.json').write_text(json.dumps({'addresses': self._addresses, 'resolver': self._resolver,
                                                          'images': self._images, 'state_path': str(state),
                                                          'persistent': self._state_path is not None,
                                                          'hostname': self._hostname, 'url': self.getURL(),
                                                          'browser': f'http://localhost:{self._host_port}/' if self._host_port else None}, indent=2) + '\n')
        Path('docker-compose.yml').touch(mode=0o600, exist_ok=True)
        Path('docker-compose.yml').chmod(0o600)
        return super().install()
