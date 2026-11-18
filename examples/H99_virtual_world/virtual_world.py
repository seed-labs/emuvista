#!/usr/bin/env python3
"""Build a mini Internet with email, payment, two banks and a marketplace."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.core import Binding, Filter
from seedemu.containerBundle import ContainerBundle, InternetMap
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator as build_mini_internet, host_zone
from bundles.BankBundle import BankBundle
from bundles.EmailBundle import EmailBundle
from bundles.PaymentBundle import PaymentBundle
from services.ShopService import ShopService

HERE = Path(__file__).resolve().parent
BUNDLE_TYPES = {
    'email': EmailBundle,
    'payment': PaymentBundle,
    'south-bank': BankBundle,
    'north-bank': BankBundle,
}
_CONFIGURATION = json.loads((HERE / 'world.json').read_text())


def createworld(state=None):
    """Return the native emulator and its separately held application systems."""
    state = Path(state).resolve() if state else None
    emu = build_mini_internet()
    systems = {name: bundle(emu, name=name, resolver=DNS_RESOLVER)
               for name, bundle in BUNDLE_TYPES.items()}
    shop = ShopService(resolver=DNS_RESOLVER)
    systems['shop'] = shop.install('shop')
    emu.addLayer(shop)
    asn = _CONFIGURATION['shop']['asn']
    emu.getLayer('Base').getAutonomousSystem(asn).createHost('shop').joinNetwork(
        'net0', address=f'10.{asn}.0.10')
    emu.addBinding(Binding('shop', filter=Filter(asn=asn, nodeName='shop')))

    for name, system in systems.items():
        settings = _CONFIGURATION[name]
        system.setHostname(settings['hostname'])
        system.setInitialConfiguration(settings['configuration'])
        zone = host_zone(emu, settings['hostname'])
        zone.addRecord(f'@ A 10.{settings["asn"]}.0.10')
        if isinstance(system, BankBundle):
            system.setDisplayName(settings['name'])
            system.enableHostAccess(settings['port'], staff_port=settings['staffPort'])
            zone.addRecord(f'staff A 10.{settings["asn"]}.0.18')
        else:
            system.enableHostAccess(settings['port'])
        if isinstance(system, EmailBundle):
            for domain in settings['configuration']['domains']:
                host_zone(emu, domain).addRecord(f'@ MX 10 {settings["hostname"]}.')
        if state:
            system.setSavePath(state / name)

    for name, settings in _CONFIGURATION.items():
        for email in settings.get('connections', {}).get('email', []):
            systems[name].connectEmail(systems[email])
    for name, settings in _CONFIGURATION.items():
        for bank in settings.get('connections', {}).get('bank', []):
            systems[name].connectBank(systems[bank])
    for name, settings in _CONFIGURATION.items():
        for payment in settings.get('connections', {}).get('payment', []):
            systems[name].connectPayment(systems[payment])
    return emu, systems


def createcompiler(emu, systems):
    """Attach application containers to rendered networks using the native compiler."""
    compiler = Docker(platform=Platform.AMD64)
    internet_map = InternetMap(emu)
    internet_map.setPorts([8083, 8080, 8084])
    compiler.addContainerBundle(internet_map)
    for name, bundle in systems.items():
        if not isinstance(bundle, ContainerBundle):
            continue
        asn = _CONFIGURATION[name]['asn']
        bundle.addInternalNetwork(str(asn), 'net0',
                                  [f'10.{asn}.0.{i}' for i in range(10, 10 + len(bundle.getContainers()))])
        compiler.addContainerBundle(bundle)
    return compiler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve() or args.output.resolve() in args.state.resolve().parents):
        parser.error('state must be outside output')
    emu, systems = createworld(args.state)
    emu.render()
    emu.compile(createcompiler(emu, systems), str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
