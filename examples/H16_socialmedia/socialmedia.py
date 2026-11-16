#!/usr/bin/env python3
"""Build a minimal single-AS Mastodon network with DNS and CA-issued HTTPS."""
import argparse
from pathlib import Path
import sys
from shutil import copytree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'seed-emulator'))
sys.path.insert(0, str(HERE.parents[1] / 'services'))
sys.path.insert(0, str(HERE.parents[1]))

from seedemu.compiler import Docker, Platform
from seedemu.core import Binding, Emulator, Filter
from seedemu.layers import Base, Routing
from seedemu.services import CAService, RootCAStore, DomainNameCachingService, DomainNameService
from bundles.MastodonBundle import MastodonBundle


def build_scenario():
    """Create DNS, Mastodon, and Alice and Bob client hosts."""
    emu = Emulator()
    base = Base()
    routing = Routing()

    as151 = base.createAutonomousSystem(151)
    as151.createNetwork('net0')
    as151.createRouter('router0').joinNetwork('net0', address='10.151.0.254')
    as151.createHost('dns').joinNetwork('net0', address='10.151.0.2')
    as151.createHost('dns-secondary').joinNetwork('net0', address='10.151.0.3')
    as151.createHost('local-dns').joinNetwork('net0', address='10.151.0.53')
    ca_node = as151.createHost('ca').joinNetwork('net0', address='10.151.0.4')
    ca_node.addPersistentStorage('/root/.step/db', name='h14-ca-db')
    as151.createHost('alice').joinNetwork('net0', address='10.151.0.10').setDisplayName('Alice')
    as151.createHost('bob').joinNetwork('net0', address='10.151.0.11').setDisplayName('Bob')
    base.setNameServers(['10.151.0.53'])
    emu.addLayer(base)
    emu.addLayer(routing)

    dns = DomainNameService()
    authority = dns.install('h14-dns')
    authority.addZone('.')
    authority.addZone('com.')
    authority.addZone('mastodon.com.')
    authority.setMaster()
    secondary = dns.install('h14-dns-secondary')
    secondary.addZone('.')
    secondary.addZone('com.')
    secondary.addZone('mastodon.com.')
    dns.getZone('mastodon.com.').addRecord('@ A 10.151.0.9')
    dns.getZone('mastodon.com.').addRecord('ca A 10.151.0.4')
    emu.addLayer(dns)
    emu.addBinding(Binding('h14-dns', filter=Filter(asn=151, nodeName='^dns$')))
    emu.addBinding(Binding('h14-dns-secondary', filter=Filter(asn=151, nodeName='^dns-secondary$')))

    ldns = DomainNameCachingService()
    ldns.install('h14-resolver')
    emu.addLayer(ldns)
    emu.addBinding(Binding('h14-resolver', filter=Filter(asn=151, nodeName='local-dns')))

    # Follow B25_pki/pki_with_dns.py; retain the same CA across regeneration.
    ca_store = RootCAStore(caDomain='ca.mastodon.com')
    saved_ca = HERE / 'runtime' / 'h14-ca'
    if saved_ca.exists():
        # RootCAStore.restore uses copytree and requires a nonexistent destination.
        Path(ca_store.getStorePath()).rmdir()
        ca_store.restore(str(saved_ca))
    else:
        ca_store.initialize()
        saved_ca.parent.mkdir(parents=True, exist_ok=True)
        ca_store.save(str(saved_ca))
        saved_ca.chmod(0o700)
    ca = CAService()
    ca.install('h14-ca').setCAStore(ca_store).installCACert(Filter(asn=151))
    emu.addLayer(ca)
    emu.addBinding(Binding('h14-ca', filter=Filter(asn=151, nodeName='^ca$')))

    # ------------------------------------------------------------------------
    # Mastodon application bundle with the same DNS identity and CA.
    # ------------------------------------------------------------------------
    mastodon = MastodonBundle(emu, name='h14-mastodon', resolver='10.151.0.53')
    mastodon.trustCA(saved_ca / '.step/certs/root_ca.crt')
    server = mastodon.server
    server.setHttps(18443)
    server.setDomain('mastodon.com')
    server.setAcmeUrl('https://ca.mastodon.com/acme/acme/directory')
    server.setPort(18443).setPortForwarding(18443)
    server.addAccount('admin', 'admin123456', email='admin@mastodon.com', admin=True)
    server.addAccount('alice', 'alice123456', email='alice@mastodon.com')
    server.addAccount('bob', 'bob123456', email='bob@mastodon.com')
    mastodon.addStorage('/etc/letsencrypt', 'h14-mastodon-letsencrypt')
    return emu, mastodon


def configure_bundle(mastodon, compiler):
    mastodon.addInternalNetwork('151', 'net0', ['10.151.0.9'], '10.151.0.254')
    mastodon.registerVolumes(compiler)
    mastodon.getContainer('app').updateServiceConfig({
        'build': {'context': './application-images/mastodon'}, 'pull_policy': 'never',
    })
    compiler.addContainerBundle(mastodon)


def copy_application_image(output):
    copytree(HERE.parents[1] / 'docker_images/mastodon', output / 'application-images/mastodon')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    emu, mastodon = build_scenario()
    emu.render()
    compiler = Docker(platform=Platform.AMD64 if args.platform == 'amd' else Platform.ARM64)
    configure_bundle(mastodon, compiler)
    emu.compile(compiler, str(output), override=True)
    copy_application_image(output)
    print(f'Generated {output}; build and start it with Docker Compose.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
