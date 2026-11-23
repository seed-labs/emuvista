"""Marketplace tools authenticate as the resident, never as the shop administrator."""
from emuvista_agent.http import basic, request


def shop_request(context, path, body=None):
    account = context.accounts['shop']
    providers = context.tool_config['shop']
    provider = providers[account.get('instance') or next(iter(providers))]
    email = account.get('email', context.accounts['email']['email'])
    return request({**provider, 'url': provider['url'] + '/wp-json/emuvista/v1', 'timeout': 120}, path,
                   method='GET' if body is None else 'POST', body=body,
                   headers={'Authorization': basic(email, account['password'])})


def catalog(arguments, context):
    return shop_request(context, '/catalog')


def open_store(arguments, context):
    return shop_request(context, '/stores', arguments)


def publish(arguments, context):
    return shop_request(context, '/products', arguments)


def order(arguments, context):
    return shop_request(context, '/orders', arguments)


def checkout(arguments, context):
    return shop_request(context, f'/orders/{arguments["order"]}/checkout', {})


def pay(arguments, context):
    context.tools.invoke('payment.banks', {}, source='checkout')
    from emuvista_tools_payment.client import connection
    checkout = shop_request(context, f'/orders/{arguments["order"]}/checkout', {})
    if checkout.get('status') == 'paid':
        return orders({}, context)
    config, headers = connection(context)
    if checkout['group'] != config['group']:
        raise ValueError('Order currency community does not match your payment wallet')
    receipt = request({'url': config['accountingURL'], 'timeout': 120},
                      '/checkout/sessions/' + checkout['id'] + '/pay', method='POST', headers=headers,
                      body={'payer': config['account'], 'source': arguments.get('source', 'balance')})
    result = orders({}, context)
    return {'payment': receipt, 'orders': result['orders']}


def orders(arguments, context):
    return shop_request(context, '/orders')


def sales(arguments, context):
    return shop_request(context, '/sales')


def downloads(arguments, context):
    return shop_request(context, '/downloads')


def read_download(arguments, context):
    return shop_request(context, f'/downloads/{arguments["product"]}')
