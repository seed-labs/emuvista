#!/usr/bin/env python3
"""Compile Komunitin into SEED using prebuilt images and automatic initialization."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.core import Binding, Emulator, Filter
from seedemu.compiler import Docker, Platform
from seedemu.layers import Base, Ebgp, Routing
from seedemu.utilities import Makers
from services.PaymentService import PaymentService
from mini_internet import build_emulator
from initial_state import load_users, prepare_bundle


def compact_network():
    """Three real BGP-connected ASes; can run beside the old manual demo."""
    emu = Emulator()
    base, bgp = Base(), Ebgp()
    base.createInternetExchange(219)
    for asn in (210, 211, 212):
        Makers.makeStubAsWithHosts(emu, base, asn, 219, 1)
    bgp.addRsPeers(219, [210, 211, 212])
    for layer in (base, Routing(), bgp):
        emu.addLayer(layer)
    return emu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topology', choices=['mini', 'compact'], default='mini')
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Optional directory to save and resume payment state')
    parser.add_argument('--images', type=Path, help='JSON mapping of component roles to prebuilt image references')
    initial = parser.add_mutually_exclusive_group()
    initial.add_argument('--users', type=Path, default=Path(__file__).with_name('users.json'),
                         help='Initial user configuration (default: users.json)')
    initial.add_argument('--initial-data', type=Path, help='Advanced: use a Komunitin ZIP instead of users.json')
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
    try:
        users = load_users(args.users, admin_email) if not args.initial_data else None
        initial_data = args.initial_data if args.initial_data else prepare_bundle(users, admin_email, args.state)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    emu = build_emulator() if args.topology == 'mini' else compact_network()
    payment = PaymentService(json.loads(args.images.read_text()) if args.images else None)
    wallet = payment.install('wallet')
    wallet.enableHostAccess(args.host_port)
    wallet.setAdminCredentials(admin_email, admin_password)
    wallet.setInitialData(initial_data)
    if args.state:
        wallet.setSavePath(str(args.state))
    emu.addLayer(payment)
    emu.addBinding(Binding('wallet', filter=Filter(asn=150 if args.topology == 'mini' else 210, nodeName='host_0')))
    emu.render()
    compiler = Docker(platform=Platform.AMD64)
    compiler.addContainerBundle(payment.getContainerBundle(emu))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(compiler, str(args.output.resolve()), override=True)
    print(f'Compiled PaymentService: {wallet.getURL()}')
    print(f'Host browser: https://localhost:{args.host_port}/login-mail')
    print(f'Next: cd {args.output}; docker compose build; docker compose up -d')


if __name__ == '__main__':
    main()
