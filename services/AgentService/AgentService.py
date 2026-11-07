"""Native SEED service for container-local agents."""

from pathlib import Path
from seedemu.core import Service
from .AgentServer import AgentServer
from .ToolPackage import ToolPackage


class AgentService(Service):
    def __init__(self):
        super().__init__()
        self.addDependency('Base', False, False)
        self.addDependency('Routing', False, False)
        self._packages = {}
        self._nodes = set()

    def addToolPackage(self, package):
        if self._nodes:
            raise RuntimeError('add tool packages before rendering')
        if not isinstance(package, ToolPackage):
            raise TypeError('expected ToolPackage')
        if package.name in self._packages:
            raise ValueError('duplicate tool package')
        self._packages[package.name] = package
        return self

    def addToolsFrom(self, service):
        """A provider's getAgentTools() returns its service-owned ToolPackage."""
        package=service.getAgentTools()
        if isinstance(package,dict):package=ToolPackage(package['name'],package['source'])
        return self.addToolPackage(package)

    def addNetworkTools(self):
        return self.addToolPackage(ToolPackage('network', Path(__file__).parent/'tools/network'))

    def install(self, vnode):
        server = super().install(vnode)
        if server._identity is None:
            server.setIdentity(vnode)
        return server

    def _createServer(self):
        return AgentServer(self._packages)

    def _doConfigure(self, node, server):
        key = (node.getAsn(), node.getName())
        if key in self._nodes:
            raise ValueError('bind each agent to a separate node')
        self._nodes.add(key)

    def getName(self):
        return 'AgentService'

    def print(self, indent):
        return ' '*indent+'AgentService layer\n'
