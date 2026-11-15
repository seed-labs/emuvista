"""A resident's personal inventory and orders; money and delivery use real services."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
from emuvista_agent.http import request

_lock = threading.RLock()


def catalog(arguments, context):
    return {'shops': [request(provider, '/catalog')
                      for provider in context.tool_config.get('shop', {}).values()]}


def _owned(context):
    config = context.possessions.get('shop', {})
    if not config.get('products'):
        raise ValueError('You do not own this inventory; contact the seller by email')
    return {**config, 'directory': context.config['framework']['state_directory'] + '/shop'}


def _path(config):
    directory = Path(config['directory'])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / 'orders.json'


def _load(config):
    path = _path(config)
    return json.loads(path.read_text()) if path.exists() else {}


def _save(config, orders):
    path = _path(config)
    descriptor, temporary = tempfile.mkstemp(prefix='.orders-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(orders, output)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def quote(arguments, context):
    config = _owned(context)
    buyer = arguments['buyer']
    if buyer == config['seller'] or buyer not in context.knowledge['emails']:
        raise ValueError('Choose another resident as the buyer')
    product = next((product for product in config['products']
                   if product['id'] == arguments['product']), None)
    if not product:
        raise ValueError('Product is not in your inventory')
    identifier = str(uuid.uuid4())
    order = {'id': identifier, 'product': product['id'], 'title': product['title'],
             'seller': config['seller'], 'buyer': buyer, 'amountMinor': arguments.get('priceMinor', product['priceMinor']),
             'currency': product['currency'], 'paymentReference': 'Order ' + identifier, 'status': 'quoted',
             'created': datetime.now(timezone.utc).isoformat()}
    with _lock:
        orders = _load(config)
        orders[identifier] = order
        _save(config, orders)
    return order


def orders(arguments, context):
    config = _owned(context)
    with _lock:
        saved = _load(config)
        if arguments.get('id'):
            if arguments['id'] not in saved:
                raise ValueError('Order not found')
            return saved[arguments['id']]
        return {'orders': sorted(saved.values(), key=lambda order: order['created'], reverse=True)[:30]}


def deliver(arguments, context):
    config = _owned(context)
    with _lock:
        saved = _load(config)
        order = saved.get(arguments['order'])
        if not order:
            raise ValueError('Order not found')
        if order['status'] == 'delivered':
            return {**order, 'alreadyDelivered': True}
        if order['status'] in ('delivering', 'delivery_uncertain'):
            return {**order, 'status': 'delivery_uncertain',
                    'warning': 'Inspect Sent and the recipient before attempting another delivery'}
        receipt = context.tools.invoke(
            'payment.receipt', {'id': arguments['transfer']}, source='shop')
        from emuvista_tools_payment.client import configuration
        payment = configuration(context)
        if (receipt['state'] != 'committed' or receipt['payee'] != payment['account']
                or receipt['amountMinor'] != order['amountMinor'] or receipt['currency'] != order['currency']
                or order['id'] not in receipt.get('meta', {}).get('description', '')):
            raise ValueError('The ledger does not confirm the agreed payment to your wallet')
        payer = payment['recipients'][order['buyer']]
        if receipt['payer'] != payer:
            raise ValueError('Payment does not match this buyer')
        if any(other.get('transfer') == receipt['id'] and other['id'] != order['id'] for other in saved.values()):
            raise ValueError('This payment is already assigned to another order')
        product = next(product for product in config['products']
                       if product['id'] == order['product'])
        order.update(status='delivering', transfer=receipt['id'])
        _save(config, saved)
        try:
            delivery = context.tools.invoke('email.send', {
                'recipient': order['buyer'], 'subject': 'Your purchase: ' + order['title'],
                'body': 'Thank you for your purchase.\nOrder: ' + order['id'] + '\n\n' + product['content'],
            }, source='shop')
            if not delivery.get('sent'):
                raise RuntimeError('Email delivery was not accepted')
        except Exception:
            order['status'] = 'delivery_uncertain'
            _save(config, saved)
            raise RuntimeError(
                'Payment was verified but delivery is uncertain; inspect Sent before retrying') from None
        order.update(status='delivered', messageId=delivery.get(
            'messageId'), savedToSent=delivery.get('savedToSent'))
        _save(config, saved)
        context.emit('sale_completed', order=order['id'], product=order['product'], buyer=order['buyer'],
                     amountMinor=order['amountMinor'], currency=order['currency'], transfer=receipt['id'])
        return order
