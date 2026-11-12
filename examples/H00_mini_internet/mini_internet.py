#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

import argparse
from pathlib import Path

from seedemu.compiler import Docker, Platform
from seedemu.core import Binding, Emulator, Filter
from seedemu.layers import Base, Dnssec, Ebgp, Ibgp, Ospf, PeerRelationship, Routing
from seedemu.services import DomainNameCachingService, DomainNameService
from seedemu.utilities import Makers


DNS_AUTHORITY = '10.150.0.53'
DNS_RESOLVER = '10.150.0.54'


def build_emulator(hosts_per_as=2, *, dnssec_key_store=None) -> Emulator:
    """Return an unrendered mini Internet with an empty private DNS root.

    Add application records and services before calling emu.render(). DNSSEC is
    always enabled; saved signing keys must be outside compiler output.
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
    _configure_dns(emu, key_store=dnssec_key_store)
    return emu


def _configure_dns(emu, *, key_store):
    base = emu.getLayer('Base')
    authority = DomainNameService()
    base.getAutonomousSystem(150).createHost(
        'dns_authority').joinNetwork('net0', address=DNS_AUTHORITY)
    authority.install('dns-authority').addZone('.').setMaster()
    emu.addBinding(Binding('dns-authority', filter=Filter(asn=150, nodeName='dns_authority')))
    emu.getVirtualNode('dns-authority').setDisplayName('Root DNS')

    caching = DomainNameCachingService()
    base.getAutonomousSystem(150).createHost(
        'dns_resolver').joinNetwork('net0', address=DNS_RESOLVER)
    resolver = caching.install('dns-resolver')
    emu.addLayer(authority)
    emu.addLayer(caching)
    emu.addBinding(Binding('dns-resolver', filter=Filter(asn=150, nodeName='dns_resolver')))
    emu.getVirtualNode('dns-resolver').setDisplayName('Recursive DNS')

    signing = Dnssec().enableOn('.')
    if key_store is not None:
        signing.setKeyStore(Path(key_store).expanduser().resolve())
    resolver.addDnssecTrustAnchor('.', signing.getTrustAnchor('.'))
    resolver.setDnssecValidation()
    emu.addLayer(signing)


def main():
    parser = argparse.ArgumentParser(description='Build the shared mini Internet with DNS.')
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')
    parser.add_argument('--hosts-per-as', type=int, default=2)
    parser.add_argument('--dnssec-key-store', type=Path,
                        help='Optional directory to save and reuse DNSSEC keys')
    args = parser.parse_args()
    if args.dnssec_key_store and (args.dnssec_key_store.resolve() == args.output.resolve()
                                  or args.output.resolve() in args.dnssec_key_store.resolve().parents):
        parser.error('DNSSEC keys must be outside output')
    emu = build_emulator(args.hosts_per_as, dnssec_key_store=args.dnssec_key_store)
    emu.render()
    platform = Platform.AMD64 if args.platform == 'amd' else Platform.ARM64
    emu.compile(Docker(platform=platform, internetMapEnabled=True),
                str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
