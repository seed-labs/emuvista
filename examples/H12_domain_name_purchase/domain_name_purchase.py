#!/usr/bin/env python3
"""Generate Docker deployment files for the complete environment."""
import argparse
from pathlib import Path
from shutil import copytree
import sys

HERE = Path(__file__).resolve().parent
SERVICES = HERE.parents[1] / 'services'
SEED_EMULATOR = HERE.parents[2] / 'seed-emulator'
sys.path.insert(0, str(SEED_EMULATOR))
sys.path.insert(0, str(SERVICES))
sys.path.insert(0, str(HERE.parents[1]))

from DomainService import DnsService, FakePaymentService
from DomainService import DnsServiceMerger, DomainDataService
from seedemu.core import Binding, Filter, Emulator, Action
from seedemu.compiler import Docker, Platform
from seedemu.containerBundle import InternetMap
from examples.H00_mini_internet import build_emulator as build_mini_internet
from bundles.DomainRegistryBundle import DomainRegistryBundle
from bundles.DomainRegistrarBundle import DomainRegistrarBundle

def build_scenario():
    """Build H12 with independent Registry and registrar bundles."""

    emu = build_mini_internet()
    # Use the native merge API to install the DNS subclass, retaining H00 zones, nodes and bindings.
    dns_extension = Emulator()
    dns_extension.addLayer(DnsService())
    emu = emu.merge(dns_extension, [DnsServiceMerger()])
    # ------------------------------------------------------------------------
    # Registry and DNS publication authorization
    # ------------------------------------------------------------------------
    registry_bundle = DomainRegistryBundle(emu)
    registry_server = registry_bundle.server
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
    registrar_bundle = DomainRegistrarBundle(emu)
    registrar_server = registrar_bundle.server
    registrar_server.setPortForwarding(18080)
    registrar_server.setRegistry('registry')
    registrar_server.setTlds(['com', 'net'])
    registrar_server.setAdminAccount('admin@example.com', 'Aa123456')
    registrar_server.setClientAccount('user@example.com', 'Aa123456')
    registrar_server.setTldPrice('com', '11.99', '11.99', '11.99')
    registrar_server.setTldPrice('net', '11.99', '11.99', '11.99')
    # Reserve domains used by base DNS and hosting to prevent resale.
    registrar_server.setReservedDomains(['google.com', 'twitter.com', 'example.com'])

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
    
    domain_data = DomainDataService()
    domain_data.addTarget('registry', registry_server)
    domain_data.addTarget('fossbilling', registrar_server)
    domain_data.importFile(HERE / 'domains.example.yaml')
    emu.addLayer(domain_data)
    return emu, [registry_bundle, registrar_bundle]


def configure_bundles(emu, bundles, compiler):
    """Attach applications after network rendering; DNS and domain checkout stay Services."""
    registry, registrar = bundles
    registry.addInternalNetwork('151', 'net0', ['10.151.0.10'], '10.151.0.254')
    registrar.addInternalNetwork('150', 'net0', ['10.150.0.10'], '10.150.0.254')
    registrar.connectRegistry(registry)
    registrar.connectPayment(emu.getServerByVirtualNodeName('fake-payment'))
    for bundle, image_directory in ((registry, 'namingo'), (registrar, 'fossbilling')):
        bundle.getContainer('app').updateServiceConfig({
            'build': {'context': f'./application-images/{image_directory}'},
            'pull_policy': 'never',
        })
    compiler.addContainerBundle(registry)
    compiler.addContainerBundle(registrar)
    internet_map = InternetMap(emu)
    # Observer control, topology UI, geographic UI, respectively.
    internet_map.setPorts([8081, 8080, 8082])
    compiler.addContainerBundle(internet_map)


def main(argv=None):
    """Render and generate deployment files without building or starting containers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')

    args = parser.parse_args(argv)
    output = args.output.resolve()
    try:
        emu, bundles = build_scenario()
        emu.render()
        compiler = Docker(platform=Platform.AMD64 if args.platform == 'amd' else Platform.ARM64)
        configure_bundles(emu, bundles, compiler)
        emu.compile(compiler, str(output), override=True)
        for image_directory in ('namingo', 'fossbilling'):
            copytree(HERE.parents[1] / 'docker_images' / image_directory,
                     output / 'application-images' / image_directory)
        if not (output / 'docker-compose.yml').is_file():
            raise RuntimeError(f'Missing {output / "docker-compose.yml"}')
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
