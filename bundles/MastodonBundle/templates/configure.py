"""Generate noninteractive runtime configuration; retain secrets across restarts."""
import json
from pathlib import Path
import secrets
import shlex

settings = json.loads(Path('/opt/mastodon-service/settings.json').read_text())
state = Path('/var/lib/mastodon')
state.mkdir(parents=True, exist_ok=True)
saved = state / 'settings.json'
previous = json.loads(saved.read_text()) if saved.exists() else dict(settings)
# ACME URL was transport configuration, not instance identity.
previous.pop('acme_url', None)
identity = {k: v for k, v in settings.items() if k != 'acme_url'}
if previous != identity:
    raise SystemExit('Existing Mastodon settings differ; do not change an initialized instance identity.')
saved.write_text(json.dumps(identity))
env_path = state / 'runtime.env'
if not env_path.exists():
    env = {
        'RAILS_ENV': 'production', 'NODE_ENV': 'production',
        **({'EMUVISTA_HTTP': 'true'} if settings.get('scheme') == 'http' else {}),
        'LOCAL_DOMAIN': settings['domain'], 'WEB_DOMAIN': settings['web_domain'],
        'DB_HOST': '/var/run/postgresql', 'DB_USER': 'mastodon',
        'DB_NAME': 'mastodon_production', 'REDIS_HOST': '127.0.0.1',
        'RAILS_SERVE_STATIC_FILES': 'true', 'BIND': '127.0.0.1',
        'WEB_CONCURRENCY': '1', 'MAX_THREADS': '5',
        'ES_ENABLED': 'false', 'S3_ENABLED': 'false',
        'SMTP_DELIVERY_METHOD': 'file',
        'SMTP_FROM_ADDRESS': 'notifications@' + settings['domain'],
        'SECRET_KEY_BASE': secrets.token_hex(64),
        'ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY': secrets.token_hex(32),
        'ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY': secrets.token_hex(32),
        'ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT': secrets.token_hex(32),
    }
    env_path.write_text(''.join(f'{k}={shlex.quote(v)}\n' for k, v in env.items()))
    env_path.chmod(0o600)

domain = settings['domain']
cert_path = f'/etc/letsencrypt/live/{domain}' if settings.get('acme_url') else '/var/lib/mastodon/tls'
cert_file = 'fullchain.pem' if settings.get('acme_url') else 'cert.pem'
key_file = 'privkey.pem' if settings.get('acme_url') else 'key.pem'
Path('/etc/nginx/conf.d/mastodon-http.conf').write_text('''server {
    listen 80;
    server_name DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/acme; }
    location / { return 301 https://WEB_DOMAIN$request_uri; }
}
'''.replace('WEB_DOMAIN', settings['web_domain']).replace('DOMAIN', domain))
proxy_config = ('''server {
    listen PORT ssl;
    server_name DOMAIN;
    ssl_certificate CERT_PATH/CERT_FILE;
    ssl_certificate_key CERT_PATH/KEY_FILE;
    client_max_body_size 100m;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    location /api/v1/streaming {
        proxy_pass http://127.0.0.1:4000;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
    location / { proxy_pass http://127.0.0.1:3000; }
}
'''.replace('DOMAIN', domain).replace('PORT', str(settings['port']))
    .replace('CERT_PATH', cert_path).replace('CERT_FILE', cert_file).replace('KEY_FILE', key_file))

if settings.get('scheme') == 'http':
    proxy_config = proxy_config.replace(' ssl;', ';').replace('X-Forwarded-Proto https;', 'X-Forwarded-Proto http;')
    proxy_config = '\n'.join(line for line in proxy_config.splitlines() if 'ssl_certificate' not in line) + '\n'
    Path('/etc/nginx/conf.d/mastodon-https.conf').unlink(missing_ok=True)
    Path('/etc/nginx/conf.d/mastodon-http.conf').write_text(proxy_config)
else:
    Path('/opt/mastodon-service/mastodon-https.conf').write_text(proxy_config)
