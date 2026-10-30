#!/usr/bin/env python3
"""Generate Docker deployment files for the complete environment."""
import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SERVICES = HERE.parents[1] / 'services'
SEED_EMULATOR = HERE.parents[2] / 'seed-emulator'
sys.path.insert(0, str(SEED_EMULATOR))
sys.path.insert(0, str(SERVICES))

from DomainService import NamingoRegistryService, FossBillingRegistrarService, DnsService, FakePaymentService
from DomainService import DnsServiceMerger
from seedemu.core import Binding, Filter, Emulator, Action
from seedemu.compiler import Docker, Platform
from examples.internet.B02_mini_internet_with_dns.mini_internet_with_dns import build_emulator as build_b02

def build_emulator():
    """Build the complete domain purchase environment."""

    emu = build_b02()
    # Use the native merge API to install the DNS subclass, retaining B02 zones, nodes and bindings.
    dns_extension = Emulator()
    dns_extension.addLayer(DnsService())
    emu = emu.merge(dns_extension, [DnsServiceMerger()])
    # ------------------------------------------------------------------------
    # Registry and DNS publication authorization
    # ------------------------------------------------------------------------
    registry_service = NamingoRegistryService()
    registry_server = registry_service.install('registry')
    registry_server.setPortForwarding(18081)
    registry_server.setTlds(['com', 'net'])
    registry_server.setAdminAccount('admin@example.com', '123456')
    registry_server.setDatabasePassword('registry-database-password')
    authorization = emu.getLayer('DomainNameService').authorizeZoneUpdates(
        ['com', 'net'],
    )
    registry_server.setDnsAuthorization(authorization)
    registry_server.enableDnsPublication(['com', 'net'])
    emu.addLayer(registry_service)
    emu.addBinding(Binding('registry', filter=Filter(asn=151, nodeName=r'^host_'), action=Action.FIRST))

    # ------------------------------------------------------------------------
    # Registrar and domain products
    # ------------------------------------------------------------------------
    registrar_service = FossBillingRegistrarService()
    registrar_server = registrar_service.install('fossbilling')
    registrar_server.setPortForwarding(18080)
    registrar_server.setRegistry('registry')
    registrar_server.setTlds(['com', 'net'])
    registrar_server.setAdminAccount('admin@example.com', 'Aa123456')
    registrar_server.setClientAccount('user@example.com', 'Aa123456')
    registrar_server.setTldPrice('com', '11.99', '11.99', '11.99')
    registrar_server.setTldPrice('net', '11.99', '11.99', '11.99')
    # Reserve domains used by base DNS and hosting to prevent resale.
    registrar_server.setReservedDomains(['google.com', 'twitter.com', 'example.com'])
    emu.addLayer(registrar_service)
    emu.addBinding(Binding('fossbilling', filter=Filter(asn=150, nodeName=r'^host_'), action=Action.FIRST))

    # ------------------------------------------------------------------------
    # Primary-secondary DNS and hosting
    # ------------------------------------------------------------------------
    dns = emu.getLayer('DomainNameService')
    dns.install('hosted-dns-primary').addZone('example.com.').setMaster()
    dns.install('hosted-dns-secondary').addZone('example.com.')
    dns_hosting = dns.addHosting('hosted-dns-primary', 'hosted-dns-secondary', domain='example.com')
    dns_hosting.addRegistrarToRateLimitWhitelist('fossbilling')
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
    registrar_server.setPaymentService('fake-payment')
    emu.addLayer(fake_payment_service)
    emu.addBinding(Binding('fake-payment', filter=Filter(asn=160, nodeName=r'^host_'), action=Action.FIRST))
    return emu


def main(argv=None):
    """Render and generate deployment files without building or starting containers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')

    args = parser.parse_args(argv)
    output = args.output.resolve()
    try:
        emu = build_emulator()
        emu.render()
        emu.compile(Docker(platform=Platform.AMD64 if args.platform == 'amd' else Platform.ARM64),
                    str(output), override=True)
        if not (output / 'docker-compose.yml').is_file():
            raise RuntimeError(f'Missing {output / "docker-compose.yml"}')
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
