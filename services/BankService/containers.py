"""Routing helpers for external applications on SEED networks."""

from ipaddress import IPv4Address

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer
from seedemu.core.enums import NetworkType


class RoutedContainer(PreparedContainer):
    """Add routing tools to prepared Alpine or Debian application images."""

    def _computeDockerfile(self):
        image = self.service.pop('image')
        self.service['build'] = './' + self.getHostname()
        lines = [f'FROM {image}', 'USER root',
                 'RUN if ! command -v ip >/dev/null 2>&1; then '
                 'if command -v apk >/dev/null 2>&1; then apk add --no-cache iproute2; '
                 'else apt-get update && apt-get install -y --no-install-recommends iproute2 '
                 '&& rm -rf /var/lib/apt/lists/*; fi; fi']
        lines.extend(self._addFile(path, content) for path, content in self._files.items())
        return '\n'.join(lines) + '\n'


class RoutedBundle(ContainerBundle):
    """Assign external containers to existing rendered networks."""

    def configure(self):
        if getattr(self, '_configured', False):
            return
        super().configure()
        if self._emulator is None or not self._emulator.rendered():
            raise RuntimeError('render the emulator before configuring a bundle')
        missing = [c for c in self._containers.values() if not c._internal_networks]
        allocated = set()
        if missing:
            self._required_emu_network_address_number = len(missing)
            if not self._default_internal_network:
                self.allocateEmuNetworkAddress()
                allocated.update(self._default_internal_network['ip_addresses'])
            net = self._default_internal_network
            if not net or len(net['ip_addresses']) < len(missing):
                raise ValueError(f'bundle requires {len(missing)} free addresses')
            for c, ip in zip(missing, net['ip_addresses']):
                c.joinInternalNetwork(net['network'], c.getHostname(), ip, net['default_route'])
        networks, occupied = {}, set()
        for (scope, kind, _), obj in self._emulator.getRegistry().getAll().items():
            if kind == 'net':
                key = obj.getName() if obj.getType() == NetworkType.Bridge else f'net_{scope}_{obj.getName()}'
                networks[key] = obj
            elif kind in ('hnode', 'rnode', 'brdnode'):
                occupied.update(str(i.getAddress()) for i in obj.getInterfaces())
        self._addresses = {}
        for role, c in self._containers.items():
            if len(c._internal_networks) != 1:
                raise ValueError('each bundle component requires one emulated network')
            network, _, address, route = c._internal_networks[0]
            net, ip = networks.get(network), IPv4Address(address)
            if net is None or ip not in net.getPrefix():
                raise ValueError(f'{role}: address is outside the rendered network')
            reserved = net.getAttribute('container_bundle_reserved_addresses', set())
            if (address in occupied or address == str(net.getDefaultRouter()) or
                    ip in {net.getPrefix().network_address, net.getPrefix().broadcast_address} or
                    (ip in reserved and address not in allocated)):
                raise ValueError(f'{role}: address is occupied or reserved')
            if route != str(net.getDefaultRouter()):
                raise ValueError(f'{role}: default route must use the emulated router')
            net.setAttribute('container_bundle_reserved_addresses', reserved | {ip})
            occupied.add(address)
            self._addresses[role] = address
        self._configured = True

    def getAddress(self, role='gateway'):
        if role in getattr(self, '_addresses', {}):
            return self._addresses[role]
        c = self.getContainer(role)
        if c._internal_networks:
            return c._internal_networks[0][2]
        net = self._default_internal_network
        if net:
            return net['ip_addresses'][list(self._containers).index(role)]
        raise RuntimeError('assign a network before reading bundle addresses')

    def install(self):
        containers = self._containers
        self._containers = {c.getHostname(): c for c in containers.values()}
        try:
            return super().install()
        finally:
            self._containers = containers
