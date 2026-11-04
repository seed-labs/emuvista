"""Native DNS subclass with hosting APIs and dynamic update authorization."""
import base64
import json
from pathlib import Path
import secrets
import shlex
from typing import List

from seedemu.services import DomainNameService, DomainNameServer
from seedemu.mergers.DefaultDomainNameServiceMerger import DefaultDomainNameServiceMerger


DnsFileTemplates = {
    name: (Path(__file__).resolve().parent / 'templates' / name).read_text(encoding='utf-8')
    for name in (
        'bind-api-settings.env',
        'init-bind-api-nameserver.php',
        'patch-bind-api-soa-types.php',
        'start-bind-api-nameserver.sh',
    )
}


def apt_install(packages):
    """Update indexes and install packages in one Docker layer."""
    options = '-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 '
    return ('apt-get ' + options + 'update && '
            'DEBIAN_FRONTEND=noninteractive apt-get ' + options + 'install -y '
            + ' '.join(shlex.quote(package) for package in packages.split()))


def composer_install(directory):
    """Run Composer with the service PHP 8.5 and retain dependency checks."""
    return ('cd ' + shlex.quote(directory) + ' && '
            'COMPOSER_ALLOW_SUPERUSER=1 '
            'php8.5 /usr/bin/composer install --no-dev --prefer-dist --no-interaction')


class _DnsHostingPair:
    """Hosting configuration and credentials shared with DNS consumers."""

    def __init__(self):
        """Set default virtual nodes and the hosting domain."""
        self._primary = 'hosted-dns-primary'
        self._secondary = 'hosted-dns-secondary'
        self._domain = 'example.com'
        self._api_clients = []

    def setNameServers(self, primary, secondary, domain='example.com'):
        """Select DNS virtual nodes and their existing static zone."""
        if primary == secondary:
            raise ValueError('Distinct primary and secondary DNS virtual nodes are required')
        domain = domain.lower().rstrip('.')
        self._primary, self._secondary, self._domain = primary, secondary, domain
        return self

    def addRegistrarToRateLimitWhitelist(self, virtual_node):
        """Exempt the bound registrar from API rate limits; authentication remains required."""
        self._api_clients.append(virtual_node)
        return self

    def getSettings(self):
        """Return resolved public DNS connection settings."""
        return dict(self._settings)

    def getConfiguration(self):
        """Return DNS settings and independent copies of API credentials."""
        return self.getSettings(), {role: dict(value) for role, value in self._credentials.items()}


class DnsServer(DomainNameServer):
    """Install authoritative DNS and optional hosting API on this server's node."""

    def __init__(self):
        super().__init__()
        self._hosting_configuration = None

    def install(self, node, dns):
        """Install base DNS and the prepared hosting configuration on this node."""
        # Run the complete parent installation unchanged.
        super().install(node, dns)

        # --------------------------------------------------------------------
        # Additional DNS hosting installation
        # --------------------------------------------------------------------
        if self._hosting_configuration is None:
            return
        role, settings, credentials, client_ips = self._hosting_configuration
        node.setDisplayName(settings['ns1' if role == 'primary' else 'ns2'])
        node.addSoftware('ca-certificates software-properties-common git unzip')
        for command in (
            'add-apt-repository --no-update -y ppa:ondrej/php',
            apt_install('composer'),
            apt_install('php8.5-cli php8.5-sqlite3 php8.5-swoole php8.5-mbstring '
                        'php8.5-xml php8.5-curl php8.5-gmp php8.5-intl'),
            'useradd --system --home /var/lib/bind9-api --shell /usr/sbin/nologin bind9-api',
            'git clone https://github.com/getnamingo/bind9-api.git /opt/bind9-api '
            '&& cd /opt/bind9-api && git checkout f196ca0625b4341f3952d576ea2d223f4b2b6434',
            composer_install('/opt/bind9-api'),
        ):
            node.addBuildCommand(command)
        node.addBuildCommandAtEnd('usermod -aG bind bind9-api')
        path = '/opt/dns-hosting/bind-api-credentials.json'
        node.setFile(path, json.dumps(credentials) + '\n')
        node.addBuildCommandAtEnd('chmod 600 ' + path)
        node.setFile('/opt/bind9-api/.env', DnsFileTemplates['bind-api-settings.env'].replace('__ADDRESS__', settings[role]).replace('__DOMAIN__', settings['domain']))
        for name in ('start-bind-api-nameserver.sh', 'init-bind-api-nameserver.php', 'patch-bind-api-soa-types.php'):
            content = DnsFileTemplates[name].replace('__SECONDARY_IP__', settings['secondary']).replace('__API_CLIENTS__', ', '.join(repr(ip) for ip in client_ips))
            node.setFile('/opt/dns-hosting/' + name, content)
        node.addBuildCommandAtEnd('php8.5 /opt/dns-hosting/patch-bind-api-soa-types.php')
        node.insertStartCommand(0, 'bash /opt/dns-hosting/start-bind-api-nameserver.sh ' + role)


class DnsUpdateAuthorization:
    """DNS update credentials populated by DNS rendering and read by publishers."""

    def __init__(self, zones):
        self.__zones = tuple(zones)
        self.__credentials = {}

    def getZones(self):
        """Return authorized zone names."""
        return self.__zones

    def getCredentials(self, zone):
        """Read the address and TSIG key after rendering."""
        if zone not in self.__credentials:
            raise RuntimeError('DNS authorization is not ready; render DomainNameService first')
        return self.__credentials[zone]

    def _setCredentials(self, zone, address, key):
        """Populate credentials from the DNS service."""
        self.__credentials[zone] = (address, key)


class DnsService(DomainNameService):
    """Extend native DNS with hosting APIs and publisher-independent update authorizations."""

    def __init__(self, autoNameServer=True):
        """Preserve base initialization and track authorizations."""
        super().__init__(autoNameServer)
        self._update_authorizations = []
        self._hosting = []

    def _createServer(self):
        return DnsServer()

    def _prepareHostingConfiguration(self, hosting, primary, secondary, client_ips):
        """Validate resolved DNS nodes and prepare hosting settings and credentials."""
        for vnode in (hosting._primary, hosting._secondary):
            if vnode not in self.getPendingTargets():
                raise ValueError(f'{vnode} must be installed by DomainNameService')
            server = self.getPendingTargets()[vnode]
            if server.getZones() != [hosting._domain + '.'] or server.getIncludePath(hosting._domain + '.') is not None:
                raise ValueError('Hosted DNS nodes must exclusively host the selected zone without custom includes')
        primary_ip = str(primary.getInterfaces()[0].getAddress())
        secondary_ip = str(secondary.getInterfaces()[0].getAddress())
        if self.getMasterIp().get(hosting._domain + '.') != [primary_ip]:
            raise ValueError('Set only the primary DNS node as master for the hosting zone')
        records = self.getZone(hosting._domain + '.').getRecords()
        if (f'ns1.{hosting._domain}. A {primary_ip}' not in records
                or f'ns2.{hosting._domain}. A {secondary_ip}' not in records):
            raise ValueError('Install primary before secondary so ns1/ns2 match their bound addresses')
        hosting._credentials = {role: {'username': 'hosting', 'password': secrets.token_hex(32)}
                                for role in ('primary', 'secondary')}
        hosting._settings = {
            'domain': hosting._domain,
            'primary': str(primary.getInterfaces()[0].getAddress()),
            'secondary': str(secondary.getInterfaces()[0].getAddress()),
            'ns1': 'ns1.' + hosting._domain, 'ns2': 'ns2.' + hosting._domain,
            'soaemail': 'hostmaster@' + hosting._domain,
        }

        for role, vnode in (('primary', hosting._primary), ('secondary', hosting._secondary)):
            server = self.getPendingTargets()[vnode]
            if not isinstance(server, DnsServer):
                raise ValueError('Hosting requires DNS nodes installed by DnsService')
            server._hosting_configuration = (
                role, dict(hosting._settings), dict(hosting._credentials[role]), list(client_ips),
            )

    def addHosting(self, primary, secondary, domain='example.com'):
        """Add hosting to existing DNS nodes without another virtual node."""
        hosting = _DnsHostingPair().setNameServers(primary, secondary, domain)
        self._hosting.append(hosting)
        return hosting

    def getZoneServerNames(self, domain: str) -> List[str]:
        """!
        @brief Get the names of servers hosting the given zone. This only works
        if the server was installed by using the "installByName" call.

        @param domain domain.

        @returns list of tuple of (node name, asn)
        """
        info = []
        targets = self.getPendingTargets()

        for (vnode, sobj) in targets.items():
            server: DomainNameServer = sobj

            hit = False

            for zone in server.getZones():
                if zone == domain:
                    info.append(vnode)
                    hit = True
                    break
            
            if hit: continue
        
        return info

    def authorizeZoneUpdates(self, zones):
        """    Create a publisher-independent authorization for NS/A/AAAA updates below
        each zone, protecting its apex and name servers. Pass zone names only; DNS
        discovers their servers and primary from its own configuration. Returns credentials
        resolved during DNS rendering; consumers must render after this layer.
        """
        normalized, servers, hosted = {}, {}, {}
        for value in zones:
            zone_name = value.removesuffix('.').lower()
            names = self.getZoneServerNames(zone_name + '.')
            if not names:
                raise ValueError(f'No DNS servers host {zone_name}.')
            normalized[zone_name] = tuple(names)
            for name in names:
                server = self._pending_targets[name]
                if server.getIncludePath(zone_name + '.') is not None:
                    raise ValueError(f'{name} already has a custom include for {zone_name}.')
                servers[name] = server
                hosted.setdefault(name, set()).add(zone_name + '.')
        for name, server in servers.items():
            if {zone.rstrip('.').lower() + '.' for zone in server.getZones()} != hosted[name]:
                raise ValueError(f'All zones hosted by {name} must be included in zones')
        # Mutate includes only after complete validation.
        for zone_name, names in normalized.items():
            for name in names:
                servers[name].setInclude(zone_name + '.', f'/etc/bind/update-{zone_name}.conf')
        authorization = DnsUpdateAuthorization(zone_name + '.' for zone_name in normalized)
        self._update_authorizations.append((authorization, normalized))
        return authorization

    def __renderUpdateAuthorizations(self, emulator):
        """Render DNS authorization and populate credentials."""
        def new_key(identity):
            secret = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
            return f'key "{identity}" {{ algorithm hmac-sha256; secret "{secret}"; }};\n'

        for authorization, zones in self._update_authorizations:
            for zone_name, vnodes in zones.items():
                zone = zone_name + '.'
                nodes = [emulator.getServerByVirtualNodeName(name).getNode() for name in vnodes]
                if len(nodes) > 1:
                    master_ips = self.getMasterIp().get(zone, [])
                    primaries = [node for node in nodes
                                 if str(node.getInterfaces()[0].getAddress()) in master_ips]
                    if len(primaries) != 1:
                        raise ValueError(f'{zone} requires exactly one configured DNS primary')
                    nodes = primaries + [node for node in nodes if node is not primaries[0]]
                primary = nodes[0]
                primary_ip = str(primary.getInterfaces()[0].getAddress())
                publish_id, transfer_id = f'{zone_name}-publisher', f'{zone_name}-zone-transfer'
                bind_path = f'/etc/bind/keys/{zone_name}-publisher.key'
                transfer_path = f'/etc/bind/keys/{zone_name}-transfer.key'
                zone_path = f'/etc/bind/zones/{zone}'
                config_path = f'/etc/bind/update-{zone_name}.conf'
                publish_key, transfer_key = new_key(publish_id), new_key(transfer_id)
                records = self.getZone(zone).getRecords()

                # Protect the apex and name server records, including explicit TTL and IN fields.
                protected = {zone}
                for record in records:
                    fields = record.split(';', 1)[0].split()
                    upper = [field.upper() for field in fields]
                    if fields and fields[0].lower() in ('@', zone) and 'NS' in upper:
                        index = upper.index('NS')
                        if index + 1 < len(fields):
                            name = fields[index + 1].lower()
                            protected.add(name if name.endswith('.') else name + '.' + zone)
                policy = '\n'.join(f'    deny {publish_id} name {name} ANY;' for name in sorted(protected))
                policy += f'\n    grant {publish_id} subdomain {zone} NS A AAAA;'
                transfer = '    allow-transfer { none; };\n    notify no;'
                if len(nodes) > 1:
                    secondary_ips = [str(node.getInterfaces()[0].getAddress()) for node in nodes[1:]]
                    notifications = ' '.join(f'{address} key "{transfer_id}";' for address in secondary_ips)
                    transfer = (f'    allow-transfer {{ key "{transfer_id}"; }};\n'
                                '    notify explicit;\n'
                                f'    also-notify {{ {notifications} }};')
                primary.setFile(config_path, f'''include "{bind_path}";
include "{transfer_path}";
zone "{zone}" {{
    type master;
    file "{zone_path}";
    update-policy {{
{policy}
    }};
{transfer}
}};
''')
                for secondary in nodes[1:]:
                    secondary.setFile(config_path, f'''include "{transfer_path}";
zone "{zone}" {{
    type slave;
    file "{zone_path}";
    masters {{ {primary_ip} key "{transfer_id}"; }};
    allow-notify {{ key "{transfer_id}"; }};
    allow-transfer {{ none; }};
    allow-update-forwarding {{ none; }};
}};
''')
                primary.setFile(bind_path, publish_key)
                for node in nodes:
                    # Custom includes skip default zone files, so write them explicitly.
                    node.setFile(zone_path, '\n'.join(records) + '\n')
                    options = node.getFile('/etc/bind/named.conf.options')
                    options.setContent(options.get()[1].replace('allow-update { any; };', 'allow-update { none; };'))
                    node.setFile(transfer_path, transfer_key)
                    permissions = ('chown -R root:bind /etc/bind/keys && '
                                   'chmod 750 /etc/bind/keys && chmod 640 /etc/bind/keys/*.key')
                    node.addBuildCommandAtEnd(permissions)
                    node.insertStartCommand(0, permissions)
                authorization._setCredentials(zone, primary_ip, publish_key)

    def render(self, emulator):
        """Prepare hosting before each DNS server installs its own files."""
        dns_nodes = set()
        for hosting in self._hosting:
            primary = emulator.getBindingFor(hosting._primary)
            secondary = emulator.getBindingFor(hosting._secondary)
            client_ips = [str(emulator.getBindingFor(name).getInterfaces()[0].getAddress())
                          for name in hosting._api_clients]
            pair = (primary, secondary)
            if any(id(node) in dns_nodes for node in pair):
                raise ValueError('DNS hosting pairs must not overlap')
            dns_nodes.update(id(node) for node in pair)
            self._prepareHostingConfiguration(hosting, primary, secondary, client_ips)
        super().render(emulator)
        self.__renderUpdateAuthorizations(emulator)


class DnsServiceMerger(DefaultDomainNameServiceMerger):
    """Merge native DNS while preserving hosting and update authorizations."""

    def _createService(self):
        """Create the subclass for the native merge workflow."""
        return DnsService()

    def doMerge(self, objectA, objectB):
        """Keep authorization objects referenced by publishers such as Registry."""
        merged = super().doMerge(objectA, objectB)
        for service in (objectA, objectB):
            if isinstance(service, DnsService):
                merged._hosting.extend(service._hosting)
                merged._update_authorizations.extend(service._update_authorizations)
        return merged
