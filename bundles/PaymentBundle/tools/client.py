"""Payment customer API client, also used by world-level authorization workflows."""

from emuvista_agent.http import request


def connection(context):
    config = context.service('payment')
    token = request({**config, 'url': config['authURL']}, '/token', method='POST', form=True,
        body={'grant_type': 'password', 'client_id': 'komunitin-app', 'username': config['email'],
              'password': config['password'], 'scope': 'email accounting:read accounting:write'})['access_token']
    return config, {'Authorization': 'Bearer '+token}


def bank_request(context, path, body=None):
    config, headers = connection(context)
    return request({**config, 'url': config['accountingURL']}, '/bank'+path,
                   method='GET' if body is None else 'POST', body=body, headers=headers)


def recipient(context, email):
    account = context.service('world')['wallets'].get(email)
    if not account:
        raise ValueError('Recipient is not in the world directory')
    return account
