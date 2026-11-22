"""Prepare the native LDAP catalog once; passwords remain in the IdP."""

import json
from pathlib import Path
import time

import ldap
from ldap_directory import connect, provision

configuration = json.loads(Path('/identity-config/identity.json').read_text())
settings = {**configuration['ldap'], 'host': '127.0.0.1'}
for attempt in range(60):
    try:
        connection = connect(settings)
        break
    except ldap.SERVER_DOWN:
        time.sleep(1)
else:
    raise RuntimeError('Employee LDAP catalog did not start')
try:
    connection.add_s('ou=people,' + settings['base_dn'], [
        ('objectClass', [b'top', b'organizationalUnit']), ('ou', [b'people']),
    ])
except ldap.ALREADY_EXISTS:
    pass
connection.unbind_s()
administrator = {'id': 'admin', 'firstName': 'Company', 'lastName': 'Administrator',
                 'email': 'admin@company.com'}
provision(administrator, settings)
marker = Path('/var/lib/ldap/.company-initialized')
if not marker.exists():
    for person in configuration['employees']:
        provision(person, settings)
    marker.write_text('Company employee catalog initialized.\n')
print('Company LDAP catalog is ready.', flush=True)
