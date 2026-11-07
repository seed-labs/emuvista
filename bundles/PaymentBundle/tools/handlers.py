"""Native wallet APIs using only this agent's payment identity."""
import uuid
from emuvista_agent.http import request


def connection(context):
    config=context.service('payment')
    token=request({**config,'url':config['authURL']},'/token',method='POST',form=True,
        body={'grant_type':'password','client_id':'komunitin-app','username':config['email'],
              'password':config['password'],'scope':'email accounting:read accounting:write'})['access_token']
    return config,{'Authorization':'Bearer '+token}


def balance(arguments,context):
    config,headers=connection(context)
    data=request({**config,'url':config['accountingURL']},'/accounts/'+config['account'],headers=headers)['data']
    return {'account':config['account'],'balanceMinor':data['attributes']['balance'],'currency':'USD'}


def transfer(arguments,context):
    config,headers=connection(context)
    recipient=context.service('world')['wallets'].get(arguments['recipient'])
    if not recipient:raise ValueError('recipient is not in the world directory')
    identifier=arguments['id']
    uuid.UUID(identifier)
    data={'data':{'type':'transfers','id':identifier,'attributes':{'state':'committed',
        'amount':arguments['amountMinor'],'meta':{'description':arguments['description']}},
        'relationships':{'payer':{'data':{'type':'accounts','id':config['account']}},
                         'payee':{'data':{'type':'accounts','id':recipient}}}}}
    response=request({**config,'url':config['accountingURL']},'/transfers',method='POST',headers=headers,body=data)
    return {'id':response['data']['id'],'state':response['data']['attributes']['state']}
