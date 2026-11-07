#!/usr/bin/env python3
"""Compile Komunitin into SEED using prebuilt images and automatic initialization."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from bundles.PaymentBundle import PaymentBundle
from examples.H00_mini_internet import build_emulator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Optional directory to save and resume payment state')
    parser.add_argument('--images', type=Path, help='JSON mapping of component roles to prebuilt image references')
    initial = parser.add_mutually_exclusive_group()
    initial.add_argument('--config', type=Path, default=Path(__file__).with_name('groups.json'),
                         help='Community, currency and user configuration (default: groups.json)')
    initial.add_argument('--initial-data', type=Path, help='Advanced: use a Komunitin ZIP instead of groups.json')
    parser.add_argument('--host-port', type=int, default=8443, help='Host browser HTTPS port (default: 8443)')
    args = parser.parse_args()
    output = args.output.resolve()
    if args.state:
        state = args.state.resolve()
        if state == output or output in state.parents:
            parser.error('payment state must be outside the compilation output directory')
    if any(output.glob('payment-*/state')):
        parser.error('output contains runtime data from the old layout; stop its containers and move output aside before recompiling')
    admin_email, admin_password = 'admin@h20.example', 'seed1234'
    emu = build_emulator()
    emu.render()
    payment = PaymentBundle(emu, images=json.loads(args.images.read_text()) if args.images else None)
    payment.addInternalNetwork(
        asn='150', network_name='net0',
        ip_addresses=[f'10.150.0.{10+index}' for index in range(len(payment.getContainers()))],
        default_route='10.150.0.254')
    payment.enableHostAccess(args.host_port)
    payment.setAdminCredentials(admin_email, admin_password)
    try:
        if args.initial_data:
            payment.setInitialData(args.initial_data)
        else:
            payment.setInitialConfiguration(args.config)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.state:
        payment.setSavePath(str(args.state))
    compiler = Docker(platform=Platform.AMD64, internetMapEnabled=True)
    compiler.addContainerBundle(payment)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(compiler, str(args.output.resolve()), override=True)
    print(f'Compiled PaymentBundle: {payment.getURL()}')
    print(f'Host browser: https://localhost:{args.host_port}/login-mail')
    print('Internet Map: http://localhost:8080')
    print(f'Next: cd {args.output}; docker compose build; docker compose up -d')


if __name__ == '__main__':
    main()
