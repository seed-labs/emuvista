"""Keep cloud-drive employee profiles aligned with the shared directory."""

import base64
import json
import secrets
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def checked(response):
    value = json.load(response)
    if value['ocs']['meta']['statuscode'] not in (100, 200):
        raise RuntimeError('Cloud account provisioning failed')
    return value


def provision(person, configuration):
    credentials = (configuration['user'] + ':' + configuration['password']).encode()
    headers = {'Authorization': 'Basic ' + base64.b64encode(credentials).decode(),
               'OCS-APIRequest': 'true', 'Content-Type': 'application/x-www-form-urlencoded'}
    base = configuration['url'] + '/ocs/v2.php/cloud/users'
    identifier = person['id']
    url = base + '/' + quote(identifier, safe='')
    try:
        with urlopen(Request(url + '?format=json', headers=headers), timeout=20) as response:
            result = json.load(response)
        exists = result['ocs']['meta']['statuscode'] in (100, 200)
    except HTTPError as error:
        if error.code != 404:
            raise
        exists = False
    if not exists:
        value = urlencode({'userid': identifier, 'password': secrets.token_urlsafe(32),
                           'displayName': person['firstName'] + ' ' + person['lastName'],
                           'email': person['email']}).encode()
        with urlopen(Request(base + '?format=json', data=value, headers=headers, method='POST'), timeout=20) as response:
            checked(response)
    for key, value in {'displayname': person['firstName'] + ' ' + person['lastName'],
                        'email': person['email']}.items():
        body = urlencode({'key': key, 'value': value}).encode()
        with urlopen(Request(url + '?format=json', data=body, headers=headers, method='PUT'), timeout=20) as response:
            checked(response)
    action = 'enable' if person.get('active', True) else 'disable'
    with urlopen(Request(url + '/' + action + '?format=json', headers=headers, method='PUT'), timeout=20) as response:
        checked(response)
