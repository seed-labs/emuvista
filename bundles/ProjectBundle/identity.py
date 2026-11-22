"""Provision project users through the native API v3."""

import base64
import json
from urllib.request import Request, urlopen


def provision(person, configuration):
    headers = {'Authorization': 'Basic ' + base64.b64encode(('apikey:' + configuration['token']).encode()).decode(),
               'Host': configuration['host'], 'Content-Type': 'application/json'}
    url = configuration['url'] + '/api/v3/users'
    with urlopen(Request(url + '?pageSize=1000', headers=headers), timeout=20) as response:
        directory = json.load(response)['_embedded']['elements']
    users = [user for user in directory if user.get('login') == person['id'].lower()]
    value = {'login': person['id'].lower(), 'firstName': person['firstName'],
             'lastName': person['lastName'], 'email': person['email'],
             'status': 'active' if person.get('active', True) else 'locked'}
    source = next(user['_links']['auth_source'] for user in directory
                  if user['_links'].get('auth_source', {}).get('title') == configuration['auth_source'])
    value['_links'] = {'authSource': {'href': source['href']}}
    target = configuration['url'] + users[0]['_links']['self']['href'] if users else url
    with urlopen(Request(target, data=json.dumps(value).encode(), headers=headers,
                         method='PATCH' if users else 'POST'), timeout=20) as response:
        response.read()
