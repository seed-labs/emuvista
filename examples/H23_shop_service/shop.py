#!/usr/bin/env python3
"""Deploy a marketplace with Payment, bank cards and email on mini Internet."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.containerBundle import InternetMap
from seedemu.core import Binding, Filter
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator, host_zone
from bundles.EmailBundle import EmailBundle
from bundles.PaymentBundle import PaymentBundle
from bundles.BankBundle import BankBundle
from services.ShopService import ShopService

HERE = Path(__file__).resolve().parent


def createworld(state=None):
    initial = json.loads((HERE / 'shop.json').read_text())
    emu = build_emulator()
    email = EmailBundle(emu, resolver=DNS_RESOLVER).setHostname('mail.com')
    email.setInitialConfiguration(initial['email']).enableHostAccess(8445)
    payment = PaymentBundle(emu, resolver=DNS_RESOLVER).setHostname('payment.com')
    payment.setInitialConfiguration(initial['payment']).enableHostAccess(8443)
    bank = BankBundle(emu, resolver=DNS_RESOLVER).setHostname('southbank.com')
    bank.setInitialConfiguration(initial['bank']).enableHostAccess(8444, staff_port=8446)
    shops = ShopService(resolver=DNS_RESOLVER)
    shop = shops.install('shop').setHostname('shop.com')
    emu.addLayer(shops)
    emu.getLayer('Base').getAutonomousSystem(154).createHost('shop').joinNetwork(
        'net0', address='10.154.0.10')
    emu.addBinding(Binding('shop', filter=Filter(asn=154, nodeName='shop')))
    shop.setInitialConfiguration(initial['shop']).enableHostAccess(8449)
    bank.connectEmail(email)
    payment.connectEmail(email).connectBank(bank)
    shop.connectEmail(email).connectPayment(payment)
    systems = {'email': email, 'payment': payment, 'bank': bank, 'shop': shop}
    for person in initial['shop']['users']:
        person['wallet'] = payment.getInitialAccountId('SEED', person['email'])
    for name, hostname, asn in [('email', 'mail.com', 150), ('payment', 'payment.com', 152),
                                ('bank', 'southbank.com', 151), ('shop', 'shop.com', 154)]:
        host_zone(emu, hostname).addRecord(f'@ A 10.{asn}.0.10')
        if state:
            systems[name].setSavePath(Path(state) / name)
    host_zone(emu, 'southbank.com').addRecord('staff A 10.151.0.18')
    host_zone(emu, 'mail.com').addRecord('@ MX 10 mail.com.')
    return emu, systems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Save and resume application state outside output')
    args = parser.parse_args()
    emu, systems = createworld(args.state)
    emu.render()
    compiler = Docker(platform=Platform.AMD64)
    internet_map = InternetMap(emu)
    internet_map.setPorts([8083, 8080, 8084])
    compiler.addContainerBundle(internet_map)
    for name, asn in [('email', 150), ('payment', 152), ('bank', 151)]:
        bundle = systems[name]
        bundle.addInternalNetwork(str(asn), 'net0',
                                  [f'10.{asn}.0.{i}' for i in range(10, 10 + len(bundle.getContainers()))])
        compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
