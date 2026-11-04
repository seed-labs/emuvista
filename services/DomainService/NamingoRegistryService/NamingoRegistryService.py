"""Define the Registry layer and server, and install each instance on its bound existing host during rendering."""
from seedemu.core import Node, Server, Service

import json
import re
import shlex
from pathlib import Path


NamingoRegistryFileTemplates = {
    name: (Path(__file__).resolve().parent / 'templates' / name).read_text(encoding='utf-8')
    for name in (
        'configure-automation.php',
        'configure-control-panel.php',
        'configure-domain-availability.php',
        'configure-epp.php',
        'create-epp-registrar.php',
        'create-nameserver-hosts.php',
        'init-database.sql',
        'init-tlds.php',
        'initialize-nameserver-hosts.sh',
        'nginx-registry.conf',
        'publish-dns-delegations-loop.sh',
        'publish-dns-delegations.php',
        'start-database.sh',
        'start-web.sh',
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

def php_string(value):
    """Escape the contents of a PHP single-quoted string.

    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def sql_string(value):
    """Escape a MariaDB string with its default backslash escaping mode.

    """
    return value.replace("\\", "\\\\").replace("'", "''")


def normalize_tlds(tlds):
    """Normalize TLD spelling and remove duplicates while preserving order."""
    return tuple(dict.fromkeys(value.removeprefix('.').lower() for value in tlds))


class NamingoRegistryServer(Server):
    """Registry, MariaDB, Redis, web panel, EPP, DAS and lifecycle cron.

    Defaults manage the simulated .com/.net TLDs.
    """

    def __init__(self):
        """Initialize an instance with simulation defaults."""
        super().__init__()
        self._forwarded_port = 18081
        self._dns_authorization = None
        self._publication_tlds = ()
        self._publication_interval = 30
        self._registrars = {}
        self._nameservers = []
        self._tlds = ('com', 'net')
        self._epp_port = 700
        self._db_password = 'registry-database-password'
        self._admin_email = 'admin@example.com'
        self._admin_password = '123456'
        self.appendClassName('NamingoRegistryService')
        self.setDisplayName('Namingo COM Registry')

    def setPortForwarding(self, host_port):
        """Set the host Web port; None disables forwarding."""
        self._forwarded_port = host_port
        return self

    def setAdminAccount(self, email: str, password: str):
        """Set initial administrator credentials and return this instance."""
        self._admin_email = email
        self._admin_password = password
        return self

    def setDatabasePassword(self, password: str):
        """Set the initial database account password and return this instance."""
        self._db_password = password
        return self

    def setTlds(self, tlds):
        """Set initial TLDs and return this instance; existing databases are not migrated."""
        self._tlds = normalize_tlds(tlds)
        return self

    def getTlds(self):
        """Return a copy of the TLD list without leading dots."""
        return list(self._tlds)

    def setEppPort(self, port: int):
        """Set the EPP listening port, returning this instance."""
        self._epp_port = port
        return self

    def setDnsAuthorization(self, authorization):
        """Accept DNS authorization and validate Registry-owned TLDs."""
        if {zone.rstrip('.') for zone in authorization.getZones()} - set(self._tlds):
            raise ValueError('DNS authorization zones must be managed by Registry')
        self._dns_authorization = authorization
        return self

    def _validateDnsAuthorization(self):
        """Check that authorized zones still belong to this Registry."""
        zones = self._dns_authorization.getZones()
        if {zone.rstrip('.') for zone in zones} - set(self._tlds):
            raise ValueError('Authorized TLDs must remain managed by Registry')

    def enableDnsPublication(self, tlds, interval=30):
        """Enable periodic delegation publication for TLDs with DNS authorization configured."""
        values = normalize_tlds(tlds)
        if set(values) - set(self._tlds):
            raise ValueError('Publication TLDs must be managed by Registry')
        self._publication_tlds = values
        self._publication_interval = interval
        return self

    def getEppPort(self):
        """Return the EPP port for dependent services."""
        return self._epp_port

    def addNameServers(self, hosting, epp_username):
        """Register a DNS pair's host records under the given EPP username."""
        self._nameservers.append((hosting, epp_username))
        return self

    def addEppRegistrar(self, username, password, prefix, source_ip, reserved_domains=()):
        """Initialize an account, whitelist, and reserved domains before EPP starts."""
        if username in self._registrars or any(item['prefix'] == prefix for item in self._registrars.values()):
            raise ValueError('Duplicate EPP registrar username or prefix')
        domains = []
        for name in reserved_domains:
            name = name.lower()
            if name.rsplit('.', 1)[-1] not in self._tlds:
                raise ValueError('Reserved domains must belong to a managed TLD')
            if name not in domains:
                domains.append(name)
        self._registrars[username] = dict(password=password, prefix=prefix, source_ip=source_ip, domains=domains)
        return self

    def install(self, node: Node):
        """Configure the bound host in database, cache, and application dependency order."""
        if self._dns_authorization is not None:
            self._validateDnsAuthorization()
            self._installDnsAuthorization(node)
        if self._publication_tlds:
            files = {file.get()[0] for file in node.getFiles()}
            for tld in self._publication_tlds:
                if f'/opt/registry/dns-publication-{tld}.json' not in files:
                    raise ValueError(f'Configure Registry DNS authorization for {tld} before enabling publication')
        self._installSoftware(node)
        self._installDatabase(node)
        for username, account in self._registrars.items():
            self._installEppRegistrar(node, username, **account)
        self._installCache(node)
        self._installWeb(node)
        if self._forwarded_port is not None:
            node.addPortForwarding(self._forwarded_port, 8080)
        self._installAdmin(node)
        self._installEpp(node)
        self._installDas(node)
        self._installLifecycle(node)
        for hosting, epp_username in self._nameservers:
            settings = hosting.getSettings()
            if epp_username not in self._registrars or settings['domain'] not in self._registrars[epp_username]['domains']:
                raise ValueError('Nameserver parent domain must be reserved by the selected EPP registrar')
            self._installNameServers(node, settings, epp_username)
        if self._publication_tlds:
            if set(self._publication_tlds) - set(self._tlds):
                raise ValueError('Publication TLDs must remain managed by Registry')
            self._installDnsPublication(node)

    def _installSoftware(self, node):
        """Install Registry and its local dependencies."""
        node.addSoftware('ca-certificates software-properties-common git unzip openssl cron '
                         'mariadb-server mariadb-client redis-server nginx')
        node.addBuildCommand('add-apt-repository --no-update -y ppa:ondrej/php')
        node.addBuildCommand(apt_install('composer'))
        node.addBuildCommand(apt_install(
            'php8.5-cli php8.5-fpm php8.5-mysql php8.5-curl php8.5-bcmath php8.5-gmp '
            'php8.5-intl php8.5-mbstring php8.5-xml php8.5-zip php8.5-swoole php8.5-imap '
            'php8.5-gd php8.5-bz2 php8.5-soap php8.5-redis'))
        node.addBuildCommand(
            "git clone https://github.com/getnamingo/registry.git /opt/registry "
            f"&& cd /opt/registry && git checkout a783a3c37a5614827f7141f07028e9a6a2d4f5cb"
        )
        for component in ("cp", "epp", "das", "automation"):
            node.addBuildCommand(composer_install(f'/opt/registry/{component}'))

    def _installDatabase(self, node):
        """Start MariaDB, import the Registry schema, and initialize the selected TLDs."""
        tld_values = ", ".join("'." + name + "'" for name in self._tlds)
        node.setFile("/opt/registry/init-database.sql", NamingoRegistryFileTemplates['init-database.sql'].replace('__DB_PASSWORD__', sql_string(self._db_password)))
        values = {'__DB_PASSWORD__': php_string(self._db_password), '__TLDS__': tld_values}
        script = re.sub(r'__[A-Z_]+__', lambda match: values[match.group()],
                        NamingoRegistryFileTemplates['init-tlds.php'])
        node.setFile("/opt/registry/init-tlds.php", script)
        node.setFile("/opt/registry/start-database.sh", NamingoRegistryFileTemplates['start-database.sh'])
        node.appendStartCommand("bash /opt/registry/start-database.sh")

    def _installCache(self, node):
        """Start local Redis for EPP domain pricing queries."""
        node.setFile("/opt/registry/cache.sh", (
            '#!/bin/bash\n'
            '\n'
            'set -e\n'
            'service redis-server start\n'
            'redis-cli ping | grep -qx PONG\n'
        ))
        node.appendStartCommand("bash /opt/registry/cache.sh")

    def _installAdmin(self, node):
        """Create the administrator account for the Registry web panel."""
        values = {'__ADMIN_EMAIL__': php_string(self._admin_email), '__ADMIN_PASSWORD__': php_string(self._admin_password)}
        node.setFile("/opt/registry/create-admin.php", re.sub(r'__[A-Z_]+__', lambda match: values[match.group()], (
            '<?php\n'
            "putenv('PANEL_EMAIL=__ADMIN_EMAIL__');\n"
            "putenv('PANEL_PASSWORD=__ADMIN_PASSWORD__');\n"
            "require '/opt/registry/cp/bin/create_admin_user.php';\n"
        )))
        node.setFile("/opt/registry/admin.sh", (
            '#!/bin/bash\n'
            'php8.5 /opt/registry/create-admin.php\n'
        ))
        node.appendStartCommand("bash /opt/registry/admin.sh")

    def _installWeb(self, node):
        """Configure and start the Namingo Registry web panel."""
        node.setFile("/opt/registry/configure-control-panel.php", NamingoRegistryFileTemplates['configure-control-panel.php'].replace('__DB_PASSWORD__', php_string(self._db_password)))
        node.setFile("/etc/nginx/conf.d/nginx-registry.conf", NamingoRegistryFileTemplates['nginx-registry.conf'])
        node.setFile("/etc/php/8.5/fpm/conf.d/99-registry.ini",
                     'session.cookie_secure=0\n'
                     'session.cookie_httponly=1\n')
        node.addBuildCommandAtEnd(
            "mkdir -p /opt/registry/cp/cache /opt/registry/cp/logs "
            "&& chown -R www-data:www-data /opt/registry/cp/cache /opt/registry/cp/logs"
        )
        node.setFile("/opt/registry/start-web.sh", NamingoRegistryFileTemplates['start-web.sh'])
        node.appendStartCommand("bash /opt/registry/start-web.sh")

    def _installEpp(self, node):
        """Configure EPP and its TLS server certificate, then start the service.

        This certificate is independent of the web panel certificate.
        The self-signed certificate is for simulation only. Certificate authentication
        requires a trusted CA and server certificate verification by the registrar.
        Identifying registrars by client certificate also requires mutual TLS in Registry.
        """
        values = {'__DB_PASSWORD__': php_string(self._db_password), '__EPP_PORT__': str(self._epp_port)}
        node.setFile("/opt/registry/configure-epp.php", re.sub(r'__[A-Z_]+__', lambda match: values[match.group()], NamingoRegistryFileTemplates['configure-epp.php']))
        node.addBuildCommandAtEnd(
            "openssl req -x509 -newkey rsa:2048 -nodes -days 3650 "
            "-subj /CN=namingo-registry "
            "-keyout /opt/registry/epp/epp.key -out /opt/registry/epp/epp.crt "
            "&& chmod 600 /opt/registry/epp/epp.key"
        )
        node.setFile("/opt/registry/epp.sh", (
            '#!/bin/bash\n'
            'php8.5 /opt/registry/configure-epp.php\n'
            '\n'
            'cd /opt/registry/epp\n'
            'php8.5 start_epp.php >> /var/log/namingo/epp-start.log 2>&1 &\n'
        ))
        node.appendStartCommand("bash /opt/registry/epp.sh")

    def _installDas(self, node):
        """Configure and start the IPv4 domain availability service."""
        node.setFile("/opt/registry/configure-domain-availability.php", NamingoRegistryFileTemplates['configure-domain-availability.php'].replace('__DB_PASSWORD__', php_string(self._db_password)))
        node.setFile("/opt/registry/das.sh", (
            '#!/bin/bash\n'
            'php8.5 /opt/registry/configure-domain-availability.php\n'
            '\n'
            'cd /opt/registry/das\n'
            'php8.5 start_das.php >> /var/log/namingo/das-start.log 2>&1 &\n'
        ))
        node.appendStartCommand("bash /opt/registry/das.sh")

    def _installLifecycle(self, node):
        """Configure automation and run domain lifecycle maintenance every five minutes via cron.

        The separate loop configured by configure_dns_publication handles DNS delegation publication.
        """
        node.setFile("/opt/registry/configure-automation.php", NamingoRegistryFileTemplates['configure-automation.php'].replace('__DB_PASSWORD__', php_string(self._db_password)))
        node.setFile("/etc/cron.d/namingo-lifecycle",
                     '*/5 * * * * root cd /opt/registry/automation '
                     '&& php8.5 domain-lifecycle-manager.php '
                     '>> /var/log/namingo/lifecycle-start.log 2>&1\n')
        node.setFile("/opt/registry/lifecycle.sh", (
            '#!/bin/bash\n'
            'php8.5 /opt/registry/configure-automation.php\n'
            'service cron start\n'
        ))
        node.appendStartCommand("bash /opt/registry/lifecycle.sh")

    def _installEppRegistrar(self, node, username, password, prefix, source_ip, domains):
        """Generate account initialization to run before EPP reads its whitelist."""
        values = {
            '__REGISTRY_DB_PASSWORD__': self._db_password, '__EPP_USERNAME__': username,
            '__EPP_PASSWORD__': password, '__EPP_PREFIX__': prefix,
            '__EPP_SOURCE_IP__': source_ip, '__RESERVED_DOMAINS__': json.dumps(domains),
        }
        # Replace once to avoid expanding markers inside credentials.
        script = re.sub(r'__[A-Z_]+__', lambda match: php_string(values[match.group()]),
                        NamingoRegistryFileTemplates['create-epp-registrar.php'])
        path = f'/opt/registry/create-registrar-{username}.php'
        node.setFile(path, script)
        node.addBuildCommandAtEnd(f'chmod 600 {path}')
        node.appendStartCommand(f'chmod 600 {path} && php8.5 {path}')

    def _installDnsAuthorization(self, node):
        """Resolve DNS credentials, write publication files, and restrict key permissions."""
        # Resolve all credentials before writing files.
        credentials = {zone.rstrip('.'): self._dns_authorization.getCredentials(zone)
                       for zone in self._dns_authorization.getZones()}
        publications = {}
        for tld, (address, key) in credentials.items():
            path = f'/opt/registry/dns-keys/{tld}-publisher.key'
            node.setFile(path, key)
            entry = {'zone': tld + '.', 'server': address, 'key_file': path}
            publications[tld + '.'] = entry
            node.setFile(f'/opt/registry/dns-publication-{tld}.json', json.dumps(entry) + '\n')
            permissions = f'chmod 700 /opt/registry/dns-keys && chmod 600 {path}'
            node.addBuildCommandAtEnd(permissions)
            node.insertStartCommand(0, permissions)
        if publications:
            node.setFile('/opt/registry/dns-publications.json', json.dumps(publications) + '\n')

    def _installDnsPublication(self, node):
        """Install publication and its loop without copying database credentials into scripts."""
        node.addSoftware('bind9-dnsutils')
        node.setFile('/opt/registry/publish-dns-delegations.php', NamingoRegistryFileTemplates['publish-dns-delegations.php'])
        commands = '\n'.join(
            f'    timeout 25 php8.5 /opt/registry/publish-dns-delegations.php {tld}'
            ' >> /var/log/namingo/dns-publication.log 2>&1'
            for tld in self._publication_tlds)
        values = {'__COMMANDS__': commands, '__INTERVAL__': str(self._publication_interval)}
        node.setFile('/opt/registry/publish-dns-delegations-loop.sh',
                     re.sub(r'__[A-Z_]+__', lambda match: values[match.group()], NamingoRegistryFileTemplates['publish-dns-delegations-loop.sh']))
        node.appendStartCommand('bash /opt/registry/publish-dns-delegations-loop.sh &')

    def _installNameServers(self, node, settings, epp_username):
        """Initialize nameserver host records in this Registry after local setup."""
        directory = '/opt/dns-hosting/hosts-' + settings['domain']
        node.setFile(directory + '.php', NamingoRegistryFileTemplates['create-nameserver-hosts.php'])
        environment = {
            'REGISTRY_NAMESERVER_HOSTS': json.dumps([[settings['ns1'], settings['primary']],
                                     [settings['ns2'], settings['secondary']]]),
            'REGISTRY_EPP_USERNAME': epp_username,
            'REGISTRY_PARENT_DOMAIN': settings['domain'], 'REGISTRY_CHECK_ONLY': '0',
        }
        exports = ''.join('export ' + key + '=' + shlex.quote(value) + '\n'
                          for key, value in environment.items())
        marker = '/run/registry-hosts-' + settings['domain']
        values = {'__MARKER__': marker, '__EXPORTS__': exports, '__DIRECTORY__': directory}
        node.setFile(directory + '.sh', re.sub(r'__[A-Z_]+__', lambda match: values[match.group()], NamingoRegistryFileTemplates['initialize-nameserver-hosts.sh']))
        node.appendStartCommand('sh ' + directory + '.sh > /var/log/registry-hosts-'
                                    + settings['domain'] + '.log 2>&1')

    def print(self, indent: int):
        """Return the server description at the requested indentation."""
        return ' ' * indent + 'Namingo Registry server\n'


class NamingoRegistryService(Service):
    """Service layer that installs Registry instances on existing hosts."""

    def __init__(self):
        """Declare base network and routing dependencies."""
        super().__init__()
        self.addDependency('Base', False, False)
        self.addDependency('Routing', False, False)
        self.addDependency('DomainNameService', False, True)

    def _createServer(self):
        """Create a server instance for virtual node binding."""
        return NamingoRegistryServer()

    def getName(self):
        """Return the service layer registration name."""
        return 'NamingoRegistryService'

    def print(self, indent: int):
        """Return the layer description at the requested indentation."""
        return ' ' * indent + 'NamingoRegistryServiceLayer\n'
