#!/usr/bin/env python3
"""Deploy Mailu on the mini Internet using an independent EmailBundle."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from bundles.EmailBundle import EmailBundle
from examples.H00_mini_internet import DNS_AUTHORITY, DNS_RESOLVER, build_emulator


def add_mail_records(emu, configuration, address='10.150.0.10'):
    """Add application records to H00's existing DNS infrastructure."""
    dns = emu.getLayer('DomainNameService')
    zones = {zone for server in dns.getPendingTargets().values() for zone in server.getZones()}

    def add(name, value):
        name = name.lower().rstrip('.')+'.'
        zone = max((zone for zone in zones if zone == '.' or name == zone or name.endswith('.'+zone)), key=len)
        dns.getZone(zone).addRecord(f'{name} {value}')

    add(configuration['hostname'], 'A '+address)
    for domain in configuration['domains']:
        add(domain, f'MX 10 {configuration["hostname"]}.')
    # Mailu checks this signed name at startup in the private simulation namespace.
    add('example.org', 'A '+DNS_AUTHORITY)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('mailboxes.json'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Save and resume mailboxes and configuration')
    parser.add_argument('--host-port', type=int, default=8445)
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve() or args.output.resolve() in args.state.resolve().parents):
        parser.error('email state must be outside output')
    emu = build_emulator(dnssec=True, dnssec_key_store=args.state.resolve()/'dnssec' if args.state else None)
    configuration = json.loads(args.config.read_text())
    bundle = EmailBundle(emu, resolver=DNS_RESOLVER)
    bundle.setInitialConfiguration(configuration)
    add_mail_records(emu, configuration)
    emu.render()
    bundle.addInternalNetwork('150', 'net0',
        [f'10.150.0.{i}' for i in range(10, 10+len(bundle.getContainers()))], '10.150.0.254')
    bundle.enableHostAccess(args.host_port)
    if args.state:
        bundle.setSavePath(args.state)
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=True)
    compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(args.output.resolve()), override=True)
    (args.output/'.env').write_text('COMPOSE_PROJECT_NAME=h21-email\n')
    print(f'Webmail: https://localhost:{args.host_port}/webmail/')
    print(f'Administration: https://localhost:{args.host_port}/admin/')
    print('Internet Map: http://localhost:8080')
    print('Next: cd output; docker compose build; docker compose up -d')


if __name__ == '__main__':
    main()
