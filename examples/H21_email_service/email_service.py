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
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator, host_zone


def add_mail_records(emu, configuration, address='10.150.0.10'):
    """Add application records to H00's existing DNS infrastructure."""
    host_zone(emu, configuration['hostname']).addRecord('@ A ' + address)
    for domain in configuration['domains']:
        host_zone(emu, domain).addRecord(f'@ MX 10 {configuration["hostname"]}.')


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
    bundle = EmailBundle(emu, resolver=DNS_RESOLVER)
    bundle.setHostname(configuration['hostname'])
    bundle.setInitialConfiguration(configuration)
    add_mail_records(emu, configuration)
    emu.render()
    bundle.addInternalNetwork('150', 'net0',
                              [f'10.150.0.{i}' for i in range(10, 10 + len(bundle.getContainers()))], '10.150.0.254')
    bundle.enableHostAccess(args.host_port)
    if args.state:
        bundle.setSavePath(args.state)
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=True)
    compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
