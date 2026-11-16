"""FOSSBilling with Namingo, DNS Hosting and the existing FakePayment checkout."""

from pathlib import Path

from .server import FossBillingRegistrarServer
from bundles.DomainRegistryBundle.DomainRegistryBundle import DomainApplicationBundle


class DomainRegistrarBundle(DomainApplicationBundle):
    @staticmethod
    def getAgentTools():
        """Export bundle-owned tools without importing an agent framework."""
        return {'name': 'domain_purchase', 'source': Path(__file__).parent / 'tools'}

    def __init__(self, emulator, name='fossbilling',
                 image='handsonsecurity/emuvista-fossbilling:1.0', resolver='10.150.0.54'):
        super().__init__(emulator, name, image, FossBillingRegistrarServer(), resolver)

    def connectRegistry(self, registry):
        """Resolve EPP endpoints after render, before either bundle is installed."""
        server = self.server
        if server.getRegistry() != registry._name:
            raise ValueError('Selected Registry name does not match the Bundle')
        tlds = list(server._tlds) if server._tlds is not None else registry.server.getTlds()
        if set(tlds) - set(registry.server.getTlds()) or set(server._prices) - set(tlds):
            raise ValueError('Registrar products must use Registry-managed TLDs')
        registry.server.addEppRegistrar(server._username, server._password, server._prefix,
                                       self.getAddress(), server.getReservedDomains())
        server._connection = {
            'host': registry.getAddress(), 'port': registry.server.getEppPort(),
            'clid': server._username, 'pw': server._password, 'registrarprefix': server._prefix,
            'local_cert': '/var/www/fossbilling/ssl/namingo_cert.pem',
            'local_pk': '/var/www/fossbilling/ssl/namingo_key.pem',
        }
        server._settings['url'] = f'http://{self.getAddress()}:8080/'
        server._settings['prices'] = {'.' + tld: list(server._prices.get(tld, ['11.99'] * 3))
                                      for tld in tlds}
        return self

    def connectPayment(self, payment):
        """Resolve payment settings; preauthorize this address before emu.render()."""
        payment.authorizeCallback(f'http://{self.getAddress()}:8080')
        self.server._payment_settings = payment.getConnectionSettings()
        self.server._payment_secret = payment.getSharedSecret()
        browser_urls = {}
        host_port, payment_port = self.server.getPortForwarding(), payment.getPortForwarding()
        if host_port is not None and payment_port is not None:
            for hostname in ('localhost', '127.0.0.1'):
                origin = hostname if host_port == 80 else f'{hostname}:{host_port}'
                browser_urls[origin] = f'http://{hostname}:{payment_port}/pay'
        self.server._payment_settings['browser_urls'] = browser_urls
        return self
