"""Bank customer queries through each resident's own authenticated session."""

from emuvista_agent.http import request
from .client import connection


def read(context, path, bank=None):
    config, opener, headers = connection(context, bank)
    return request(config, '/api/v1/' + path, opener=opener, headers=headers)


def accounts(arguments, context):
    return read(context, 'savings', arguments.get('bank'))


def cards(arguments, context):
    return read(context, 'cards', arguments.get('bank'))


def card_payments(arguments, context):
    return read(context, 'card-payments', arguments.get('bank'))


def products(arguments, context):
    return read(context, 'customer-accounts/products', arguments.get('bank'))


def open_account(arguments, context):
    config, opener, headers = connection(context, arguments.get('bank'))
    return request(config, '/api/v1/customer-accounts', method='POST', opener=opener, headers=headers,
                   body={'productId': arguments['productId'], 'id': arguments['id']})


def issue_card(arguments, context):
    config, opener, headers = connection(context, arguments.get('bank'))
    return request(config, '/api/v1/cards', method='POST', opener=opener, headers=headers,
                   body={'accountId': arguments['accountId'], 'id': arguments['id']})
