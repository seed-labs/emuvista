"""Native SEED service for container-local agents."""

from pathlib import Path
import re
from seedemu.core import Service
from .AgentServer import AgentServer
from .ToolPackage import ToolPackage


class AgentService(Service):
    def __init__(self, tools=(), environment_file=None):
        super().__init__()
        self.addDependency('Base', False, False)
        self.addDependency('Routing', False, False)
        self._packages = {}
        self._nodes = set()
        self._person_ids = set()
        self._environment_file = Path(environment_file).resolve() if environment_file else None
        if self._environment_file and not self._environment_file.is_file():
            raise ValueError('environment file not found')
        for package in tools:
            self.addToolPackage(package)

    def addToolPackage(self, package):
        if self._nodes:
            raise RuntimeError('add tool packages before rendering')
        if isinstance(package, dict):
            package = ToolPackage(package['name'], package['source'],
                                  configuration=package.get('configuration'),
                                  requirements=package.get('requirements', ()),
                                  software=package.get('software', ()))
        if not isinstance(package, ToolPackage):
            raise TypeError('expected ToolPackage or tool package export')
        if package.name in self._packages:
            existing = self._packages[package.name]
            if (existing.source != package.source or existing.manifest != package.manifest
                    or existing.requirements != package.requirements or existing.software != package.software):
                raise ValueError('conflicting tool package: ' + package.name)
            for instance, settings in package.configuration.items():
                if instance in existing.configuration and existing.configuration[instance] != settings:
                    raise ValueError('conflicting tool instance: ' + instance)
                existing.configuration[instance] = settings
            return self
        self._packages[package.name] = package
        return self

    def addToolsFrom(self, service):
        """A provider's getAgentTools() returns its service-owned ToolPackage."""
        return self.addToolPackage(service.getAgentTools())

    def addNetworkTools(self):
        return self.addToolPackage(ToolPackage('network', Path(__file__).parent / 'tools/network'))

    def addPkiTools(self):
        """Copy PKI tools into agents; all selected tools are available by default."""
        return self.addToolPackage(ToolPackage(
            'pki', Path(__file__).parent / 'tools/pki',
            requirements=('pydantic>=2,<3',), software=('openssl', 'coreutils'),
        ))

    def install(self, vnode):
        if not isinstance(vnode, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,49}', vnode):
            raise ValueError('invalid agent virtual node name')
        server = super().install(vnode)
        server.vnode = vnode
        if not server._persona:
            server.setDisplayName('Agent ' + vnode)
        return server

    def createagent(self, config):
        """Create one person's agent; normal SEED bindings select its host."""
        server = self._createServer().setPersona(config)
        index = 1
        while 'agent_' + str(index) in self._pending_targets:
            index += 1
        server.vnode = 'agent_' + str(index)
        self._pending_targets[server.vnode] = server
        return server

    def _createServer(self):
        return AgentServer(self._packages, self._environment_file)

    def _doConfigure(self, node, server):
        key = (node.getAsn(), node.getName())
        if key in self._nodes:
            raise ValueError('bind each agent to a separate node')
        if not server._persona:
            raise ValueError('setPersona with a stable person id before rendering')
        person_id = server._persona['id']
        if person_id in self._person_ids:
            raise ValueError('duplicate person id: ' + person_id)
        self._nodes.add(key)
        self._person_ids.add(person_id)

    def getName(self):
        return 'AgentService'

    def print(self, indent):
        return ' ' * indent + 'AgentService layer\n'
