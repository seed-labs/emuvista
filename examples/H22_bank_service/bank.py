#!/usr/bin/env python3
"""Deploy customer and staff banking with H21's SMTP/IMAP email infrastructure."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from examples.H21_email_service.email_service import add_mail_records
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator
from bundles.BankBundle import BankBundle
from bundles.EmailBundle import EmailBundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('bank.json'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Save and resume bank, mailbox and DNS state')
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve() or args.output.resolve() in args.state.resolve().parents):
        parser.error('state must be outside output')
    initial = json.loads(args.config.read_text())
    mailbox = json.loads((ROOT/'examples/H21_email_service/mailboxes.json').read_text())
    users = {user['email']: user for user in mailbox['users']}
    for customer in initial['customers']:
        if customer.get('email'):
            users[customer['email']] = {'email': customer['email'], 'password': customer['emailPassword']}
    sender = initial['email']
    users[sender['address']] = {'email': sender['address'], 'password': sender['password']}
    mailbox['users'] = list(users.values())
    mailbox['domains'] = sorted(set(mailbox['domains']) | {user['email'].split('@')[1] for user in mailbox['users']})

    emu = build_emulator(dnssec=True, dnssec_key_store=args.state.resolve()/'dnssec' if args.state else None)
    add_mail_records(emu, mailbox)
    emu.getLayer('DomainNameService').getRootZone().addRecord('bank.seed.example. A 10.151.0.10')
    emu.render()
    email = EmailBundle(emu, resolver=DNS_RESOLVER).setInitialConfiguration(mailbox).enableHostAccess(8445)
    email.addInternalNetwork('150', 'net0', [f'10.150.0.{i}' for i in range(10, 18)], '10.150.0.254')
    bank = BankBundle(emu, resolver=DNS_RESOLVER).setInitialConfiguration(initial).enableHostAccess(8444)
    bank.addInternalNetwork('151', 'net0',
        [f'10.151.0.{i}' for i in range(10, 10+len(bank.getContainers()))], '10.151.0.254')
    bank.setEmailServer(mailbox['hostname'], sender['address'], sender['password'], 'email/config/cert.pem')
    if args.state:
        email.setSavePath(args.state/'email')
        bank.setSavePath(args.state/'bank')
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=True)
    compiler.addContainerBundle(email)
    compiler.addContainerBundle(bank)
    emu.compile(compiler, str(args.output.resolve()), override=True)
    (args.output/'.env').write_text('COMPOSE_PROJECT_NAME=h22-bank\n')
    print('Bank: https://localhost:8444')
    print('Bank administration: https://localhost:8446')
    print('Webmail: https://localhost:8445/webmail/')
    print('Internet Map: http://localhost:8080')
    print('Next: cd output; docker compose build; docker compose up -d')


if __name__ == '__main__':
    main()
