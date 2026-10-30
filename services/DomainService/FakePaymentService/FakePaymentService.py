"""Provide an independent simulated payment checkout."""
import json
from pathlib import Path
from seedemu.core import Server, Service


FakePaymentFileTemplates = {
    name: (Path(__file__).resolve().parent / 'templates' / name).read_text(encoding='utf-8')
    for name in (
        'checkout-server.py',
    )
}


class FakePaymentServer(Server):
    """Manage an independent checkout endpoint and its callback authorization."""

    def __init__(self):
        """Initialize demonstration settings."""
        super().__init__()
        self._forwarded_port = 18083
        self._secret = 'fake-payment-demo-secret'
        self._port = 8080
        self._settings = None
        self._notify_origin = None
        self.appendClassName('FakePaymentService')
        self.setDisplayName('FakePayment Checkout')

    def setPortForwarding(self, host_port):
        """Set the host Web port; None disables forwarding."""
        self._forwarded_port = host_port
        return self

    def getPortForwarding(self):
        """Return the checkout host port, or None if forwarding is disabled."""
        return self._forwarded_port

    def getSharedSecret(self):
        """Return the signing secret for a payment adapter."""
        return self._secret

    def authorizeCallback(self, origin):
        """Allow one client origin to receive signed payment notifications."""
        if self._notify_origin is not None and self._notify_origin != origin:
            raise ValueError('Each checkout supports one callback origin')
        self._notify_origin = origin
        self._settings['notify_origin'] = origin

    def getConnectionSettings(self):
        """Return a copy of the resolved checkout settings."""
        return dict(self._settings)

    def setSharedSecret(self, secret):
        """Set the shared checkout and adapter signing secret."""
        self._secret = secret
        return self

    def setPort(self, port):
        """Set the internal listening port."""
        self._port = port
        return self

    def _configureEndpoint(self, node):
        """Resolve this checkout's own address."""
        self._settings = {
            'port': self._port,
            'payment_url': f'http://{node.getInterfaces()[0].getAddress()}:{self._port}/pay',
            'notify_origin': self._notify_origin,
        }

    def install(self, node):
        """Install only the checkout endpoint on its bound node."""
        node.addSoftware('python3')
        node.setFile('/opt/fake-payment/checkout-server.py', FakePaymentFileTemplates['checkout-server.py'])
        node.setFile('/opt/fake-payment/payment-config.json', json.dumps(self._settings))
        node.setFile('/opt/fake-payment/secret', self._secret + '\n')
        node.addBuildCommandAtEnd('chmod 600 /opt/fake-payment/secret')
        node.appendStartCommand('chmod 600 /opt/fake-payment/secret')
        node.appendStartCommand('python3 /opt/fake-payment/checkout-server.py > /var/log/fake-payment.log 2>&1', fork=True)
        if self._forwarded_port is not None:
            node.addPortForwarding(self._forwarded_port, self._port)

    def print(self, indent):
        """Return the instance description."""
        return ' ' * indent + 'FakePayment checkout server\n'


class FakePaymentService(Service):
    """Provide independent simulated payment endpoints."""

    def __init__(self):
        """Declare network dependencies."""
        super().__init__()
        for name in ('Base', 'Routing'):
            self.addDependency(name, False, False)

    def _doConfigure(self, node, server):
        """Pass the bound node to the checkout before installation."""
        server._configureEndpoint(node)

    def _createServer(self):
        """Create a checkout instance."""
        return FakePaymentServer()

    def getName(self):
        """Return the service name."""
        return 'FakePaymentService'

    def print(self, indent):
        """Return the service description."""
        return ' ' * indent + 'FakePaymentServiceLayer\n'
