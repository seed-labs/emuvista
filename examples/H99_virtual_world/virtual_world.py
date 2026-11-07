#!/usr/bin/env python3
"""A shared digital world with email, payment and banks."""

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator
from examples.H21_email_service.email_service import add_mail_records
from bundles.BankBundle import BankBundle
from bundles.EmailBundle import EmailBundle
from bundles.PaymentBundle import PaymentBundle

HERE = Path(__file__).resolve().parent


class VirtualWorld:
    def __init__(self, config=None, state=None, dnssec=True):
        self.config = json.loads(Path(config or HERE/'world.json').read_text())
        self.state = Path(state).resolve() if state else None
        self.emu = build_emulator(dnssec=dnssec,
            dnssec_key_store=self.state/'dnssec' if self.state and dnssec else None)
        self.bundles = []
        self.catalog = {
            'payment': {'url':'https://10.152.0.10', 'authURL':'https://10.152.0.10:2026', 'accountingURL':'https://10.152.0.10:2025/SEED', 'caFile':'/etc/world-certs/payment.pem'},
            'email': {'url':'https://mail.seed.example', 'hostname':'mail.seed.example', 'caFile':'/etc/world-certs/email.pem'},
            'seed-bank': {'url':'https://10.151.0.10', 'sender':'bank@seed.example', 'caFile':'/etc/world-certs/seed-bank.pem'},
            'north-bank': {'url':'https://10.153.0.10', 'sender':'north-bank@seed.example', 'caFile':'/etc/world-certs/north-bank.pem'},
        }
        self._mail()
        self.payment=PaymentBundle(self.emu).setAdminCredentials('admin@payment.example','PaymentAdmin123!')
        self.payment.setInitialConfiguration(self.config['payment'])

    def _mail(self):
        mail = json.loads((ROOT/'examples/H21_email_service/mailboxes.json').read_text())
        users = {u['email']:u for u in mail['users']}
        for bank in self.config['banks']:
            for user in bank['configuration']['customers']:
                if user.get('email'):users[user['email']]={'email':user['email'],'password':user['emailPassword']}
            sender = bank['configuration']['email']
            users[sender['address']]={'email':sender['address'],'password':sender['password']}
        mail['users']=list(users.values())
        mail['domains']=sorted(set(mail['domains'])|{u.split('@')[1] for u in users})
        add_mail_records(self.emu,mail)
        self.mail = mail

    def prepare_bundles(self):
        email = EmailBundle(self.emu,resolver=DNS_RESOLVER).setInitialConfiguration(self.mail).enableHostAccess(8445)
        payment = self.payment.enableHostAccess(8443)
        for name,bundle,asn in [('email',email,150),('payment',payment,152)]:
            bundle.addInternalNetwork(str(asn),'net0',[f'10.{asn}.0.{i}' for i in range(10,10+len(bundle.getContainers()))],f'10.{asn}.0.254')
            if self.state:bundle.setSavePath(self.state/name)
        self.bundles=[email,payment]
        providers,certificates,dependencies=[],[],[]
        for settings in self.config['banks']:
            bank = BankBundle(self.emu,name=settings['id'],resolver=DNS_RESOLVER)
            bank.setInitialConfiguration(settings['configuration']).enableHostAccess(settings['port'],staff_port=settings['staffPort'])
            sender=settings['configuration']['email']
            bank.setEmailServer(self.mail['hostname'],sender['address'],sender['password'],'email/config/cert.pem')
            asn=settings['asn']
            bank.addInternalNetwork(str(asn),'net0',[f'10.{asn}.0.{i}' for i in range(10,10+len(bank.getContainers()))],f'10.{asn}.0.254')
            if self.state:bank.setSavePath(self.state/settings['id'])
            callbacks=['https://localhost:8443/bank-accounts','https://127.0.0.1:8443/bank-accounts','https://10.152.0.10/bank-accounts']
            settlement=settings['connection']
            bank.registerAPIClient('payment-wallet',callbacks,settlement['settlementBankAccount'])
            connection=bank.getOpenBankingConnection()
            provider={key:connection[key] for key in ('apiURL','browserURL','clientId','clientSecret','redirectURIs')}
            provider.update(id=settings['id'],name=settings['name'],group=settlement['group'],currency=settlement['currency'],settlementWallet=payment.getInitialAccountId(settlement['group'],settlement['settlementEmail']))
            providers.append(provider)
            certificates.append('./'+connection['certificate'])
            dependencies.extend(connection['readyServices'])
            self.bundles.append(bank)
        payment.configureApplication('accounting',environment={'BANK_PROVIDER_CONFIG':'/payment-config/providers.json'},files={'providers.json':json.dumps(providers)+'\n'},trusted_certificates=certificates,dependencies=dependencies)
        payment.configureApplication('app',environment={'BANK_FUNDING_ENABLED':'true'})

    def compile(self, output, project='h99-world', after_render=None):
        output=Path(output).resolve()
        if self.state and (self.state==output or output in self.state.parents):
            raise ValueError('state must be outside output')
        self.emu.render()
        if after_render:after_render(self)
        self.prepare_bundles()
        compiler=Docker(platform=Platform.AMD64,internetMapEnabled=True)
        for bundle in self.bundles:compiler.addContainerBundle(bundle)
        self.emu.compile(compiler,str(output),override=True)
        certs=output/'world-certs'
        certs.mkdir()
        for name,source in [('email','email/config/cert.pem'),('payment','payment/config/server.crt'),*[(b['id'],b['id']+'/config/server.crt') for b in self.config['banks']]]:
            certificate=certs/(name+'.pem')
            shutil.copyfile(output/source,certificate)
            certificate.chmod(0o644)
        (output/'.env').write_text('COMPOSE_PROJECT_NAME='+project+'\n')
        (output/'world.json').write_text(json.dumps({'services':self.catalog},indent=2)+'\n')
        print('World compiled: '+str(output))
        print('Payment 8443; banks 8444/8447; webmail 8445; map 8080')


def build_world(config=None,state=None,**kwargs):
    return VirtualWorld(config,state,**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=HERE/'world.json')
    parser.add_argument('--output',type=Path,default=Path('output'))
    parser.add_argument('--state',type=Path)
    args=parser.parse_args()
    build_world(args.config,args.state).compile(args.output)
    print('Next: cd '+str(args.output)+' && docker compose build && docker compose up -d')


if __name__=='__main__':main()
