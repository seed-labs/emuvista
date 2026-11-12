"""Compose independent wallet and bank customer APIs for explicit user card linking."""

import re
from urllib.parse import urlsplit


def link_card(arguments, context):
    bank = arguments['bank']
    number = re.sub(r'[ -]', '', arguments['cardNumber'])
    if not re.fullmatch(r'[0-9]{16,19}', number):
        raise ValueError('A full card number is required')
    # Calling the provider tools initializes their installed package namespaces.
    # Protocol clients are imported from those copied packages, never the repository.
    providers = context.tools.invoke('payment.banks', {}, source='card_link')['banks']
    if bank not in {provider['id'] for provider in providers}:
        raise ValueError('Bank is not offered by the payment service')
    own_cards = context.tools.invoke('bank.cards', {'bank': bank}, source='card_link')
    selected = next((card for card in own_cards if card['number'] == number), None)
    if selected is None:
        raise ValueError('Card does not belong to this agent at the selected bank')
    if selected['status'] != 'active':
        raise ValueError('Card is not active')

    from emuvista_tools_payment.client import bank_request, configuration
    from emuvista_tools_bank.client import authorize_card

    payment = configuration(context)
    redirect = payment.get('redirectURI', payment['url'].rstrip('/') + '/bank-accounts')
    target, base = urlsplit(redirect), urlsplit(payment['url'])
    if (target.scheme != 'http' or target.netloc != base.netloc
            or target.path != '/bank-accounts' or target.query or target.fragment):
        raise ValueError('Card callback must use this payment service inside the emulator')
    prepared = bank_request(context, '/links', {
        'bank': bank, 'cardNumber': number, 'redirectURI': redirect,
    })
    # Authorization codes, OTPs and cookies stay inside these clients.
    callback = authorize_card(
        context, bank, prepared['authorizationURL'], redirect, selected['cardId'])
    linked = bank_request(context, '/links/complete', callback)
    sources = bank_request(context, '/sources')['sources']
    source = next((source for source in sources if source['id'] == linked['id']), None)
    return {'status': 'linked', 'linked': True, 'source': linked['id'], 'bank': bank,
            'maskedCard': number[-4:], 'available': source['available'] if source else False}
