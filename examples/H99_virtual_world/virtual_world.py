#!/usr/bin/env python3
"""Build a mini Internet with email, payment and two banks."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from examples.H00_mini_internet import DNS_AUTHORITY, DNS_RESOLVER, build_emulator as build_mini_internet
from bundles.BankBundle import BankBundle
from bundles.EmailBundle import EmailBundle
from bundles.PaymentBundle import PaymentBundle

HERE = Path(__file__).resolve().parent
BUNDLE_TYPES = {
    'email': EmailBundle,
    'payment': PaymentBundle,
    'south-bank': BankBundle,
    'north-bank': BankBundle,
}
_CONFIGURATION = json.loads((HERE / 'world.json').read_text())


def createworld(state=None):
    """Return the native emulator and its separately held application bundles."""
    state = Path(state).resolve() if state else None
    emu = build_mini_internet(dnssec_key_store=state / 'dnssec' if state else None)
    bundles = {name: BUNDLE_TYPES[name](emu, name=name, resolver=DNS_RESOLVER)
               for name in _CONFIGURATION}

    zone = emu.getLayer('DomainNameService').getRootZone()
    for name, bundle in bundles.items():
        settings = _CONFIGURATION[name]
        bundle.setHostname(settings['hostname'])
        bundle.setInitialConfiguration(settings['configuration'])
        zone.addRecord(f'{settings["hostname"]}. A 10.{settings["asn"]}.0.10')
        if isinstance(bundle, BankBundle):
            bundle.setDisplayName(settings['name'])
            bundle.enableHostAccess(settings['port'], staff_port=settings['staffPort'])
            zone.addRecord(f'staff.{settings["hostname"]}. A 10.{settings["asn"]}.0.18')
        else:
            bundle.enableHostAccess(settings['port'])
        if isinstance(bundle, EmailBundle):
            for domain in settings['configuration']['domains']:
                zone.addRecord(f'{domain}. MX 10 {settings["hostname"]}.')
        if state:
            bundle.setSavePath(state / name)
    # Mailu requires this signed record for its startup DNSSEC check.
    zone.addRecord('example.org. A ' + DNS_AUTHORITY)

    for name, settings in _CONFIGURATION.items():
        for email in settings.get('connections', {}).get('email', []):
            bundles[name].connectEmail(bundles[email])
    for name, settings in _CONFIGURATION.items():
        for bank in settings.get('connections', {}).get('bank', []):
            bundles[name].connectBank(bundles[bank])
    return emu, bundles


def createcompiler(bundles):
    """Attach application containers to rendered networks using the native compiler."""
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=True)
    for name, bundle in bundles.items():
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
    emu, bundles = createworld(args.state)
    emu.render()
    emu.compile(createcompiler(bundles), str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
