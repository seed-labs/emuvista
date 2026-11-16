#!/usr/bin/env python3
"""Build the Mastodon social media and domain purchase environment for E15."""

import argparse
from ipaddress import ip_address
import re
import shutil
from urllib.parse import urlsplit
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT.parent / 'seed-emulator'))
sys.path.insert(0, str(ROOT / 'services'))
sys.path.insert(0, str(ROOT))

from examples.H00_mini_internet import build_emulator as build_mini_internet
from DomainService import (
    DnsService, DnsServiceMerger,
    FakePaymentService,
)
from seedemu.compiler import Docker, Platform
from seedemu.core import Action, Binding, Emulator, Filter
from bundles.DomainRegistryBundle import DomainRegistryBundle
from bundles.DomainRegistrarBundle import DomainRegistrarBundle
from bundles.MastodonBundle import MastodonBundle
from services.AgentService import AgentService, ToolPackage
from services.AgentService.runtime.emuvista_agent.launch import read_environment


AGENT_NAMES = ('alice', 'bob', 'carol', 'dave', 'eve')

def configure_agents(emu, env_file):
    """Run all five agents with E99's framework and E15's service tools."""
    agents = AgentService(environment_file=env_file).addNetworkTools()
    agents.addToolPackage(ToolPackage('world', ROOT / 'experiments/E99_virtual_world_with_agents/tools/world',
        configuration={'mastodon': {'url': 'http://mastodon.com:18084/api/v2/instance'},
                       'registrar': {'url': 'http://fossbilling.com:8080/'},
                       'registry': {'url': 'http://registry.com:8080/'},
                       'payment': {'url': 'http://10.160.0.71:8080/health'}}))
    agents.addToolPackage(ToolPackage(**MastodonBundle.getAgentTools(),
                                      requirements=('pydantic>=2,<3',)))
    agents.addToolPackage(ToolPackage('dns', ROOT / 'services/AgentService/tools/dns',
                                      software=['dnsutils']))
    agents.addToolPackage(ToolPackage(**DomainRegistrarBundle.getAgentTools()))
    directory = {'services': {
        'mastodon': {'url': 'http://mastodon.com:18084/api/v2/instance'},
        'registrar': {'url': 'http://fossbilling.com:8080/'},
        'registry': {'url': 'http://registry.com:8080/'},
        'payment': {'url': 'http://10.160.0.71:8080/health'},
    }}
    tools = [
        'network.identity', 'network.resolve', 'world.catalog', 'world.probe',
        'socialmedia.inbox', 'socialmedia.browse', 'socialmedia.profile',
        'socialmedia.posts', 'socialmedia.read', 'socialmedia.post',
        'socialmedia.like', 'socialmedia.boost', 'socialmedia.follow',
        'dns.lookup', 'domain_purchase.purchase', 'domain_purchase.status',
        'domain_purchase.set_nameservers', 'domain_purchase.hosting_purchase',
        'domain_purchase.hosting_status',
    ]
    for index, name in enumerate(AGENT_NAMES):
        node = emu.getLayer('Base').getAutonomousSystem(161).createHost('agent_' + name)
        node.joinNetwork('net0', address=f'10.161.0.{80 + index}')
        agent_tools = tools if name != 'bob' else [tool for tool in tools if not tool.startswith('domain_purchase.')]
        agent = agents.install(name).setTools(agent_tools)
        accounts = {}
        agent.setFramework('langchain')
        if name != 'bob':
            accounts['domain_purchase'] = {
                'registrar_url': 'http://10.150.0.10:8080',
                'payment_url': 'http://10.160.0.71:8080',
                'email': name + '@example.com', 'password': name + '123456',
                'currency': 'USD', 'tlds': ['com', 'net'],
                'state_dir': '/home/emuvista-agent/domain-purchases',
            }
            node.addPersistentStorage('/home/emuvista-agent/domain-purchases',
                                      name='e15-domain-purchases-' + name)
            node.addBuildCommandAtEnd('install -d -o 10001 -g 10001 -m 700 /home/emuvista-agent/domain-purchases')
        else:
            accounts['fossbilling_admin'] = {
                'registrar_url': 'http://10.150.0.10:8080',
                'email': 'admin@example.com', 'password': 'Aa123456',
            }
        node.addPersistentStorage('/run/socialmedia', name='e15-socialmedia-http-' + name, read_only=True)
        accounts['socialmedia'] = {
            'instance_url': 'http://mastodon.com:18084',
            'allow_http': True,
            'credential_file': '/run/socialmedia/credentials.json',
        }
        if name == 'bob':
            role = '你是 Bob，FOSSBilling 的域名销售员工。你喜欢刷 Mastodon，关注大家的动态，也喜欢参与交流。'
            task = (
                '结合当前环境与交流历史，以域名销售员工的身份理解用户需求、提供专业价值，并自主决定下一步行动。'
                '主动寻找符合职责的机会，让行动随实际反馈调整。'
            )
        else:
            if name == 'alice':
                role = '你是 Alice，一位 Mastodon 用户。你最近想建立一个属于自己的博客。'
            else:
                role = f'你是 {name.capitalize()}，一位 Mastodon 用户。'
            task = (
                '结合当前环境与交流历史，以普通用户的身份探索兴趣、增进理解并与他人建立交流，自主决定下一步行动。'
                '主动发现值得参与的事情，让行动随实际反馈调整。'
            )
        agent.setPersona({
            'id': name, 'name': name.capitalize(), 'accounts': accounts,
            'knowledge': directory,
            'instructions': role + (
                '保持角色一致，根据真实观察自主判断和行动。'
                '关于当前环境的回答必须依据工具返回的结果，不得编造事实或操作结果。'
                '区分已核实的事实、他人陈述与自己的推测；证据不足时明确说明不确定。'
                '通过工具执行行动，并核实结果后再报告完成；结果不明时先确认。'
                '交流简洁、相关，避免重复，并遵守工具声明的使用规则。'
            ),
            'background': task,
            'requiredServices': ['mastodon'],
        })
        emu.addBinding(Binding(name, filter=Filter(asn=161, nodeName='^agent_' + name + '$')))
    emu.addBinding(Binding(agents.clock.vnode, action=Action.NEW,
                           filter=Filter(asn=161, nodeName=agents.clock.vnode, ip='10.161.0.79')))
    emu.addLayer(agents)


def add_model_egress(emu, base_url):
    """Use E99's native real-world routing and forward only the LLM hostname."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('LLM_BASE_URL must be an HTTP(S) endpoint')
    # H00 already provides AS99999 and real-world default routes.
    host = parsed.hostname
    try:
        ip_address(host)
        return None
    except ValueError:
        pass
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host):
        raise ValueError('invalid LLM hostname')

    def forward():
        resolver = emu.getBindingFor('dns-resolver')
        resolver.appendFile('/etc/bind/named.conf.local',
                            f'\nzone "{host}" {{ type forward; forward only; forwarders {{ 1.1.1.1; 8.8.8.8; }}; }};\n')
    return forward


def build_scenario(*, env_file=None):
    """Build E15 services directly on the shared H00 topology."""
    emu = build_mini_internet()
    # Use the native merge API to install the DNS subclass, retaining H00 zones, nodes and bindings.
    dns_extension = Emulator()
    dns_extension.addLayer(DnsService())
    emu = emu.merge(dns_extension, [DnsServiceMerger()])
    # ------------------------------------------------------------------------
    # Registry and DNS publication authorization
    # ------------------------------------------------------------------------
    registry = DomainRegistryBundle(emu)
    registry_server = registry.server
    registry_server.setPortForwarding(18081)
    registry_server.setTlds(['com', 'net'])
    registry_server.setAdminAccount('admin@example.com', '123456')
    registry_server.setDatabasePassword('registry-database-password')
    authorization = emu.getLayer('DomainNameService').authorizeZoneUpdates(
        ['com', 'net'],
    )
    registry_server.setDnsAuthorization(authorization)
    registry_server.enableDnsPublication(['com', 'net'])

    # ------------------------------------------------------------------------
    # Registrar and domain products
    # ------------------------------------------------------------------------
    registrar = DomainRegistrarBundle(emu)
    registrar_server = registrar.server
    registrar_server.setPortForwarding(18080)
    registrar_server.setRegistry('registry')
    registrar_server.setTlds(['com', 'net'])
    registrar_server.setAdminAccount('admin@example.com', 'Aa123456')
    registrar_server.setClientAccount('alice@example.com', 'alice123456')
    for name in ('carol', 'dave', 'eve'):
        registrar_server.addClientAccount(name + '@example.com', name + '123456')
    registrar_server.setTldPrice('com', '11.99', '11.99', '11.99')
    registrar_server.setTldPrice('net', '11.99', '11.99', '11.99')
    # Reserve domains used by base DNS and hosting to prevent resale.
    registrar_server.setReservedDomains([
        'google.com', 'twitter.com', 'example.com', 'mastodon.com',
        'fossbilling.com', 'registry.com',
    ])

    # ------------------------------------------------------------------------
    # Primary-secondary DNS and hosting
    # ------------------------------------------------------------------------
    dns = emu.getLayer('DomainNameService')
    dns.install('hosted-dns-primary').addZone('example.com.').setMaster()
    dns.install('hosted-dns-secondary').addZone('example.com.')
    dns_hosting = dns.addHosting('hosted-dns-primary', 'hosted-dns-secondary', domain='example.com')
    dns_hosting.addAddressToRateLimitWhitelist('10.150.0.10')
    registry_server.addNameServers(dns_hosting, epp_username=registrar_server.getEppUsername())
    registrar_server.setDnsHostings(dns_hosting)
    emu.addBinding(Binding('hosted-dns-primary', filter=Filter(asn=170, nodeName=r'^host_'), action=Action.FIRST))
    emu.addBinding(Binding('hosted-dns-secondary', filter=Filter(asn=170, nodeName=r'^host_'), action=Action.FIRST))

    # ------------------------------------------------------------------------
    # Simulated payment checkout
    # ------------------------------------------------------------------------
    fake_payment_service = FakePaymentService()
    fake_payment_server = fake_payment_service.install('fake-payment')
    fake_payment_server.setPortForwarding(18083)
    fake_payment_server.setPort(8080)
    fake_payment_server.authorizeCallback('http://10.150.0.10:8080')
    registrar_server.setPaymentService('fake-payment')
    emu.addLayer(fake_payment_service)
    emu.addBinding(Binding('fake-payment', filter=Filter(asn=160, nodeName=r'^host_'), action=Action.FIRST))

    social_as = emu.getLayer('Base').getAutonomousSystem(161)
    mastodon = MastodonBundle(emu)
    social_as.createHost('alice').joinNetwork('net0', address='10.161.0.10')
    social_as.createHost('bob').joinNetwork('net0', address='10.161.0.11')
    for name, address in [('mastodon', '10.161.0.9'),
                          ('fossbilling', '10.150.0.10'), ('registry', '10.151.0.10')]:
        dns.getZone('com.').addRecord(f'{name} A {address}')

    server = mastodon.server
    server.setDomain('mastodon.com')
    server.addAccount('admin', 'admin123456', email='admin@mastodon.com', admin=True)
    for name in AGENT_NAMES:
        server.addAccount(name, name + '123456', email=name + '@mastodon.com')
        server.exportToken(name, scopes=['read:accounts', 'read:statuses', 'read:notifications',
                                        'write:statuses', 'write:favourites', 'write:follows'],
                           path=f'/var/lib/mastodon/agent-{name}.json')
        mastodon.exportAgentToken(name, 'e15-socialmedia-http-' + name)
    configure_agents(emu, env_file)
    return emu, (registry, registrar, mastodon)


def configure_bundles(emu, bundles, compiler):
    registry, registrar, mastodon = bundles
    registry.addInternalNetwork('151', 'net0', ['10.151.0.10'], '10.151.0.254')
    registrar.addInternalNetwork('150', 'net0', ['10.150.0.10'], '10.150.0.254')
    mastodon.addInternalNetwork('161', 'net0', ['10.161.0.9'], '10.161.0.254')
    registrar.connectRegistry(registry)
    registrar.connectPayment(emu.getServerByVirtualNodeName('fake-payment'))
    mastodon.registerVolumes(compiler)
    for bundle, directory in zip(bundles, ('namingo', 'fossbilling', 'mastodon')):
        bundle.getContainer('app').updateServiceConfig({
            'build': {'context': f'./application-images/{directory}'},
            'pull_policy': 'never',
        })
        compiler.addContainerBundle(bundle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')
    parser.add_argument('--env-file', type=Path, default=HERE / '.env')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not args.env_file.exists():
        shutil.copy2(HERE / '.env.example', args.env_file)
        args.env_file.chmod(0o600)
    environment = read_environment(args.env_file)
    emu, bundles = build_scenario(env_file=args.env_file)
    after_render = add_model_egress(emu, environment.get('LLM_BASE_URL') or 'https://api.openai.com/v1')
    emu.render()
    if after_render is not None:
        after_render()
    compiler = Docker(platform=Platform.AMD64 if args.platform == 'amd' else Platform.ARM64)
    configure_bundles(emu, bundles, compiler)
    emu.compile(compiler, str(output), override=True)
    for directory in ('namingo', 'fossbilling', 'mastodon'):
        shutil.copytree(ROOT / 'docker_images' / directory,
                        output / 'application-images' / directory)
    print(f'Generated {output}; run docker compose build and docker compose up -d there.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
