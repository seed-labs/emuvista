"""Configure the identity server through its native administration API."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = os.environ['IDENTITY_URL']


def request(method, path, body=None, token=None, form=False):
    headers = {}
    data = None
    if body is not None:
        data = (urlencode(body) if form else json.dumps(body)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urlopen(Request(BASE + path, data=data, headers=headers, method=method), timeout=30) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


def admin_token():
    return request('POST', '/realms/master/protocol/openid-connect/token', {
        'grant_type': 'password', 'client_id': 'admin-cli',
        'username': os.environ['IDENTITY_ADMIN'], 'password': os.environ['IDENTITY_PASSWORD'],
    }, form=True)['access_token']


def profile(person):
    return {'username': person['id'].lower(), 'enabled': person.get('active', True),
            'emailVerified': True, 'email': person['email'],
            'firstName': person['firstName'], 'lastName': person['lastName'],
            'attributes': {'employee_id': [person['id']], 'department': [person.get('department', '')],
                           'manager': [person.get('reportsTo', '')]}}


def main():
    configuration = json.loads(Path('/identity-config/identity.json').read_text())
    token = admin_token()
    try:
        request('GET', '/admin/realms/company', token=token)
    except HTTPError as error:
        if error.code != 404:
            raise
        request('POST', '/admin/realms', {
            'realm': 'company', 'enabled': True, 'sslRequired': 'none',
            'displayName': configuration.get('company', {}).get('name', 'Company'),
            'registrationAllowed': False, 'resetPasswordAllowed': False,
            'loginWithEmailAllowed': True, 'duplicateEmailsAllowed': False,
            'accessTokenLifespan': 300,
        }, token)
    # Declare custom profile fields so they remain available to OIDC mappers.
    settings = request('GET', '/admin/realms/company/users/profile', token=token)
    for name in ('employee_id', 'department', 'manager'):
        if not any(field['name'] == name for field in settings['attributes']):
            settings['attributes'].append({'name': name, 'displayName': name,
                                          'permissions': {'view': ['admin', 'user'], 'edit': ['admin']}})
    request('PUT', '/admin/realms/company/users/profile', settings, token)
    administrator = {'id': 'admin', 'firstName': 'Company', 'lastName': 'Administrator',
                     'email': 'admin@company.com', 'password': os.environ['IDENTITY_PASSWORD']}
    for person in [administrator, *configuration.get('employees', [])]:
        users = request('GET', '/admin/realms/company/users?' + urlencode({
            'username': person['id'].lower(), 'exact': 'true'}), token=token)
        if not users:
            request('POST', '/admin/realms/company/users', {
                **profile(person), 'credentials': [{'type': 'password',
                    'value': person['password'], 'temporary': False}],
            }, token)
    for name, client in configuration['clients'].items():
        identifier = client.get('entity_id', name)
        existing = request('GET', '/admin/realms/company/clients?' + urlencode({'clientId': identifier}), token=token)
        if not existing and identifier != name:
            existing = request('GET', '/admin/realms/company/clients?' + urlencode({'clientId': name}), token=token)
        value = {'clientId': name, 'name': name, 'enabled': True,
                 'protocol': 'openid-connect', 'publicClient': False,
                 'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
                 'secret': client['secret'], 'redirectUris': client['redirects'],
                 'webOrigins': [], 'attributes': {'post.logout.redirect.uris': '+'},
                 'protocolMappers': [{
                     'name': attribute, 'protocol': 'openid-connect',
                     'protocolMapper': 'oidc-usermodel-attribute-mapper',
                     'config': {'user.attribute': attribute, 'claim.name': attribute,
                                'jsonType.label': 'String', 'id.token.claim': 'true',
                                'access.token.claim': 'true', 'userinfo.token.claim': 'true'},
                 } for attribute in ('employee_id', 'department', 'manager')]}
        if client.get('protocol') == 'saml':
            value = {'clientId': identifier, 'name': name, 'enabled': True,
                     'protocol': 'saml', 'redirectUris': client['redirects'],
                     'attributes': {'saml.client.signature': 'false',
                                    'saml.server.signature': 'true',
                                    'saml.assertion.signature': 'true',
                                    'saml.authnstatement': 'true',
                                    'saml.force.post.binding': 'true',
                                    'saml_name_id_format': 'email',
                                    'saml_force_name_id_format': 'true'},
                     'protocolMappers': [{
                         'name': attribute, 'protocol': 'saml',
                         'protocolMapper': 'saml-user-attribute-mapper' if attribute == 'employee_id' else 'saml-user-property-mapper',
                         'config': {'user.attribute': attribute, 'attribute.name': attribute,
                                    'friendly.name': attribute, 'attribute.nameformat': 'Basic'},
                     } for attribute in ('employee_id', 'email', 'firstName', 'lastName')]}
        if existing:
            request('PUT', '/admin/realms/company/clients/' + existing[0]['id'], value, token)
        else:
            request('POST', '/admin/realms/company/clients', value, token)
        if client.get('protocol') == 'saml':
            current = existing or request('GET', '/admin/realms/company/clients?' + urlencode({
                'clientId': identifier}), token=token)
            scopes_url = '/admin/realms/company/clients/' + current[0]['id'] + '/default-client-scopes'
            for scope in request('GET', scopes_url, token=token):
                # Application roles are managed locally. The default role-list
                # mapper emits repeated names rejected by strict SAML clients.
                if scope['name'] == 'role_list':
                    request('DELETE', scopes_url + '/' + scope['id'], token=token)
    print('Company identity provider and application clients are ready.', flush=True)


if __name__ == '__main__':
    main()
