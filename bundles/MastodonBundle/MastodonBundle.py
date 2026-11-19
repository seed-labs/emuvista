"""Mastodon application image with persistent state and exported agent tokens."""

from pathlib import Path
import json
import re

from seedemu.containerBundle import ContainerBundle
from seedemu.core import Node
from seedemu.core.enums import NodeRole
from seedemu.core.Volume import BaseVolume
from .server import SocialMediaServer
from bundles.DomainRegistryBundle.DomainRegistryBundle import _ApplicationContainer


class MastodonBundle(ContainerBundle):
    @staticmethod
    def getAgentTools():
        """Export bundle-owned tools without importing an agent framework."""
        return {'name': 'socialmedia', 'source': Path(__file__).parent / 'tools'}

    def __init__(self, emulator, name='mastodon',
                 image='handsonsecurity/emuvista-mastodon:1.0', resolver='10.150.0.54'):
        if not re.fullmatch(r'[a-z][a-z0-9-]*', name):
            raise ValueError('Invalid Mastodon bundle name')
        super().__init__(emulator=emulator)
        self._name, self._image, self._resolver = name, image, resolver
        self.server = SocialMediaServer().setHttp(18084).setPortForwarding(18084)
        self._required_internal_address_count = 1
        self._containers = {'app': _ApplicationContainer(name=name, emulator=emulator)}
        self._volumes = []
        self._exports = []
        self._ca_certificate = None
        self._site_title = None
        self._bootstrap_email_domains = ()
        for path in ('/var/lib/postgresql', '/var/lib/redis', '/var/lib/mastodon',
                     '/opt/mastodon/public/system'):
            self.addStorage(path, f'{name}-http-' + path.rsplit('/', 1)[-1])

    def trustCA(self, path):
        """Install the scenario CA before ACME and application startup."""
        self._ca_certificate = Path(path).read_text()
        return self

    def addStorage(self, target, name):
        self._volumes.append(BaseVolume(type='volume', source=name, name=name, target=target))
        return self

    def setStorage(self, target, name):
        """Replace the named volume for one application path."""
        self._volumes = [volume for volume in self._volumes
                         if volume.asDict()['target'] != target]
        return self.addStorage(target, name)

    def setBootstrap(self, *, site_title=None, email_domains=()):
        """Customize the site title and account-bootstrap email allowlist."""
        self._site_title = site_title
        self._bootstrap_email_domains = tuple(email_domains)
        return self

    def exportAgentToken(self, username, volume):
        if not any(item['username'] == username for item in self.server._token_exports):
            raise ValueError('Configure exportToken before sharing agent credentials')
        self.addStorage('/run/agent-credentials/' + username, volume)
        self._exports.append(username)
        return self

    def registerVolumes(self, compiler):
        for volume in self._volumes:
            compiler._addVolume(volume)

    def configure(self):
        if self._is_configured:
            return
        networks = self.getInternalNetworks()
        if len(networks) != 1:
            raise ValueError('Configure exactly one Mastodon network')
        net = networks[0]
        self.getContainer('app').joinInternalNetwork(
            net['asn'], net['network_name'], net['ip_addresses'][0], self._name, net['default_route'])
        super().configure()

    def install(self):
        self.configure()
        node = Node(self._name, NodeRole.Host, 0)
        self.server.install(node)
        root = Path(self._name + '-config')
        root.mkdir(mode=0o700)
        for file in node.getFiles():
            target, content = file.get()
            # Build scripts remain owned by the application image.
            if target.endswith('/install.sh'):
                continue
            if target.endswith('/initialize.rb'):
                if self._bootstrap_email_domains:
                    content = ("Rails.configuration.x.email_domains_allowlist = "
                               "Array(Rails.configuration.x.email_domains_allowlist) | "
                               + json.dumps(self._bootstrap_email_domains) + '\n' + content)
                if self._site_title is not None:
                    content = content.replace("Setting.site_title = 'H16 Mastodon'",
                                              'Setting.site_title = ' + json.dumps(self._site_title))
            path = root / Path(target).name
            path.write_text(content)
            path.chmod(0o600)
        commands = ['#!/bin/bash', 'set -e',
                    'cp /bundle-config/* /opt/mastodon-service/',
                    'chmod 644 /opt/mastodon-service/*',
                    'chmod 755 /opt/mastodon-service/run.sh',
                    'rm -f /run/mastodon-bundle.ready',
                    'bash /opt/mastodon-service/start.sh > /var/log/mastodon-initialize.log 2>&1']
        if self._ca_certificate is not None:
            (root / 'root-ca.crt').write_text(self._ca_certificate)
            commands[2:2] = [
                'cp /bundle-config/root-ca.crt /usr/local/share/ca-certificates/mastodon-bundle.crt',
                'update-ca-certificates',
            ]
        for name in self._exports:
            export = next(item for item in self.server._token_exports if item['username'] == name)
            commands.append(
                f'install -d -m 700 -o 10001 -g 10001 /run/agent-credentials/{name} && '
                f'install -m 600 -o 10001 -g 10001 {export["path"]} '
                f'/run/agent-credentials/{name}/credentials.json')
        commands += ['touch /run/mastodon-bundle.ready', 'exec sleep infinity']
        container = self.getContainer('app')
        container.setFile('/application-start.sh', '\n'.join(commands) + '\n')
        # PreparedContainer invokes the wrapper using sh; execute this Bash script explicitly.
        container.setFile('/launch-mastodon.sh', '#!/bin/sh\nexec bash /application-start.sh\n')
        container.setEntrypointWrapper('/launch-mastodon.sh', [])
        port = self.server._port
        probe = (f'curl -fsS --max-time 5 --resolve {self.server._domain}:{port}:127.0.0.1 '
                 f'{self.server._scheme}://{self.server._domain}:{port}/api/v2/instance >/dev/null')
        network = self.getInternalNetworks()[0]
        config = {
            'image': self._image, 'cap_add': ['NET_ADMIN'], 'dns': [self._resolver],
            'volumes': [f'./{root}:/bundle-config:ro'] + [
                f'{v.asDict()["source"]}:{v.asDict()["target"]}' for v in self._volumes],
            'labels': {'org.emuvista.bundle': type(self).__name__,
                       'org.seedsecuritylabs.seedemu.meta.asn': network['asn'],
                       'org.seedsecuritylabs.seedemu.meta.nodename': self._name,
                       'org.seedsecuritylabs.seedemu.meta.role': 'Host',
                       'org.seedsecuritylabs.seedemu.meta.net.0.name': network['network_name'],
                       'org.seedsecuritylabs.seedemu.meta.net.0.address': network['ip_addresses'][0]},
            'healthcheck': {'test': ['CMD-SHELL',
                f'test -f /run/mastodon-bundle.ready && {probe}'],
                'interval': '10s', 'timeout': '8s', 'retries': 30, 'start_period': '180s'},
        }
        if self.server._forwarded_port is not None:
            config['ports'] = [f'127.0.0.1:{self.server._forwarded_port}:{port}']
        container.updateServiceConfig(config)
        return super().install()
