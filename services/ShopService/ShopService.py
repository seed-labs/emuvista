"""A marketplace installed on ordinary SEED hosts."""

from seedemu.core import BaseSystem, Service, SystemProfile
from seedemu.compiler import DockerImage, Platform
from .ShopServer import ShopServer

PROFILE = SystemProfile('emuvista-shop', subset=BaseSystem.DEFAULT)


class ShopService(Service):
    def __init__(self, resolver=None):
        super().__init__()
        self._resolver = resolver
        self.addDependency('Base', False, False)
        self.addDependency('Routing', False, False)
        image = DockerImage('handsonsecurity/emuvista-shop:1.0', [
            'curl', 'iproute2', 'iputils-ping', 'python3', 'tini', 'zsh', 'nano',
            'vim-nox', 'mtr-tiny', 'tcpdump', 'termshark', 'dnsutils', 'jq',
            'ipcalc', 'netcat-openbsd',
        ])
        self.setDockerImage(PROFILE, image, Platform.AMD64)

    def _createServer(self):
        return ShopServer(PROFILE, self._resolver)

    def install(self, vnode):
        server = super().install(vnode)
        server._name = vnode
        return server

    def _doConfigure(self, node, server):
        server.configure(node)

    def getName(self):
        return 'ShopService'

    def print(self, indent):
        return ' ' * indent + 'ShopService\n'
