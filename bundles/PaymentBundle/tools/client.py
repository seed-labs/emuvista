"""Payment customer API client, also used by world-level authorization workflows."""

from emuvista_agent.http import request


def configuration(context):
    """The payment tools own endpoint paths and ports, not the model."""
    account = context.accounts['payment']
    providers = context.tool_config['payment']
    instance = account.get('instance') or next(iter(providers))
    provider = providers[instance]
    email = account.get('email', context.accounts['email']['email'])
    wallets = provider['wallets'][account['group']]
    config = {**provider, **account, 'email': email,
              'account': wallets[email], 'recipients': wallets}
    origin = config['url'].rstrip('/')
    config.setdefault('authURL', origin + ':2026')
    config.setdefault('accountingURL', origin + ':2025/' + config.get('group', 'SEED'))
    return config


def connection(context):
    config = configuration(context)
    token = request({**config, 'url': config['authURL']}, '/token', method='POST', form=True,
                    body={'grant_type': 'password', 'client_id': 'komunitin-app', 'username': config['email'],
                          'password': config['password'], 'scope': 'email accounting:read accounting:write'})['access_token']
    return config, {'Authorization': 'Bearer ' + token}


def bank_request(context, path, body=None):
    config, headers = connection(context)
    return request({**config, 'url': config['accountingURL']}, '/bank' + path,
                   method='GET' if body is None else 'POST', body=body, headers=headers)


def recipient(context, email):
    account = configuration(context)['recipients'].get(email)
    if not account:
        raise ValueError('Recipient is not in the world directory')
    return account
