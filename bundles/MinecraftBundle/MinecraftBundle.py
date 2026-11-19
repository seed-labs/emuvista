"""Dockerized Minecraft Java server attached to a rendered SEED network."""
from pathlib import Path
import shlex

from seedemu.containerBundle import ContainerBundle
from seedemu.core.Volume import BaseVolume
from .containers import RoutedContainer


class MinecraftBundle(ContainerBundle):
    @staticmethod
    def getAgentTools():
        """Export the bundle-owned Minecraft tool package."""
        return {'name': 'minecraft', 'source': Path(__file__).parent / 'tools'}

    @staticmethod
    def getAgentBridge():
        """Return the persistent Mineflayer bridge source directory."""
        return Path(__file__).parent / 'bridge'

    def __init__(self, emulator, *, image, environment, name='minecraft', resolver=None,
                 host_port=25565, volume='minecraft-data', startup_probe_url=None):
        super().__init__(emulator=emulator)
        self._name = name
        self._image = image
        self._environment = dict(environment)
        self._resolver = resolver
        self._host_port = host_port
        self._volume = volume
        self._startup_probe_url = startup_probe_url
        self._required_internal_address_count = 1
        self._containers = {'server': RoutedContainer(name=name, emulator=emulator)}

    def configure(self):
        if self._is_configured:
            return
        network, = self.getInternalNetworks()
        self.getContainer('server').joinInternalNetwork(
            network['asn'], network['network_name'], network['ip_addresses'][0],
            self._name, network['default_route'])
        super().configure()

    def install(self):
        self.configure()
        container = self.getContainer('server')
        startup = '#!/bin/sh\n'
        if self._startup_probe_url:
            startup += (
                'echo "[network-wait] Waiting up to 180s for Minecraft download access"\n'
                'timeout 180 sh -c \'\n'
                '  until curl --fail --silent --show-error --location --connect-timeout 5 --max-time 10 --output /dev/null "$1"; do\n'
                '    echo "[network-wait] Download endpoint unavailable; retrying in 5s" >&2\n'
                '    sleep 5\n'
                '  done\n'
                '\' network-wait ' + shlex.quote(self._startup_probe_url) + ' || {\n'
                '  echo "[network-wait] Timed out or probe failed; check DNS, routing and Internet access" >&2\n'
                '  exit 1\n'
                '}\n'
                'echo "[network-wait] Download endpoint reachable; starting Minecraft"\n'
            )
        startup += 'exec /start "$@"\n'
        container.setFile('/application-start.sh', startup)
        container.setEntrypointWrapper('/application-start.sh', [])
        config = {
            'image': self._image, 'environment': self._environment,
            'volumes': [f'{self._volume}:/data'], 'stop_grace_period': '2m',
            'healthcheck': {'interval': '10s', 'timeout': '5s',
                            'retries': 12, 'start_period': '5m'},
        }
        if self._host_port is not None:
            config['ports'] = [f'{self._host_port}:{self._environment.get("SERVER_PORT", 25565)}']
        if self._resolver:
            config['dns'] = [self._resolver]
        container.updateServiceConfig(config)
        return super().install()

    def registerVolumes(self, compiler):
        compiler._addVolume(BaseVolume(type='volume', source=self._volume,
                                       name=self._volume, target='/data'))
