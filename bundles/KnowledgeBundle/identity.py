"""Provision knowledge accounts through the native administrative API."""

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def provision(person, configuration):
    headers = {'Authorization': 'Token ' + configuration['token_id'] + ':' + configuration['token_secret'],
               'Content-Type': 'application/json'}
    url = configuration['url'] + '/api/users'
    query = urlencode({'filter[external_auth_id]': person['id']})
    with urlopen(Request(url + '?' + query, headers=headers), timeout=20) as response:
        users = json.load(response)['data']
    value = {'name': person['firstName'] + ' ' + person['lastName'],
             'email': person['email'], 'external_auth_id': person['id']}
    target = url + '/' + str(users[0]['id']) if users else url
    if not users:
        roles_url = configuration['url'] + '/api/roles?' + urlencode({'filter[display_name]': 'Editor'})
        with urlopen(Request(roles_url, headers=headers), timeout=20) as response:
            value['roles'] = [json.load(response)['data'][0]['id']]
    with urlopen(Request(target, data=json.dumps(value).encode(), headers=headers,
                         method='PUT' if users else 'POST'), timeout=20) as response:
        response.read()
