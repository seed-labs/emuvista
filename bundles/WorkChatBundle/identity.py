"""Provision chat identities through the native administration API."""

from base64 import b64encode
import json
import secrets
import ssl
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def provision(person, settings):
    def call(method, path, values=None):
        authorization = b64encode((settings['email'] + ':' + settings['api_key']).encode()).decode()
        headers = {'Authorization': 'Basic ' + authorization, 'Host': settings['host'],
                   'Content-Type': 'application/x-www-form-urlencoded'}
        body = urlencode(values).encode() if values is not None else None
        with urlopen(Request(settings['url'] + '/api/v1/' + path, data=body,
                             headers=headers, method=method), timeout=30,
                     context=ssl._create_unverified_context()) as response:
            result = json.load(response)
        if result['result'] != 'success':
            raise RuntimeError(result['msg'])
        return result

    fields = call('GET', 'realm/profile_fields')['custom_fields']
    field = next(value['id'] for value in fields if value['name'] == 'Employee ID')
    users = call('GET', 'users?include_custom_profile_fields=true')['members']
    user = next((user for user in users if user.get('profile_data', {}).get(str(field), {}).get('value') == person['id']), None)
    values = {'full_name': person['firstName'] + ' ' + person['lastName'],
              'profile_data': json.dumps([{'id': field, 'value': person['id']}])}
    if user:
        call('PATCH', 'users/' + str(user['user_id']), values)
        # Email changes use the dedicated administrator operation.
        if (user.get('delivery_email') or user['email']) != person['email']:
            call('PATCH', 'users/' + str(user['user_id']), {'new_email': person['email']})
        if user['is_active'] != person.get('active', True):
            call('POST' if person.get('active', True) else 'DELETE',
                 'users/' + str(user['user_id']) + ('/reactivate' if person.get('active', True) else ''))
    else:
        created = call('POST', 'users', {'email': person['email'],
                       'password': secrets.token_urlsafe(32), 'full_name': values['full_name']})
        call('PATCH', 'users/' + str(created['user_id']), values)
