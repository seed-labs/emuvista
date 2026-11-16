#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

import argparse
from pathlib import Path

from seedemu.compiler import Docker, Platform
from seedemu.core import Binding, Emulator, Filter
from seedemu.layers import Base, Ebgp, Ibgp, Ospf, PeerRelationship, Routing
from seedemu.services import DomainNameCachingService, DomainNameService
from seedemu.utilities import Makers


DNS_AUTHORITY = '10.150.0.53'
DNS_RESOLVER = '10.150.0.54'
DNS_HOSTING = '10.154.0.53'
COMPANY_ASN = 164

# Network name, subnet number, display name, and physical host names.
COMPANY_LANS = [
    ('dmz', 10, 'Public Services', ['portal', 'website', 'vpn']),
    ('applications', 20, 'Business Applications',
     ['identity', 'hr', 'finance', 'oa', 'chat', 'projects', 'cloud']),
    ('data', 30, 'Databases and Storage', ['database1', 'database2', 'storage']),
    ('management', 40, 'IT Management', ['admin', 'monitoring', 'backup']),
    ('hr', 50, 'Human Resources', ['hr1', 'hr2', 'hr3']),
    ('finance', 60, 'Finance', ['finance1', 'finance2', 'finance3']),
    ('engineering', 70, 'Engineering', ['engineer1', 'engineer2', 'engineer3', 'engineer4']),
    ('sales', 80, 'Sales', ['sales1', 'sales2', 'sales3']),
    ('operations', 90, 'Operations', ['operations1', 'operations2', 'operations3']),
    ('guest', 100, 'Guest Devices', ['guest1', 'guest2']),
    ('branch', 110, 'Branch Office', ['branch1', 'branch2', 'branch3']),
]


def build_emulator(hosts_per_as=2) -> Emulator:
    """Return an unrendered mini Internet with DNS and a company campus.

    Add application records and services before calling emu.render().
    The network includes an IPv4 gateway to destinations outside the emulation.
    """
    if type(hosts_per_as) is not int or hosts_per_as < 1:
        raise ValueError('hosts_per_as must be a positive integer')
    emu = Emulator()
    ebgp = Ebgp()
    base = Base().setNameServers([DNS_RESOLVER])

    ###############################################################################
    # Create internet exchanges
    ix100 = base.createInternetExchange(100)
    ix101 = base.createInternetExchange(101)
    ix102 = base.createInternetExchange(102)
    ix103 = base.createInternetExchange(103)
    ix104 = base.createInternetExchange(104)
    ix105 = base.createInternetExchange(105)

    # Customize names (for visualization purpose)
    ix100.getPeeringLan().setDisplayName("NYC-100")
    ix101.getPeeringLan().setDisplayName("San Jose-101")
    ix102.getPeeringLan().setDisplayName("Chicago-102")
    ix103.getPeeringLan().setDisplayName("Miami-103")
    ix104.getPeeringLan().setDisplayName("Boston-104")
    ix105.getPeeringLan().setDisplayName("Huston-105")

    ###############################################################################
    # Create Transit Autonomous Systems

    # Tier 1 ASes
    Makers.makeTransitAs(
        base,
        2,
        [100, 101, 102, 105],
        [(100, 101), (101, 102), (100, 105)],
    )

    Makers.makeTransitAs(
        base,
        3,
        [100, 103, 104, 105],
        [(100, 103), (100, 105), (103, 105), (103, 104)],
    )

    Makers.makeTransitAs(
        base,
        4,
        [100, 102, 104],
        [(100, 104), (102, 104)],
    )

    # Tier 2 ASes
    Makers.makeTransitAs(base, 11, [102, 105], [(102, 105)])
    Makers.makeTransitAs(base, 12, [101, 104], [(101, 104)])

    ###############################################################################
    # Create single-homed stub ASes.
    Makers.makeStubAsWithHosts(emu, base, 150, 100, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 151, 100, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 152, 101, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 153, 101, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 154, 102, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 160, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 161, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 162, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 163, 104, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 164, 104, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 170, 105, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 171, 105, hosts_per_as)

    ###############################################################################
    # Peering via route servers.
    ebgp.addRsPeers(100, [2, 3, 4])
    ebgp.addRsPeers(102, [2, 4])
    ebgp.addRsPeers(104, [3, 4])
    ebgp.addRsPeers(105, [2, 3])

    # Private peerings for transit service.
    ebgp.addPrivatePeerings(100, [2], [150, 151], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(100, [3], [150], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(101, [2], [12], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(101, [12], [152, 153], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(102, [2, 4], [11, 154], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(102, [11], [154], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(103, [3], [160, 161, 162], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(104, [3, 4], [12], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(104, [4], [163], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(104, [12], [164], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(105, [3], [11, 170], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(105, [11], [171], PeerRelationship.Provider)

    outside = base.createAutonomousSystem(99999)
    outside.createRealWorldRouter('internet-egress',
                                  prefixes=['0.0.0.0/1', '128.0.0.0/1']).joinNetwork('ix100', '10.100.0.99')
    ebgp.addPrivatePeerings(100, [3], [99999], PeerRelationship.Provider)

    ###############################################################################
    # Add layers to the emulator

    emu.addLayer(base)
    emu.addLayer(Routing())
    emu.addLayer(ebgp)
    emu.addLayer(Ibgp())
    emu.addLayer(Ospf())
    _configure_company_network(emu)
    _configure_dns(emu)
    return emu


def _configure_company_network(emu):
    company = emu.getLayer('Base').getAutonomousSystem(COMPANY_ASN)
    ospf = emu.getLayer('Ospf')
    prefix = f'10.{COMPANY_ASN}'

    company.getNetwork('net0').setDisplayName('Company Edge LAN')
    edge = company.getRouter('router0').setDisplayName('Company Edge Router')
    company.createNetwork('edge_link', prefix=f'{prefix}.2.0/30')
    company.createNetwork('backbone', prefix=f'{prefix}.1.0/24').setDisplayName('Headquarters Backbone')
    company.createNetwork('branch_link', prefix=f'{prefix}.3.0/30').setDisplayName('Branch Routed Link')
    edge.joinNetwork('edge_link', address=f'{prefix}.2.1')
    core = company.createRouter('core').setDisplayName('Company Core Router')
    core.joinNetwork('edge_link', address=f'{prefix}.2.2')
    core.joinNetwork('backbone', address=f'{prefix}.1.1')
    core.joinNetwork('branch_link', address=f'{prefix}.3.1')

    for name, subnet, display, hosts in COMPANY_LANS:
        company.createNetwork(name, prefix=f'{prefix}.{subnet}.0/24').setDisplayName(display)
        router = company.createRouter(name + '_router').setDisplayName(display + ' Router')
        if name == 'branch':
            router.joinNetwork('branch_link', address=f'{prefix}.3.2')
        else:
            router.joinNetwork('backbone', address=f'{prefix}.1.{subnet}')
        router.joinNetwork(name, address=f'{prefix}.{subnet}.254')
        ospf.markAsStub(COMPANY_ASN, name)
        for index, hostname in enumerate(hosts, start=10):
            company.createHost(hostname).joinNetwork(name, address=f'{prefix}.{subnet}.{index}')

    ospf.markAsStub(COMPANY_ASN, 'net0')


def _configure_dns(emu):
    base = emu.getLayer('Base')
    authority = DomainNameService()
    emu.addLayer(authority)
    for name, domain, asn, display in [
        ('dns_authority', '.', 150, 'Root DNS'),
        ('dns_com', 'com.', 151, '.com DNS'),
        ('dns_net', 'net.', 152, '.net DNS'),
        ('dns_org', 'org.', 153, '.org DNS'),
    ]:
        base.getAutonomousSystem(asn).createHost(name).joinNetwork(
            'net0', address=f'10.{asn}.0.53')
        authority.install(name).addZone(domain).setMaster()
        emu.addBinding(Binding(name, filter=Filter(asn=asn, nodeName=name)))
        emu.getVirtualNode(name).setDisplayName(display)

    base.getAutonomousSystem(154).createHost('dns_hosting').joinNetwork(
        'net0', address=DNS_HOSTING)
    authority.install('dns_hosting').setMaster()
    emu.addBinding(Binding('dns_hosting', filter=Filter(asn=154, nodeName='dns_hosting')))
    emu.getVirtualNode('dns_hosting').setDisplayName('DNS Hosting: ns1.dns.com')
    host_zone(emu, 'dns.com').addRecord('ns1 A ' + DNS_HOSTING)
    # Bootstrap the provider's own nameserver with glue in its parent zone.
    authority.getZone('com.').addRecord('ns1.dns.com. A ' + DNS_HOSTING)

    recursive = DomainNameCachingService()
    base.getAutonomousSystem(150).createHost(
        'dns_resolver').joinNetwork('net0', address=DNS_RESOLVER)
    recursive.install('dns_resolver')
    emu.addLayer(recursive)
    emu.addBinding(Binding('dns_resolver', filter=Filter(asn=150, nodeName='dns_resolver')))
    emu.getVirtualNode('dns_resolver').setDisplayName('Recursive DNS')


def host_zone(emu, domain):
    """Delegate a zone to the shared nameserver and return its native Zone."""
    dns = emu.getLayer('DomainNameService')
    name = domain.rstrip('.') + '.'
    server = dns.install('dns_hosting')
    zone = dns.getZone(name)
    if name not in server.getZones():
        server.addZone(name, createNsAndSoa=False)
        zone.addRecord('@ SOA ns1.dns.com. hostmaster.dns.com. 1 900 900 1800 60')
        zone.addRecord('@ NS ns1.dns.com.')
        parent = name.rstrip('.').split('.', 1)[1]
        dns.getZone(parent).addRecord(f'{name} NS ns1.dns.com.')
    return zone


def main():
    parser = argparse.ArgumentParser(description='Build the shared mini Internet with DNS.')
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')
    parser.add_argument('--hosts-per-as', type=int, default=2)
    args = parser.parse_args()
    emu = build_emulator(args.hosts_per_as)
    emu.render()
    platform = Platform.AMD64 if args.platform == 'amd' else Platform.ARM64
    emu.compile(Docker(platform=platform, internetMapEnabled=True),
                str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
