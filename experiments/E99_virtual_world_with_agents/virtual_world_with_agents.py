#!/usr/bin/env python3
"""Run five autonomous residents inside the shared H99 virtual world."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from seedemu.core import Binding, Filter
from examples.H99_virtual_world import createworld, createcompiler
from services.AgentService import AgentService, ToolPackage

HERE = Path(__file__).resolve().parent


def createpeople(path=HERE / 'people.json', market_path=HERE / 'market.json'):
    """Load people and assemble their initial knowledge and owned inventory."""
    people = json.loads(Path(path).read_text())['people']
    market = json.loads(Path(market_path).read_text())
    for person in people:
        person['email'] = person['accounts']['email']['email']
        person['mode'] = 'resident'
        person['knowledge'] = {'emails': [other['accounts']['email']['email'] for other in people]}
        person['possessions'] = {}
        if person['id'] == market['owner']:
            person['possessions']['shop'] = {
                'name': market['name'],
                'seller': person['email'],
                'products': market['products'],
            }
    return people


def initialize_accounts(people, bundles):
    """Declare personal accounts in each Bundle's initialization metadata."""
    for person in people:
        accounts = person['accounts']
        mailbox = accounts['email']
        bundles['email'].addUser(mailbox)
        wallet = accounts['payment']
        bundles['payment'].addUser(wallet['group'], {
            'name': person['name'], 'email': mailbox['email'],
            'password': wallet['password'], 'balance': wallet['balance'],
        })
        for bank, customer in accounts['bank'].items():
            bundles[bank].addCustomer({
                **customer, 'id': person['id'],
                'email': mailbox['email'], 'emailPassword': mailbox['password'],
            })


def prepare_tools(bundles):
    """Collect service-owned tools and private instance settings."""
    tools = [
        ToolPackage('network', ROOT / 'services/AgentService/tools/network'),
        ToolPackage('world', HERE / 'tools/world'),
        ToolPackage('life', HERE / 'tools/life'),
        ToolPackage('shop', HERE / 'tools/shop'),
    ]
    tools.extend(provider.getAgentTools() for provider in bundles.values())
    return tools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path,
                        help='Preserve application data and resident memory in this directory')
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve()
                       or args.output.resolve() in args.state.resolve().parents):
        parser.error('state must be outside output')
    if not (HERE / '.env').is_file():
        parser.error('Missing .env. Copy .env.example to .env and configure the LLM settings.')
    people = createpeople()
    emu, bundles = createworld(args.state)
    initialize_accounts(people, bundles)
    agents = AgentService(tools=prepare_tools(bundles), environment_file=HERE / '.env')
    network = emu.getLayer('Base').getAutonomousSystem(171)
    for index, person in enumerate(people, 1):
        agent = agents.createagent(person)
        address = '10.171.0.' + str(79 + index)
        node = network.createHost(agent.vnode).joinNetwork('net0', address=address)
        emu.addBinding(Binding(agent.vnode, filter=Filter(asn=171, nodeName=agent.vnode)))
        if person['possessions'].get('shop'):
            node.appendStartCommand(
                'runuser -u emuvista-agent -- python3 -u '
                '/opt/emuvista-agent/packages/shop/server.py '
                '> /home/emuvista-agent/shop.log 2>&1',
                fork=True,
            )
            agents.addToolPackage(ToolPackage(
                'shop', HERE / 'tools/shop',
                configuration={
                    'shop-' + person['id']: {
                        'name': person['possessions']['shop']['name'],
                        'url': f'http://{address}:8080',
                    },
                },
            ))
    emu.addLayer(agents)
    emu.render()
    emu.compile(createcompiler(bundles), str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
