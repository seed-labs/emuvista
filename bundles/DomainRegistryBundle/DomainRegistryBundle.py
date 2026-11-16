"""Domain Registry bundle and shared domain application deployment plumbing."""

from hashlib import sha256
from pathlib import Path
import re

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer
from seedemu.core import Node
from seedemu.core.enums import NodeRole
from .server import NamingoRegistryServer


class _ApplicationContainer(PreparedContainer):
    def _generateDockerfile(self):
        """Mount generated wrappers instead of rebuilding the application image."""
        mounts = list(self._service.get('volumes', []))
        for target, content in self._files.items():
            source = sha256(target.encode()).hexdigest()
            Path(source).write_text(content)
            Path(source).chmod(0o600)
            mounts.append(f'./{self.getHostname()}/{source}:{target}:ro')
        self.updateServiceConfig({'volumes': mounts})
        return ''


class DomainApplicationBundle(ContainerBundle):
    """One independent application image, configured with existing service templates.

    A detached Node collects configuration only: it is never bound to the emulator.
    Package/download commands belong to docker_images and are not executed here.
    Post-copy commands (permissions, certificates) execute before local startup.
    """

    def __init__(self, emulator, name, image, server, resolver):
        if not re.fullmatch(r'[a-z][a-z0-9-]*', name):
            raise ValueError('Invalid domain bundle name')
        super().__init__(emulator=emulator)
        self.server = server
        self._name, self._image, self._resolver = name, image, resolver
        self._required_internal_address_count = 1
        self._containers = {'app': _ApplicationContainer(name=name, emulator=emulator)}

    def configure(self):
        if self._is_configured:
            return
        networks = self.getInternalNetworks()
        if len(networks) != 1:
            raise ValueError('Configure exactly one internal network for the application')
        net = networks[0]
        self.getContainer('app').joinInternalNetwork(
            net['asn'], net['network_name'], net['ip_addresses'][0],
            self._name, net['default_route'])
        super().configure()

    def getAddress(self):
        self.configure()
        return str(self.getInternalNetworks()[0]['ip_addresses'][0])

    def install(self):
        self.configure()
        node = Node(self._name, NodeRole.Host, 0)
        self.server.install(node)
        root = Path(self._name + '-config')
        root.mkdir(mode=0o700)
        for file in node.getFiles():
            target, content = file.get()
            path = root / 'rootfs' / target.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(0o644)
        commands = ['#!/bin/bash', 'set -e',
                    'while IFS= read -r -d "" source; do\n'
                    '    target="${source#/bundle-config/rootfs}"\n'
                    '    mkdir -p "$(dirname "$target")"\n'
                    '    cp "$source" "$target"\n'
                    'done < <(find /bundle-config/rootfs -type f -print0)',
                    'rm -f /run/domain-bundle.ready',
                    *node.getBuildCommandsAtEnd()]
        commands.extend(command + (' &' if fork else '')
                        for command, fork in node.getStartCommands())
        commands += ['touch /run/domain-bundle.ready', 'exec sleep infinity']
        (root / 'start.sh').write_text('\n'.join(commands) + '\n')
        (root / 'start.sh').chmod(0o600)
        container = self.getContainer('app')
        container.setFile('/application-start.sh', '#!/bin/sh\nexec bash /bundle-config/start.sh\n')
        container.setEntrypointWrapper('/application-start.sh', [])
        network = self.getInternalNetworks()[0]
        config = {
            'image': self._image,
            'cap_add': ['NET_ADMIN'],
            'dns': [self._resolver],
            'volumes': [f'./{root}:/bundle-config:ro'],
            'labels': {
                'org.emuvista.bundle': type(self).__name__,
                'org.seedsecuritylabs.seedemu.meta.asn': network['asn'],
                'org.seedsecuritylabs.seedemu.meta.nodename': self._name,
                'org.seedsecuritylabs.seedemu.meta.net.0.address': self.getAddress(),
            },
            'healthcheck': {'test': ['CMD-SHELL',
                'test -f /run/domain-bundle.ready && '
                'curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8080/ >/dev/null'],
                'interval': '10s', 'timeout': '8s', 'retries': 30, 'start_period': '120s'},
        }
        if self.server._forwarded_port is not None:
            config['ports'] = [f'127.0.0.1:{self.server._forwarded_port}:8080']
        container.updateServiceConfig(config)
        return super().install()


class DomainRegistryBundle(DomainApplicationBundle):
    def __init__(self, emulator, name='registry',
                 image='handsonsecurity/emuvista-namingo:1.0', resolver='10.150.0.54'):
        super().__init__(emulator, name, image, NamingoRegistryServer(), resolver)
