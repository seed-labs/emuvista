"""Existing SEED ContainerBundle adapter; no Docker daemon inside SEED nodes."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml
from seedemu.containerBundle import ContainerBundle

from .templates import BACKEND_START, DATABASE_START, INITIALIZE, nginx_config


class PaymentBundle(ContainerBundle):
    def __init__(self, emulator, service):
        super().__init__(emulator=emulator)
        self._payment = service

    def configure(self):
        if not self._payment._configured:
            raise RuntimeError("add and render PaymentService before compiling its container bundle")

    def install(self):
        definitions = {}
        for server in self._payment.getPendingTargets().values():
            prefix = 'payment-' + re.sub(r'[^a-z0-9-]', '-', server._vnode.lower()).strip('-')[:32]
            prefix += '-' + hashlib.sha256(server._vnode.encode()).hexdigest()[:8]
            root = Path(prefix)
            config = root / 'config'
            config.mkdir(parents=True, mode=0o755)
            key = server._secrets
            state = server._state_path or (root / 'state')
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            if server._state_path:
                for name in ('server.crt', 'server.key'):
                    if (state / name).exists():
                        shutil.copy2(state / name, config / name)
            if not (config / 'server.crt').exists():
                subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '365',
                    '-keyout', str(config / 'server.key'), '-out', str(config / 'server.crt'),
                    '-subj', '/CN=SEED PaymentService', '-addext',
                    f'subjectAltName=IP:{server.getAddress()},DNS:localhost,IP:127.0.0.1'],
                    check=True, capture_output=True)
            (config / 'server.key').chmod(0o600)
            if server._state_path:
                for name in ('server.crt', 'server.key'):
                    shutil.copy2(config / name, state / name)
            for name, content in [('database.sh', DATABASE_START), ('backend.sh', BACKEND_START),
                                  ('initialize.mjs', INITIALIZE),
                                  ('nginx.conf', nginx_config(server.getAddress(), server._host_port is not None))]:
                (config / name).write_text(content)
                (config / name).chmod(0o755 if name.endswith('.sh') else 0o600)
            initial = server._initial_data
            fingerprint = ''
            if initial is not None:
                data = initial.read_bytes() if isinstance(initial, Path) else initial
                fingerprint = hashlib.sha256(data).hexdigest()
                if server._state_path:
                    saved = state / 'initial-data.zip'
                    if saved.exists() and hashlib.sha256(saved.read_bytes()).hexdigest() != fingerprint:
                        raise ValueError('initial data differs from saved payment state; use a new state directory')
                    saved.write_bytes(data)
                    saved.chmod(0o600)
                (config / 'initial.zip').write_bytes(data)
                (config / 'initial.zip').chmod(0o600)
            public = server.getURL()
            scope, kind, _ = server._node.getRegistryInfo()
            node_service = f'{kind}_{scope}_{server._node.getName()}'
            # Relative config mounts make the compiled output portable. Data may
            # be explicitly persisted outside the compiler's output directory.
            mount = f'./{prefix}/config:/payment-config:ro'
            images = self._payment.getImages()

            def name(role):
                return f'{prefix}-{role}'

            def create(role, image, environment=None, dependencies=None, **kwargs):
                depends = {node_service: {'condition': 'service_started'}}
                for dependency in dependencies or []:
                    depends[name(dependency)] = {'condition': 'service_healthy'}
                value = {'image': image, 'network_mode': f'service:{node_service}',
                         'depends_on': depends, 'restart': 'unless-stopped', 'volumes': [mount],
                         'labels': {'org.emuvista.service': 'PaymentService', 'org.emuvista.vnode': server._vnode}}
                if environment:
                    # Compose interpolation must not alter caller-supplied secrets.
                    value['environment'] = {k: str(v).replace('$', '$$') for k, v in environment.items()}
                value.update(kwargs)
                definitions[name(role)] = value
                return value

            def volume(value, role, target):
                directory = state / role
                directory.mkdir(exist_ok=True, mode=0o755)
                source = str(directory) if directory.is_absolute() else './' + str(directory)
                value['volumes'].append(f'{source}:{target}')

            def node_health(port, path='/health'):
                return {'test': ['CMD', 'node', '-e', f'fetch("http://127.0.0.1:{port}{path}").then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))'],
                        'interval': '3s', 'timeout': '5s', 'retries': 120}

            for role, user, port in [('db-auth', 'auth', 5433), ('db-social', 'social', 5434),
                                     ('db-accounting', 'accounting', 5435), ('db-notifications', 'notifications', 5436)]:
                env = {'PGDATA': '/var/lib/postgresql/data', 'PGPORT': port,
                       'POSTGRES_USER': 'postgres', 'POSTGRES_DB': 'postgres',
                       'POSTGRES_PASSWORD': key['db'], 'POSTGRES_APP_USER': user,
                       'POSTGRES_APP_PASSWORD': key['db'], 'WALG_ENABLE': 'false',
                       'POSTGRES_APP_EXTENSIONS': 'postgis,vector,pg_trgm,btree_gin,unaccent' if user == 'social' else ''}
                value = create(role, images['database'], env, entrypoint=['/bin/bash', '/payment-config/database.sh'],
                               healthcheck={'test': ['CMD', 'pg_isready', '-h', '127.0.0.1', '-p', str(port), '-U', 'postgres'], 'interval': '3s', 'timeout': '5s', 'retries': 120})
                volume(value, role, '/var/lib/postgresql/data')

            value = create('redis', images['redis'], command=['redis-server', '--bind', '127.0.0.1', '--appendonly', 'yes'],
                           healthcheck={'test': ['CMD', 'redis-cli', 'ping'], 'interval': '3s', 'timeout': '5s', 'retries': 60})
            volume(value, 'redis', '/data')
            value = create('stellar', images['stellar'], {'STELLAR_MODE': 'persistent', 'POSTGRES_PASSWORD': key['stellar']},
                           command=['--local', '--enable', 'core,horizon'],
                           healthcheck={'test': ['CMD', 'curl', '-fsS', 'http://127.0.0.1:8000/'], 'interval': '3s', 'timeout': '5s', 'retries': 180})
            volume(value, 'stellar', '/opt/stellar')
            value = create('files', images['files'], command=['-d', '/data', '-a', '127.0.0.1', '-p', '9090', '--configure-bucket', 'komunitin'],
                           healthcheck=node_health(9090, '/komunitin'))
            volume(value, 'files', '/data')

            issuer = public + ':2026'
            common = {'AUTH_JWKS_URL': 'http://127.0.0.1:3026/.well-known/jwks.json',
                      'AUTH_JWT_ISSUER': issuer, 'AUTH_JWT_AUDIENCE': 'urn:komunitin:api'}
            db = lambda user, port: f'postgresql://{user}:{key["db"]}@127.0.0.1:{port}/{user}?schema=public'
            backend = lambda role, env, deps, port, path='/health': create(role, images[role], env, deps,
                entrypoint=['/bin/sh', '/payment-config/backend.sh'], healthcheck=node_health(port, path))
            backend('auth', {'PORT': 3026, 'DATABASE_URL': db('auth', 5433), 'JWT_ISSUER': issuer,
                'JWT_AUDIENCE': 'urn:komunitin:api', 'NOTIFICATIONS_URL': 'http://127.0.0.1:3023',
                'AUTH_CLIENT_SECRET': key['auth'], 'NOTIFICATIONS_CLIENT_SECRET': key['notifications'],
                'SOCIAL_CLIENT_SECRET': key['social'], 'ACCOUNTING_CLIENT_SECRET': key['accounting'],
                'ADMIN_EMAIL': server._admin_email}, ['db-auth'], 3026, '/.well-known/openid-configuration')
            backend('accounting', {**common, 'PORT': 3025, 'DATABASE_URL': db('accounting', 5435),
                'MASTER_PASSWORD': key['master'], 'MASTER_PASSWORD_SALT': key['salt'],
                'STELLAR_NETWORK': 'local', 'STELLAR_HORIZON_URL': 'http://127.0.0.1:8000',
                'STELLAR_FRIENDBOT_URL': 'http://127.0.0.1:8000/friendbot', 'STELLAR_CHANNEL_ACCOUNTS_ENABLED': 'true',
                'DOMAIN': server.getAddress(), 'AUTH_URL': 'http://127.0.0.1:3026',
                'ACCOUNTING_CLIENT_SECRET': key['accounting'], 'NOTIFICATIONS_API_URL': 'http://127.0.0.1:3023',
                'API_BASE_URL': public + ':2025', 'APP_URL': public, 'SPONSOR_PRIVATE_KEY': '', 'DOCKER': 'true'},
                ['db-accounting', 'auth', 'stellar'], 3025, '/')
            value = backend('notifications-ts', {**common, 'PORT': 3023, 'DATABASE_URL': db('notifications', 5436),
                'REDIS_URL': 'redis://127.0.0.1:6379', 'KOMUNITIN_AUTH_URL': 'http://127.0.0.1:3026',
                'KOMUNITIN_SOCIAL_URL': 'http://127.0.0.1:3028', 'KOMUNITIN_SOCIAL_PUBLIC_URL': public + ':2028',
                'KOMUNITIN_ACCOUNTING_URL': 'http://127.0.0.1:3025', 'KOMUNITIN_APP_URL': public,
                'NOTIFICATIONS_CLIENT_SECRET': key['notifications'], 'SMTP_HOST': '', 'SMTP_PORT': 587,
                'SMTP_USER': '', 'SMTP_PASS': '', 'DEV_SAVE_EMAILS': 'true', 'FLAVOR': 'komunitin',
                'ADMIN_EMAIL': server._admin_email, 'APP_EMAIL': 'payments@payment.example',
                'PUSH_NOTIFICATIONS_VAPID_PUBLIC_KEY': '', 'PUSH_NOTIFICATIONS_VAPID_PRIVATE_KEY': ''},
                ['db-notifications', 'redis', 'auth'], 3023)
            volume(value, 'mail', '/app/tmp')
            backend('social', {**common, 'PORT': 3028, 'DATABASE_URL': db('social', 5434),
                'API_BASE_URL': public + ':2028', 'ACCOUNTING_URL': 'http://127.0.0.1:3025',
                'AUTH_URL': 'http://127.0.0.1:3026', 'SOCIAL_CLIENT_SECRET': key['social'],
                'NOTIFICATIONS_API_URL': 'http://127.0.0.1:3023', 'UPLOAD_S3_PREFIX': 's3://komunitin/uploads',
                'UPLOAD_S3_ENDPOINT': 'http://127.0.0.1:9090', 'UPLOAD_S3_REGION': 'us-east-1',
                'UPLOAD_S3_ACCESS_KEY': 'S3RVER', 'UPLOAD_S3_SECRET_KEY': 'S3RVER',
                'UPLOAD_S3_FORCE_PATH_STYLE': 'true', 'UPLOAD_PUBLIC_URL': public + ':9191/komunitin/uploads'},
                ['db-social', 'auth', 'accounting', 'notifications-ts', 'files'], 3028)

            create('app', images['app'], {'MOCK_ENABLE': 'false', 'AUTH_URL': issuer,
                'SOCIAL_URL': public + ':2028', 'FILES_URL': public + ':2028', 'ACCOUNTING_URL': public + ':2025',
                'NOTIFICATIONS_URL': public + ':2023', 'FEEDBACK_URL': '', 'DOCS_URL': '', 'PRIVACY_URL': '',
                'TERMS_URL': '', 'COOKIES_URL': '', 'GTAG_ID': '', 'MATOMO_URL': '', 'MATOMO_SITE_ID': '',
                'PUSH_NOTIFICATIONS_VAPID_PUBLIC_KEY': ''},
                healthcheck={'test': ['CMD', 'wget', '-q', '--spider', 'http://127.0.0.1/'], 'interval': '3s', 'timeout': '5s', 'retries': 60})
            value = create('initialize', images['cli'], {'ADMIN_EMAIL': server._admin_email, 'ADMIN_PASSWORD': server._admin_password,
                'KOMUNITIN_AUTH_URL': 'http://127.0.0.1:3026', 'KOMUNITIN_SOCIAL_URL': 'http://127.0.0.1:3028',
                'KOMUNITIN_NOTIFICATIONS_SECRET': key['notifications'],
                'INITIAL_DATA_SHA256': fingerprint},
                ['auth', 'social', 'accounting', 'notifications-ts'], entrypoint=['node', '/payment-config/initialize.mjs'], restart='on-failure:3')
            volume(value, 'initialization', '/payment-state')
            value = create('gateway', images['gateway'], dependencies=['app'],
                           command=['nginx', '-c', '/payment-config/nginx.conf', '-g', 'daemon off;'],
                           healthcheck={'test': ['CMD', 'wget', '-q', '--no-check-certificate', '--spider', 'https://127.0.0.1/healthz'], 'interval': '3s', 'timeout': '5s', 'retries': 60})
            value['depends_on'][name('initialize')] = {'condition': 'service_completed_successfully'}
            (root / 'deployment.json').write_text(json.dumps({'vnode': server._vnode, 'url': public,
                'node_service': node_service, 'images': images, 'initial_data_sha256': fingerprint}, indent=2) + '\n')
        # The compiler subsequently writes this file without replacing its inode.
        # Restrict it now because the component environments contain credentials.
        Path('docker-compose.yml').touch(mode=0o600, exist_ok=True)
        Path('docker-compose.yml').chmod(0o600)
        return ''.join('    ' + line + '\n' for line in yaml.safe_dump(definitions, sort_keys=False).splitlines()), ''
