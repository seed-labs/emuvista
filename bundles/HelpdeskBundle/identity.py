"""Provision service-desk identities through its native REST API."""

import base64
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def provision(person, configuration):
    credentials = (configuration['user'] + ':' + configuration['password']).encode()
    headers = {'Authorization': 'Basic ' + base64.b64encode(credentials).decode(),
               'App-Token': configuration['app_token'], 'Content-Type': 'application/json'}
    base = configuration['url'] + '/apirest.php'
    with urlopen(Request(base + '/initSession', headers=headers), timeout=20) as response:
        headers['Session-Token'] = json.load(response)['session_token']
    query = urlencode({'searchText[registration_number]': person['id'], 'range': '0-999'})
    with urlopen(Request(base + '/User?' + query, headers=headers), timeout=20) as response:
        users = json.load(response)
    value = {'name': person['id'].lower(), 'registration_number': person['id'],
             'firstname': person['firstName'], 'realname': person['lastName'],
             '_useremails': [person['email']], 'is_active': int(person.get('active', True)), 'authtype': 4}
    if users:
        value['id'] = users[0]['id']
        with urlopen(Request(base + '/User/' + str(value['id']) + '/UserEmail', headers=headers), timeout=20) as response:
            emails = json.load(response)
        if emails:
            selected = next((row for row in emails if row['email'] == person['email']),
                            next((row for row in emails if row.get('is_default')), emails[0]))
            value['_useremails'] = {str(selected['id']): person['email']}
            value['_default_email'] = selected['id']
    with urlopen(Request(base + '/User', data=json.dumps({'input': value}).encode(), headers=headers,
                         method='PUT' if users else 'POST'), timeout=20) as response:
        response.read()
    with urlopen(Request(base + '/killSession', headers=headers), timeout=20) as response:
        response.read()
