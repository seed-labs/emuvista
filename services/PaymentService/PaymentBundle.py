"""Komunitin containers attached directly to rendered SEED networks."""

from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import zipfile
from ipaddress import IPv4Address
from pathlib import Path

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer
from seedemu.core.enums import NetworkType

from .initialization import load_configuration, prepare_bundle
from .templates import BACKEND_START, BROWSER_LINKS, DATABASE_START, INITIALIZE, nginx_config


REVISION = "124a87b639c37952dc9a029fc7056e523a10de5b"
DEFAULT_IMAGES = {
    **{role: f"h20-komunitin-{role}:{REVISION[:12]}" for role in
       ("app", "auth", "social", "accounting", "notifications-ts", "cli")},
    "database": f"h20-komunitin-db-auth:{REVISION[:12]}",
    "redis": "redis:7-alpine",
    "stellar": "h20-stellar-quickstart:core-horizon-beb4f2f",
    "files": "h20-komunitin-s3:3.7.1",
    "gateway": "nginx:stable-alpine",
}


ROLES = ('gateway', 'app', 'auth', 'social', 'accounting', 'notifications-ts',
         'db-auth', 'db-social', 'db-accounting', 'db-notifications',
         'redis', 'stellar', 'files', 'initialize')


class RoutedContainer(PreparedContainer):
    """Add routing tools to Debian or Alpine images without changing app code."""

    def _computeDockerfile(self):
        image = self.service.pop('image')
        self.service['build'] = './' + self.getHostname()
        lines = [f'FROM {image}', 'USER root',
                 'RUN if ! command -v ip >/dev/null 2>&1; then '
                 'if command -v apk >/dev/null 2>&1; then apk add --no-cache iproute2; '
                 'else apt-get update && apt-get install -y --no-install-recommends iproute2 '
                 '&& rm -rf /var/lib/apt/lists/*; fi; fi']
        lines.extend(self._addFile(path, content) for path, content in self._files.items())
        return '\n'.join(lines) + '\n'


class PaymentBundle(ContainerBundle):
    """Configure after render; every component owns an emulated IP address."""

    def __init__(self, emulator=None, images=None, name='payment'):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
            raise ValueError('bundle name requires 1 to 32 lowercase letters, digits or hyphens')
        super().__init__(emulator=emulator)
        self._name = name
        self._images = dict(DEFAULT_IMAGES)
        for role, image in (images or {}).items():
            self.setImage(role, image)
        self._admin_email = 'admin@payment.example'
        self._admin_password = secrets.token_urlsafe(24)
        self._admin_explicit = False
        self._initial_data = None
        self._initial_configuration = None
        self._state_path = None
        self._host_port = None
        self._addresses = {}
        self._configured = False
        self._required_emu_network_address_number = len(ROLES)
        for role in ROLES:
            container = RoutedContainer(name=name+'-'+role)
            self._containers[role] = container

    def setAdminCredentials(self, email, password):
        if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', email):
            raise ValueError('invalid payment administrator email')
        if len(password) < 8 or any(c in password for c in '\x00\n\r'):
            raise ValueError('administrator password requires at least 8 characters and no newlines')
        if self._initial_configuration is not None:
            load_configuration(self._initial_configuration, email)
        self._admin_email, self._admin_password = email, password
        self._admin_explicit = True
        return self

    def setInitialConfiguration(self, configuration: str | Path | dict) -> PaymentBundle:
        """Set groups, currencies, users and trustlines from JSON or a mapping.

        Validation copies the configuration now. Compilation generates import
        data or reuses saved data; startup applies it once through Komunitin.
        No users, balances or exchange rules are supplied by the bundle itself.
        """
        self._initial_configuration = load_configuration(configuration, self._admin_email)
        self._initial_data = None
        return self

    def setInitialData(self, bundle):
        """Select an existing migration ZIP instead of JSON configuration."""
        if isinstance(bundle, bytes):
            self._initial_data = bundle
        else:
            path = Path(bundle).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f'payment initial bundle does not exist: {path}')
            self._initial_data = path
        self._initial_configuration = None
        return self

    def setSavePath(self, path):
        self._state_path = Path(path).expanduser().resolve()
        return self

    def enableHostAccess(self, port=8443):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('host access port must be an integer between 1 and 65535')
        if port in {443,2023,2025,2026,2028,9191}:
            raise ValueError('host access port conflicts with a gateway API port')
        self._host_port = port
        return self

    def setImage(self, role, image):
        if role not in DEFAULT_IMAGES:
            raise ValueError(f'unknown payment image role: {role}')
        if not isinstance(image,str) or not image or any(c.isspace() for c in image):
            raise ValueError('payment image reference must be nonempty and contain no whitespace')
        self._images[role] = image
        return self

    def getImages(self):
        return dict(self._images)

    def getAddress(self, role='gateway'):
        if role not in self._addresses:
            raise RuntimeError('configure the bundle before reading component addresses')
        return self._addresses[role]

    def getURL(self):
        return 'https://' + self.getAddress()

    def getAdminCredentials(self):
        return {'email':self._admin_email,'password':self._admin_password}

    def configure(self):
        if self._configured:
            return
        super().configure()
        if self._emulator is None or not self._emulator.rendered():
            raise RuntimeError('render the emulator before configuring PaymentBundle')
        missing = [c for c in self._containers.values() if not c._internal_networks]
        allocated = set()
        if missing:
            self._required_emu_network_address_number = len(missing)
            if not self._default_internal_network:
                self.allocateEmuNetworkAddress()
                if self._default_internal_network:
                    allocated.update(self._default_internal_network['ip_addresses'])
            network = self._default_internal_network
            if network is None or len(network['ip_addresses']) < len(missing):
                raise ValueError(f'PaymentBundle requires {len(missing)} free emulated IP addresses')
            for container, address in zip(missing, network['ip_addresses']):
                container.joinInternalNetwork(network['network'],container.getHostname(),address,network['default_route'])
        self._validate_networks(allocated)
        if self._initial_configuration is not None:
            self._initial_data = prepare_bundle(
                self._initial_configuration, self._admin_email, self._state_path)
        self._secrets = self._credentials()
        self._configured = True

    def _validate_networks(self, allocated):
        networks, occupied = {}, set()
        for (scope, kind, _), obj in self._emulator.getRegistry().getAll().items():
            if kind == 'net':
                key = obj.getName() if obj.getType()==NetworkType.Bridge else f'net_{scope}_{obj.getName()}'
                networks[key] = obj
            elif kind in ('hnode','rnode','brdnode'):
                occupied.update(str(i.getAddress()) for i in obj.getInterfaces())
        selected = set()
        for role, container in self._containers.items():
            if len(container._internal_networks) != 1:
                raise ValueError('each payment component requires exactly one emulated network')
            network_name, _, address, route = container._internal_networks[0]
            network = networks.get(network_name)
            ip = IPv4Address(address)
            if network is None or ip not in network.getPrefix():
                raise ValueError(f'{role}: address must belong to its rendered SEED network')
            if (address in occupied or address in selected or ip in
                    {network.getPrefix().network_address,network.getPrefix().broadcast_address}
                    or address == str(network.getDefaultRouter())):
                raise ValueError(f'{role}: emulated IP address is already occupied or reserved')
            reserved = network.getAttribute('container_bundle_reserved_addresses',set())
            if ip in reserved and address not in allocated:
                raise ValueError(f'{role}: address was reserved by another container bundle')
            if route != str(network.getDefaultRouter()):
                raise ValueError(f'{role}: default route must use the emulated network router')
            selected.add(address)
            self._addresses[role] = address
        # Reserve explicit assignments for other bundles as well.
        for container in self._containers.values():
            name, _, address, _ = container._internal_networks[0]
            network = networks[name]
            reserved = set(network.getAttribute('container_bundle_reserved_addresses',set()))
            reserved.add(IPv4Address(address))
            network.setAttribute('container_bundle_reserved_addresses',reserved)

    def _credentials(self):
        identity = {'layout':'independent-containers-v1','addresses':self._addresses,'admin_email':self._admin_email}
        if self._state_path:
            self._state_path.mkdir(parents=True,exist_ok=True,mode=0o700)
            file = self._state_path/'credentials.json'
            if file.exists():
                saved = json.loads(file.read_text())
                if saved.get('identity') != identity:
                    raise ValueError('saved payment state uses a different network layout or administrator; use a new state directory')
                if file.stat().st_mode & 0o077:
                    raise ValueError('saved payment credentials must have mode 0600')
                if self._admin_explicit and self._admin_password != saved['admin_password']:
                    raise ValueError('administrator password does not match saved payment state')
                self._admin_password = saved['admin_password']
                return saved
            if any(self._state_path.iterdir()):
                raise ValueError('payment state has data but no matching credentials.json')
        values = {'identity':identity,'admin_password':self._admin_password}
        for key in ('auth','social','accounting','notifications','master','salt','stellar','db'):
            values[key] = secrets.token_urlsafe(32)
        if self._state_path:
            file.write_text(json.dumps(values,indent=2)+'\n')
            file.chmod(0o600)
        return values

    @staticmethod
    def _write_import_plan(config, data):
        """Expand an optional multi-bundle package without extracting paths."""
        entries = {'initial.zip': data}
        after = None
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            marker = 'payment-initialization.json'
            if marker in archive.namelist():
                manifest = json.loads(archive.read(marker))
                if manifest.get('format') != 'seedemu-payment-v1':
                    raise ValueError('unsupported payment initialization package')
                bundles = manifest.get('bundles')
                after = manifest.get('after_import')
                if not isinstance(bundles, list) or not 1 <= len(bundles) <= 100:
                    raise ValueError('initialization package requires 1 to 100 bundles')
                names = bundles + ([after] if after else [])
                for name in names:
                    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name)
                            or name in {'initial.zip', 'initialize.mjs'}):
                        raise ValueError('invalid initialization package filename')
                if len(set(names)) != len(names):
                    raise ValueError('duplicate initialization package filenames')
                if any(not name.endswith('.zip') for name in bundles) or (after and not after.endswith('.mjs')):
                    raise ValueError('initialization package expects ZIP bundles and an optional MJS hook')
                if set(archive.namelist()) != {marker, *names}:
                    raise ValueError('initialization package contains unexpected files')
                if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                    raise ValueError('initialization package is too large')
                entries = {name: archive.read(name) for name in names}
        for name, content in entries.items():
            (config / name).write_bytes(content)
            (config / name).chmod(0o600)
        describe = lambda name: {'file': name, 'sha256': hashlib.sha256(entries[name]).hexdigest()}
        plan = {'bundles': [describe(name) for name in entries if name != after],
                'after_import': describe(after) if after else None}
        (config / 'import-plan.json').write_text(json.dumps(plan) + '\n')
        (config / 'import-plan.json').chmod(0o600)

    def install(self):
        if not self._configured:
            raise RuntimeError('configure PaymentBundle before installing it')
        root = Path(self._name)
        config = root/'config'
        config.mkdir(parents=True,mode=0o755)
        key = self._secrets
        state = self._state_path or Path(tempfile.mkdtemp(prefix='seedemu-payment-'))
        state.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self._state_path:
            for name in ('server.crt','server.key'):
                if (state/name).exists(): shutil.copy2(state/name,config/name)
        if not (config/'server.crt').exists():
            subprocess.run(['openssl','req','-x509','-nodes','-newkey','rsa:2048','-days','365',
                '-keyout',str(config/'server.key'),'-out',str(config/'server.crt'),
                '-subj','/CN=SEED PaymentBundle','-addext',
                f'subjectAltName=IP:{self.getAddress()},DNS:localhost,DNS:host.docker.internal,IP:127.0.0.1'],
                check=True,capture_output=True)
        (config/'server.key').chmod(0o600)
        if self._state_path:
            for name in ('server.crt','server.key'): shutil.copy2(config/name,state/name)
        for name,content in [('database.sh',DATABASE_START),('backend.sh',BACKEND_START),
                             ('initialize.mjs',INITIALIZE),('browser-links.mjs',BROWSER_LINKS),
                             ('nginx.conf',nginx_config(self._addresses,self._host_port))]:
            (config/name).write_text(content)
            (config/name).chmod(0o755 if name.endswith('.sh') else 0o600)
        fingerprint = ''
        if self._initial_data is not None:
            data = self._initial_data.read_bytes() if isinstance(self._initial_data,Path) else self._initial_data
            fingerprint = hashlib.sha256(data).hexdigest()
            if self._state_path:
                saved = state/'initial-data.zip'
                if saved.exists() and hashlib.sha256(saved.read_bytes()).hexdigest()!=fingerprint:
                    raise ValueError('initial data differs from saved payment state; use a new state directory')
                saved.write_bytes(data)
                saved.chmod(0o600)
            (config/'initial.zip').write_bytes(data)
            (config/'initial.zip').chmod(0o600)
            self._write_import_plan(config,data)
        mount = f'./{self._name}/config:/payment-config:ro'
        images = self._images
        public = self.getURL()
        url = lambda role,port: f'http://{self.getAddress(role)}:{port}'
        name = lambda role: self.getContainer(role).getHostname()

        def create(role,image,command,environment=None,dependencies=(),**kwargs):
            container = self.getContainer(role)
            value = {'image':image,'entrypoint':['/bin/sh','/payment-route.sh'],'command':command,
                     'cap_add':['NET_ADMIN'],'restart':'unless-stopped','volumes':[mount],
                     'labels':{'org.emuvista.bundle':'PaymentBundle','org.emuvista.component':role}}
            if dependencies:
                value['depends_on'] = {name(dep):{'condition':'service_healthy'} for dep in dependencies}
            if environment:
                value['environment'] = {k:str(v).replace('$','$$') for k,v in environment.items()}
            value.update(kwargs)
            container.setContentAttribute(value)
            container._start_script_name = '/payment-route.sh'
            container._start_commands = ['#!/bin/sh','set -eu','exec "$@"']
            return container.service

        def volume(value,role,target):
            directory = state/role
            directory.mkdir(exist_ok=True,mode=0o755)
            value['volumes'].append(f'{directory}:{target}')

        def health(port,path='/health'):
            return {'test':['CMD','node','-e',f'fetch("http://127.0.0.1:{port}{path}").then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))'],
                    'interval':'3s','timeout':'5s','retries':120}

        for role,user in [('db-auth','auth'),('db-social','social'),('db-accounting','accounting'),('db-notifications','notifications')]:
            env = {'PGDATA':'/var/lib/postgresql/data','PGPORT':5432,
                   'POSTGRES_USER':'postgres','POSTGRES_DB':'postgres','POSTGRES_PASSWORD':key['db'],
                   'POSTGRES_APP_USER':user,'POSTGRES_APP_PASSWORD':key['db'],'WALG_ENABLE':'false',
                   'POSTGRES_APP_EXTENSIONS':'postgis,vector,pg_trgm,btree_gin,unaccent' if user=='social' else ''}
            value = create(role,images['database'],['/bin/bash','/payment-config/database.sh'],env,
                healthcheck={'test':['CMD','pg_isready','-h','127.0.0.1','-p','5432','-U','postgres'],'interval':'3s','timeout':'5s','retries':120})
            volume(value,role,'/var/lib/postgresql/data')
        value = create('redis',images['redis'],['docker-entrypoint.sh','redis-server','--bind','0.0.0.0','--appendonly','yes'],
            healthcheck={'test':['CMD','redis-cli','ping'],'interval':'3s','timeout':'5s','retries':60})
        volume(value,'redis','/data')
        value = create('stellar',images['stellar'],['/start','--local','--enable','core,horizon'],
            {'STELLAR_MODE':'persistent','POSTGRES_PASSWORD':key['stellar']},
            healthcheck={'test':['CMD','curl','-fsS','http://127.0.0.1:8000/'],'interval':'3s','timeout':'5s','retries':180})
        volume(value,'stellar','/opt/stellar')
        value = create('files',images['files'],['node','/s3/node_modules/s3rver/bin/s3rver.js','-d','/data','-a','0.0.0.0','-p','9090','--configure-bucket','komunitin'],
            healthcheck=health(9090,'/komunitin'))
        volume(value,'files','/data')

        issuer = public+':2026'
        common = {'AUTH_JWKS_URL':url('auth',3026)+'/.well-known/jwks.json','AUTH_JWT_ISSUER':issuer,'AUTH_JWT_AUDIENCE':'urn:komunitin:api'}
        db = lambda user,role: f'postgresql://{user}:{key["db"]}@{self.getAddress(role)}:5432/{user}?schema=public'
        backend = lambda role,env,deps,port,path='/health': create(role,images[role],['/bin/sh','/payment-config/backend.sh'],env,deps,healthcheck=health(port,path))
        backend('auth',{'PORT':3026,'DATABASE_URL':db('auth','db-auth'),'JWT_ISSUER':issuer,'JWT_AUDIENCE':'urn:komunitin:api',
            'NOTIFICATIONS_URL':url('notifications-ts',3023),'AUTH_CLIENT_SECRET':key['auth'],
            'NOTIFICATIONS_CLIENT_SECRET':key['notifications'],'SOCIAL_CLIENT_SECRET':key['social'],
            'ACCOUNTING_CLIENT_SECRET':key['accounting'],'ADMIN_EMAIL':self._admin_email},['db-auth'],3026,'/.well-known/openid-configuration')
        value = backend('accounting',{**common,'PORT':3025,'DATABASE_URL':db('accounting','db-accounting'),
            'MASTER_PASSWORD':key['master'],'MASTER_PASSWORD_SALT':key['salt'],'STELLAR_NETWORK':'local',
            'STELLAR_HORIZON_URL':url('stellar',8000),'STELLAR_FRIENDBOT_URL':url('stellar',8000)+'/friendbot',
            'STELLAR_CHANNEL_ACCOUNTS_ENABLED':'true','DOMAIN':self.getAddress(),'AUTH_URL':url('auth',3026),
            'ACCOUNTING_CLIENT_SECRET':key['accounting'],'NOTIFICATIONS_API_URL':url('notifications-ts',3023),
            'API_BASE_URL':public+':2025','APP_URL':public,'SPONSOR_PRIVATE_KEY':'','DOCKER':'false',
            'NODE_OPTIONS':'--import=/payment-config/browser-links.mjs',
            'PAYMENT_GATEWAY_ADDRESS':self.getAddress(),'PAYMENT_BROWSER_PORT':self._host_port or '',
            'NODE_EXTRA_CA_CERTS':'/payment-config/server.crt'},['db-accounting','auth','stellar'],3025,'/')
        value = backend('notifications-ts',{**common,'PORT':3023,'DATABASE_URL':db('notifications','db-notifications'),
            'REDIS_URL':'redis://'+self.getAddress('redis')+':6379','KOMUNITIN_AUTH_URL':url('auth',3026),
            'KOMUNITIN_SOCIAL_URL':url('social',3028),'KOMUNITIN_SOCIAL_PUBLIC_URL':public+':2028',
            'KOMUNITIN_ACCOUNTING_URL':url('accounting',3025),'KOMUNITIN_APP_URL':public,
            'NOTIFICATIONS_CLIENT_SECRET':key['notifications'],'SMTP_HOST':'','SMTP_PORT':587,'SMTP_USER':'','SMTP_PASS':'',
            'DEV_SAVE_EMAILS':'true','FLAVOR':'komunitin','ADMIN_EMAIL':self._admin_email,'APP_EMAIL':'payments@payment.example',
            'PUSH_NOTIFICATIONS_VAPID_PUBLIC_KEY':'','PUSH_NOTIFICATIONS_VAPID_PRIVATE_KEY':''},['db-notifications','redis','auth'],3023)
        volume(value,'mail','/app/tmp')
        backend('social',{**common,'PORT':3028,'DATABASE_URL':db('social','db-social'),'API_BASE_URL':public+':2028',
            'ACCOUNTING_URL':url('accounting',3025),'AUTH_URL':url('auth',3026),'SOCIAL_CLIENT_SECRET':key['social'],
            'NOTIFICATIONS_API_URL':url('notifications-ts',3023),'UPLOAD_S3_PREFIX':'s3://komunitin/uploads',
            'UPLOAD_S3_ENDPOINT':url('files',9090),'UPLOAD_S3_REGION':'us-east-1','UPLOAD_S3_ACCESS_KEY':'S3RVER',
            'UPLOAD_S3_SECRET_KEY':'S3RVER','UPLOAD_S3_FORCE_PATH_STYLE':'true','UPLOAD_PUBLIC_URL':public+':9191/komunitin/uploads'},
            ['db-social','auth','accounting','notifications-ts','files'],3028)
        create('app',images['app'],['/docker-entrypoint.sh','nginx','-g','daemon off;'],
            {'MOCK_ENABLE':'false','AUTH_URL':issuer,'SOCIAL_URL':public+':2028','FILES_URL':public+':2028',
             'ACCOUNTING_URL':public+':2025','NOTIFICATIONS_URL':public+':2023','FEEDBACK_URL':'','DOCS_URL':'',
             'PRIVACY_URL':'','TERMS_URL':'','COOKIES_URL':'','GTAG_ID':'','MATOMO_URL':'','MATOMO_SITE_ID':'',
             'PUSH_NOTIFICATIONS_VAPID_PUBLIC_KEY':''},
            healthcheck={'test':['CMD','wget','-q','--spider','http://127.0.0.1/'],'interval':'3s','timeout':'5s','retries':60})
        value = create('initialize',images['cli'],['node','/payment-config/initialize.mjs'],
            {'ADMIN_EMAIL':self._admin_email,'ADMIN_PASSWORD':self._admin_password,'KOMUNITIN_AUTH_URL':url('auth',3026),
             'KOMUNITIN_SOCIAL_URL':url('social',3028),'KOMUNITIN_ACCOUNTING_URL':url('accounting',3025),
             'KOMUNITIN_NOTIFICATIONS_SECRET':key['notifications'],'INITIAL_DATA_SHA256':fingerprint},
            ['auth','social','accounting','notifications-ts'],restart='on-failure:3')
        volume(value,'initialization','/payment-state')
        value = create('gateway',images['gateway'],['/docker-entrypoint.sh','nginx','-c','/payment-config/nginx.conf','-g','daemon off;'],
            dependencies=['app'],healthcheck={'test':['CMD','wget','-q','--no-check-certificate','--spider','https://127.0.0.1/healthz'],
                                             'interval':'3s','timeout':'5s','retries':60})
        value['depends_on'][name('initialize')] = {'condition':'service_completed_successfully'}
        if self._host_port is not None:
            value['ports'] = [f'127.0.0.1:{self._host_port}:{self._host_port}/tcp']
        (root/'deployment.json').write_text(json.dumps({'url':public,'addresses':self._addresses,'images':images,
            'initial_data_sha256':fingerprint,'state_path':str(state),'persistent':self._state_path is not None},indent=2)+'\n')
        Path('docker-compose.yml').touch(mode=0o600,exist_ok=True)
        Path('docker-compose.yml').chmod(0o600)
        # ContainerBundle uses registration keys as Compose service names.
        containers = self._containers
        self._containers = {container.getHostname():container for container in containers.values()}
        try:
            return super().install()
        finally:
            self._containers = containers
