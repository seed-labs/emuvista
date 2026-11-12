"""Native Mailu API initialization."""

INITIALIZE = r'''import hashlib, json, time, urllib.request, urllib.error
from pathlib import Path

cfg = json.loads(Path('/mailu-config/initial.json').read_text())
record = Path('/mailu-state/initialized.json')
fingerprint = hashlib.sha256(json.dumps(cfg['configuration'], sort_keys=True).encode()).hexdigest()
if record.exists():
    saved = json.loads(record.read_text())
    if saved['fingerprint'] != fingerprint:
        raise SystemExit('Initial mailbox configuration differs from saved state')
    print('Email state already initialized')
    raise SystemExit(0)
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, body=None, method=None):
    req = urllib.request.Request(cfg['url'] + '/api/v1/' + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg['token']}, method=method)
    try:
        with http.open(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError('Mailu initialization API rejected ' +
                           path + ' (HTTP ' + str(e.code) + ')') from None


for attempt in range(180):
    try:
        existing_domains = {d['name'] for d in api('domain')}
        break
    except (OSError, RuntimeError):
        time.sleep(2)
else:
    raise SystemExit('Mailu administration API did not become ready')
configuration = cfg['configuration']
for domain in configuration['domains']:
    if domain not in existing_domains:
        api('domain', {'name': domain, 'max_users': -1, 'max_aliases': -1, 'signup_enabled': True})
    else:
        api('domain/' + domain, {'signup_enabled': True}, 'PATCH')
existing_users = {u['email'] for u in api('user')}
users = [configuration['admin']] + configuration['users']
for user in users:
    fields = {'change_pw_next_login': user.get('change_password_on_login', False)}
    if 'quota_bytes' in user:
        fields['quota_bytes'] = user['quota_bytes']
    if user['email'] not in existing_users:
        api('user', {'email': user['email'], 'raw_password': user['password'], **fields})
    else:
        # Do not reset an existing password or mailbox when resuming initialization.
        api('user/' + user['email'], fields, 'PATCH')
existing_aliases = {a['email'] for a in api('alias')}
for alias in configuration.get('aliases', []):
    if alias['email'] not in existing_aliases:
        api('alias', alias)
record.parent.mkdir(parents=True, exist_ok=True)
temporary = record.with_suffix('.tmp')
temporary.write_text(json.dumps({'fingerprint': fingerprint}) + '\n')
temporary.replace(record)
print('Mailu domains, users and aliases initialized')
'''
