#!/usr/bin/env python3
"""Deploy Mailu on the mini Internet using an independent EmailBundle."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.core import Binding, Filter
from seedemu.layers import Dnssec
from seedemu.services import DomainNameService, DomainNameCachingService
from services.EmailService import EmailBundle
from examples.H21_email_service.mini_internet import build_emulator


def configure_dns(emu, configuration, state=None):
    """Use SEED's authority, signing layer and validating caching resolver."""
    base = emu.getLayer('Base')
    network = base.getAutonomousSystem(150)
    network.createHost('dns_authority').joinNetwork('net0', address='10.150.0.53')
    network.createHost('dns_resolver').joinNetwork('net0', address='10.150.0.54')
    authority = DomainNameService()
    authority.install('email-dns-authority').addZone('.').setMaster()
    root = authority.getRootZone()
    root.addRecord(f'{configuration["hostname"]}. A 10.150.0.10')
    for domain in configuration['domains']:
        root.addRecord(f'{domain}. MX 10 {configuration["hostname"]}.')
    # Mailu checks this signed name at startup in the private simulation namespace.
    root.addRecord('example.org. A 10.150.0.53')
    signing = Dnssec().enableOn('.')
    if state:
        signing.setKeyStore(state/'dnssec')
    caching = DomainNameCachingService()
    resolver = caching.install('email-dns-resolver')
    resolver.addDnssecTrustAnchor('.', signing.getTrustAnchor('.'))
    resolver.setDnssecValidation()
    for layer in (authority, caching, signing):
        emu.addLayer(layer)
    emu.addBinding(Binding('email-dns-authority', filter=Filter(asn=150, nodeName='dns_authority')))
    emu.addBinding(Binding('email-dns-resolver', filter=Filter(asn=150, nodeName='dns_resolver')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('mailboxes.json'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Save and resume mailboxes and configuration')
    parser.add_argument('--host-port', type=int, default=8445)
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve() or args.output.resolve() in args.state.resolve().parents):
        parser.error('email state must be outside output')
    emu = build_emulator()
    configuration = json.loads(args.config.read_text())
    bundle = EmailBundle(emu, resolver='10.150.0.54')
    bundle.setInitialConfiguration(configuration)
    configure_dns(emu, configuration, args.state.resolve() if args.state else None)
    emu.render()
    bundle.setDefaultInternalNetwork('net_150_net0',
        [f'10.150.0.{i}' for i in range(10, 10+len(bundle.getContainers()))], '10.150.0.254')
    bundle.enableHostAccess(args.host_port)
    if args.state:
        bundle.setSavePath(args.state)
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=False)
    compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(args.output.resolve()), override=True)
    (args.output/'.env').write_text('COMPOSE_PROJECT_NAME=h21-email\n')
    print(f'Webmail: https://localhost:{args.host_port}/webmail/')
    print(f'Administration: https://localhost:{args.host_port}/admin/')
    print('Next: cd output; docker compose build; docker compose up -d')


if __name__ == '__main__':
    main()
