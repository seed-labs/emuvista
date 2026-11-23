#!/usr/bin/env python3
"""Run five autonomous residents inside the shared H99 virtual world."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from seedemu.core import Action, Binding, Filter
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
        person['accounts']['shop'] = {'password': 'ShopDemoPass123!'}
        person['possessions'] = {}
        if person['id'] == market['owner']:
            person['possessions']['shop'] = {
                'name': market['name'],
                'seller': person['email'],
                'products': market['products'],
            }
    return people


def initialize_accounts(people, systems):
    """Declare personal accounts in each system's initialization metadata."""
    for person in people:
        accounts = person['accounts']
        mailbox = accounts['email']
        systems['email'].addUser(mailbox)
        wallet = accounts['payment']
        systems['payment'].addUser(wallet['group'], {
            'name': person['name'], 'email': mailbox['email'],
            'password': wallet['password'], 'balance': wallet['balance'],
        })
        shop = {'id': person['id'], 'name': person['name'], 'email': mailbox['email'],
                'password': accounts['shop']['password'],
                'wallet': systems['payment'].getInitialAccountId(wallet['group'], mailbox['email'])}
        if person['possessions'].get('shop'):
            shop['store'] = person['possessions']['shop']
            person['possessions']['shop'] = {'name': shop['store']['name']}
        systems['shop'].addUser(shop)
        for bank, customer in accounts['bank'].items():
            systems[bank].addCustomer({
                **customer, 'id': person['id'],
                'email': mailbox['email'], 'emailPassword': mailbox['password'],
            })


def prepare_tools(systems):
    """Collect service-owned tools and private instance settings."""
    tools = [
        ToolPackage('network', ROOT / 'services/AgentService/tools/network'),
        ToolPackage('world', HERE / 'tools/world'),
        ToolPackage('life', HERE / 'tools/life'),
    ]
    tools.extend(provider.getAgentTools() for provider in systems.values())
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
    emu, systems = createworld(args.state)
    initialize_accounts(people, systems)
    agents = AgentService(tools=prepare_tools(systems), environment_file=HERE / '.env')
    network = emu.getLayer('Base').getAutonomousSystem(171)
    emu.addBinding(Binding(agents.clock.vnode, action=Action.NEW,
                           filter=Filter(asn=171, nodeName=agents.clock.vnode, ip='10.171.0.79')))
    for index, person in enumerate(people, 1):
        agent = agents.createagent(person)
        address = '10.171.0.' + str(79 + index)
        node = network.createHost(agent.vnode).joinNetwork('net0', address=address)
        emu.addBinding(Binding(agent.vnode, filter=Filter(asn=171, nodeName=agent.vnode)))
    emu.addLayer(agents)
    emu.render()
    emu.compile(createcompiler(emu, systems), str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
