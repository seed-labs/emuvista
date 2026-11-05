#!/usr/bin/env python3
"""Bank-funded and wallet-funded payments on the mini Internet."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from examples.H21_email_service.email_service import add_mail_records
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator
from services.BankService import BankBundle
from services.EmailService import EmailBundle
from services.PaymentService import PaymentBundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('scenario.json'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Save and resume bank, payment, email and DNS state')
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve() or args.output.resolve() in args.state.resolve().parents):
        parser.error('state must be outside output')
    scenario = json.loads(args.config.read_text())
    mailbox = json.loads((ROOT/'examples/H21_email_service/mailboxes.json').read_text())
    users = {u['email']: u for u in mailbox['users']}
    for customer in scenario['bank']['customers']:
        if customer.get('email'):
            users[customer['email']] = {'email': customer['email'], 'password': customer['emailPassword']}
    sender = scenario['bank']['email']
    users[sender['address']] = {'email': sender['address'], 'password': sender['password']}
    mailbox['users'] = list(users.values())
    mailbox['domains'] = sorted(set(mailbox['domains']) | {u['email'].split('@')[1] for u in mailbox['users']})

    emu = build_emulator(dnssec=True, dnssec_key_store=args.state.resolve()/'dnssec' if args.state else None)
    add_mail_records(emu, mailbox)
    emu.render()
    email = EmailBundle(emu, resolver=DNS_RESOLVER).setInitialConfiguration(mailbox).enableHostAccess(8445)
    bank = BankBundle(emu, resolver=DNS_RESOLVER).setInitialConfiguration(scenario['bank']).enableHostAccess(8444, staff_port=8446)
    bank.setEmailServer(mailbox['hostname'], sender['address'], sender['password'], 'email/config/cert.pem')
    payment = PaymentBundle(emu).setAdminCredentials('admin@payment.example', 'PaymentAdmin123!')
    payment.setInitialConfiguration(scenario['payment']).enableHostAccess(8443)
    for bundle, asn in ((email, 150), (bank, 151), (payment, 152)):
        bundle.addInternalNetwork(str(asn), 'net0',
            [f'10.{asn}.0.{i}' for i in range(10, 10+len(bundle.getContainers()))], f'10.{asn}.0.254')
    if args.state:
        for name, bundle in (('email', email), ('bank', bank), ('payment', payment)):
            bundle.setSavePath(args.state/name)

    settings = scenario['connection']
    callbacks = ['https://localhost:8443/bank-accounts',
                 'https://127.0.0.1:8443/bank-accounts',
                 'https://10.152.0.10/bank-accounts']
    bank.registerAPIClient('payment-wallet', callbacks, settings['settlementBankAccount'])
    connection = bank.getOpenBankingConnection()
    provider = {key: connection[key] for key in
                ('apiURL', 'browserURL', 'clientId', 'clientSecret', 'redirectURIs')}
    provider.update({'id': 'seed-bank', 'name': 'SEED Bank',
                     'group': settings['group'], 'currency': settings['currency'],
                     'settlementWallet': payment.getInitialAccountId(settings['group'], settings['settlementEmail'])})
    payment.configureApplication('accounting',
        environment={'BANK_PROVIDER_CONFIG': '/payment-config/providers.json'},
        files={'providers.json': json.dumps([provider])+'\n'},
        trusted_certificates=['./'+connection['certificate']],
        dependencies=connection['readyServices'])
    payment.configureApplication('app', environment={'BANK_FUNDING_ENABLED': 'true'})
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=True)
    for bundle in (email, payment, bank):
        compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(args.output.resolve()), override=True)
    (args.output/'.env').write_text('COMPOSE_PROJECT_NAME=h23-bank-payment\n')
    print('Link a bank account: https://localhost:8443/bank-accounts')
    print('Payment: https://localhost:8443/login-mail')
    print('Bank: https://localhost:8444')
    print('Bank administration: https://localhost:8446')
    print('Webmail: https://localhost:8445/webmail/')
    print('Internet Map: http://localhost:8080')
    print('Next: cd output; docker compose build; docker compose up -d')


if __name__ == '__main__':
    main()
