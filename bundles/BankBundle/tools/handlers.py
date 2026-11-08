"""Bank customer queries through each resident's own authenticated session."""

from emuvista_agent.http import request
from .client import connection


def read(context, path, bank=None):
    config, opener, headers = connection(context, bank)
    return request(config, '/api/v1/'+path, opener=opener, headers=headers)


def accounts(arguments, context):
    return read(context, 'savings', arguments.get('bank'))


def cards(arguments, context):
    return read(context, 'cards', arguments.get('bank'))


def loans(arguments, context):
    return read(context, 'loans', arguments.get('bank'))
