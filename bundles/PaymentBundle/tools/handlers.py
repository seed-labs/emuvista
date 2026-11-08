"""Native wallet APIs using only this agent's payment identity."""
import uuid
import re
from urllib.parse import urlencode
from emuvista_agent.http import request
from .client import bank_request, connection, recipient


def balance(arguments,context):
    config,headers=connection(context)
    data=request({**config,'url':config['accountingURL']},'/accounts/'+config['account'],headers=headers)['data']
    return {'account':config['account'],'balanceMinor':data['attributes']['balance'],'currency':'USD'}


def transfer(arguments,context):
    config,headers=connection(context)
    payee=recipient(context,arguments['recipient'])
    identifier=arguments['id']
    uuid.UUID(identifier)
    data={'data':{'type':'transfers','id':identifier,'attributes':{'state':'committed',
        'amount':arguments['amountMinor'],'meta':{'description':arguments['description']}},
        'relationships':{'payer':{'data':{'type':'accounts','id':config['account']}},
                         'payee':{'data':{'type':'accounts','id':payee}}}}}
    response=request({**config,'url':config['accountingURL']},'/transfers',method='POST',headers=headers,body=data)
    return {'id':response['data']['id'],'state':response['data']['attributes']['state']}


def banks(arguments, context):
    return bank_request(context, '/providers')


def cards(arguments, context):
    return bank_request(context, '/sources')


def card_payments(arguments, context):
    if 'id' in arguments and str(uuid.UUID(arguments['id'])) != arguments['id']:
        raise ValueError('Payment id must be a canonical UUID')
    payments = bank_request(context, '/payments')['payments']
    if 'id' in arguments:
        return {'payments': [payment for payment in payments if payment['id'] == arguments['id']]}
    return {'payments': payments[:20]}


def card_payment(arguments, context):
    identifier = arguments['id']
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError('Payment id must be a canonical UUID')
    if not re.fullmatch(r'[a-f0-9]{32}', arguments['source']):
        raise ValueError('Source must be a linked card identifier from payment.cards')
    config = context.service('payment')
    # Ownership, card availability and currency are checked by the payment/bank APIs.
    return bank_request(context, '/payments', {
        'id': identifier, 'source': arguments['source'], 'payer': config['account'],
        'payee': recipient(context, arguments['recipient']),
        'amountMinor': arguments['amountMinor'], 'description': arguments['description'],
    })


def _receipt(resource, config):
    attributes = resource['attributes']
    relationships = resource['relationships']
    return {'id': resource['id'], 'state': attributes['state'],
            'amountMinor': attributes['amount'], 'currency': config.get('currency', 'USD'),
            'payer': relationships['payer']['data']['id'], 'payee': relationships['payee']['data']['id'],
            'meta': attributes.get('meta') or {}}


def receipt(arguments, context):
    identifier = arguments['id']
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError('Transfer id must be a canonical UUID')
    config, headers = connection(context)
    resource = request({**config, 'url': config['accountingURL']}, '/transfers/'+identifier, headers=headers)['data']
    return _receipt(resource, config)


def history(arguments, context):
    config, headers = connection(context)
    query = urlencode({'filter[account]': config['account'], 'sort': '-created'})
    resources = request({**config, 'url': config['accountingURL']}, '/transfers?'+query, headers=headers)['data']
    return {'transfers': [_receipt(resource, config) for resource in resources[:20]]}
