"""Logical server roles used by CloudDriveService."""

from __future__ import annotations

from ipaddress import IPv4Address, ip_address
from re import fullmatch
from shlex import quote
from typing import Callable, Iterable, Optional

from seedemu.core import Node, Server
from seedemu.core.enums import NetworkType

from .CloudDriveTemplates import (
    APACHE_SITE_TEMPLATE,
    NEXTCLOUD_INIT_TEMPLATE,
    NGINX_PROXY_TEMPLATE,
    OBJECT_STORAGE_CREDENTIALS_TEMPLATE,
    OBJECT_STORAGE_START_TEMPLATE,
    POSTGRES_START_TEMPLATE,
)
from .CloudDriveCredentials import (
    CloudDriveCredentialManager,
    DatabaseCredentials,
    DriveAdminCredentials,
    ObjectStorageCredentials,
)


_IDENTIFIER_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,62}"


def _validate_identifier(value: str, field: str) -> str:
    if not fullmatch(_IDENTIFIER_PATTERN, value):
        raise ValueError(f"{field} must be a PostgreSQL-compatible identifier")
    return value


def _validate_secret(value: str, field: str) -> str:
    if not value or any(character in value for character in ("\x00", "\n", "\r", "'")):
        raise ValueError(f"{field} must be non-empty and cannot contain NUL, newlines, or single quotes")
    return value


def _validate_port(value: int, field: str = "port") -> int:
    if not 1 <= int(value) <= 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return int(value)


def _validate_server_name(value: str) -> str:
    candidate = value.rstrip(".")
    if not candidate or not fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", candidate):
        raise ValueError(f'invalid server name "{value}"')
    return candidate


def service_address(node: Node) -> str:
    """Return the first local-network address, falling back to any interface."""
    for interface in node.getInterfaces():
        if interface.getNet().getType() == NetworkType.Local:
            return str(interface.getAddress())
    interfaces = node.getInterfaces()
    if not interfaces:
        raise ValueError(f"node {node.getName()} has no network interface")
    return str(interfaces[0].getAddress())


class PostgreSQLServer(Server):
    """A PostgreSQL role holding Nextcloud metadata."""

    def __init__(self, credentials: Optional[DatabaseCredentials] = None) -> None:
        super().__init__()
        credentials = credentials or CloudDriveCredentialManager().database("standalone")
        self._database_name = "nextcloud"
        self._credentials = credentials
        self._database_user = credentials.username
        self._database_password = credentials.password
        self._port = 5432
        self._node: Optional[Node] = None
        self._address: Optional[str] = None
        self._allowed_addresses: set[str] = set()
        self._network_isolation = True

    def setDatabaseName(self, value: str) -> PostgreSQLServer:
        self._database_name = _validate_identifier(value, "database name")
        return self

    def setDatabaseUser(self, value: str) -> PostgreSQLServer:
        self._database_user = _validate_identifier(value, "database user")
        self._credentials.username = self._database_user
        return self

    def setDatabasePassword(self, value: str) -> PostgreSQLServer:
        self._database_password = _validate_secret(value, "database password")
        self._credentials.password = self._database_password
        return self

    def setPort(self, value: int) -> PostgreSQLServer:
        self._port = _validate_port(value)
        return self

    def enableNetworkIsolation(self, enabled: bool = True) -> PostgreSQLServer:
        """Restrict PostgreSQL TCP access to drive nodes that use this database."""
        self._network_isolation = bool(enabled)
        return self

    def configure(self, node: Node, allowed_addresses: Iterable[str]) -> None:
        self._node = node
        self._address = service_address(node)
        self._allowed_addresses = {
            str(ip_address(value)) for value in allowed_addresses
        }

    def getAddress(self) -> str:
        if self._address is None:
            raise RuntimeError("PostgreSQLServer has not been configured")
        return self._address

    def install(self, node: Node) -> None:
        if node is not self._node:
            raise RuntimeError("PostgreSQLServer installation target changed after configure")
        if self._address is None:
            raise RuntimeError("PostgreSQLServer has not been configured")
        rules = "\n".join(
            f"host    {self._database_name}    {self._database_user}    {address}/32    scram-sha-256"
            for address in sorted(self._allowed_addresses)
        )
        listen_addresses = "*"
        network_isolation_commands = ""
        if self._network_isolation:
            database_address = ip_address(self._address)
            if not isinstance(database_address, IPv4Address):
                raise ValueError("PostgreSQL network isolation currently requires an IPv4 database address")
            listen_addresses = f"127.0.0.1,{database_address}"
            chain = f"SEEDVISTA_PG_{self._port}"
            firewall_rules = [
                f'PG_FIREWALL_CHAIN="{chain}"',
                'iptables -N "$PG_FIREWALL_CHAIN" 2>/dev/null || true',
                'iptables -F "$PG_FIREWALL_CHAIN"',
                f'iptables -A "$PG_FIREWALL_CHAIN" -p tcp -s 127.0.0.1/32 --dport {self._port} -j ACCEPT',
            ]
            firewall_rules.extend(
                f'iptables -A "$PG_FIREWALL_CHAIN" -p tcp -s {address}/32 --dport {self._port} -j ACCEPT'
                for address in sorted(self._allowed_addresses)
            )
            firewall_rules.extend(
                [
                    f'iptables -A "$PG_FIREWALL_CHAIN" -p tcp --dport {self._port} -j REJECT --reject-with tcp-reset',
                    f'iptables -C INPUT -p tcp --dport {self._port} -j "$PG_FIREWALL_CHAIN" 2>/dev/null || '
                    f'iptables -I INPUT 1 -p tcp --dport {self._port} -j "$PG_FIREWALL_CHAIN"',
                ]
            )
            network_isolation_commands = "\n".join(firewall_rules)
        marker = f"seedvista cloud drive {self._database_name}"
        script = POSTGRES_START_TEMPLATE.format(
            marker=marker,
            access_rules=rules,
            listen_addresses=listen_addresses,
            network_isolation_commands=network_isolation_commands,
            db_user=self._database_user,
            db_password=self._database_password,
            db_name=self._database_name,
        )
        node.addSoftware("postgresql iptables")
        node.setFile("/opt/seedvista/cloud-drive/postgresql-start", script)
        node.appendStartCommand(
            "chmod +x /opt/seedvista/cloud-drive/postgresql-start && "
            "/opt/seedvista/cloud-drive/postgresql-start"
        )
        node.appendClassName("CloudDrivePostgreSQL")


class ObjectStorageServer(Server):
    """An S3-compatible object-storage role, implemented with S3rver."""

    def __init__(self, credentials: Optional[ObjectStorageCredentials] = None) -> None:
        super().__init__()
        credentials = credentials or CloudDriveCredentialManager().objectStorage("standalone")
        self._version = "3.7.1"
        self._port = 9000
        self._bucket = "nextcloud"
        self._credentials = credentials
        self._access_key = credentials.access_key
        self._secret_key = credentials.secret_key
        self._region = "us-east-1"
        self._path_style = True
        self._use_ssl = False
        self._data_directory = "/var/lib/seedvista-s3"
        self._node: Optional[Node] = None
        self._address: Optional[str] = None
        self._allowed_addresses: set[str] = set()
        self._network_isolation = True

    def setVersion(self, value: str) -> ObjectStorageServer:
        if not fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
            raise ValueError("S3rver version must be numeric")
        self._version = value
        return self

    def setPort(self, value: int) -> ObjectStorageServer:
        self._port = _validate_port(value)
        return self

    def setBucket(self, value: str) -> ObjectStorageServer:
        if not fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", value):
            raise ValueError("bucket must be an S3-compatible DNS name")
        self._bucket = value
        return self

    def setCredentials(self, access_key: str, secret_key: str) -> ObjectStorageServer:
        self._access_key = _validate_secret(access_key, "access key")
        self._secret_key = _validate_secret(secret_key, "secret key")
        self._credentials.access_key = self._access_key
        self._credentials.secret_key = self._secret_key
        return self

    def setRegion(self, value: str) -> ObjectStorageServer:
        self._region = _validate_secret(value, "region")
        return self

    def enableNetworkIsolation(self, enabled: bool = True) -> ObjectStorageServer:
        """Restrict S3 TCP access to drive nodes that use this object store."""
        self._network_isolation = bool(enabled)
        return self

    def configure(self, node: Node, allowed_addresses: Iterable[str]) -> None:
        self._node = node
        self._address = service_address(node)
        self._allowed_addresses = {
            str(ip_address(value)) for value in allowed_addresses
        }

    def getAddress(self) -> str:
        if self._address is None:
            raise RuntimeError("ObjectStorageServer has not been configured")
        return self._address

    def install(self, node: Node) -> None:
        if node is not self._node:
            raise RuntimeError("ObjectStorageServer installation target changed after configure")
        if self._address is None:
            raise RuntimeError("ObjectStorageServer has not been configured")
        listen_address = "0.0.0.0"
        network_isolation_commands = ""
        if self._network_isolation:
            object_address = ip_address(self._address)
            if not isinstance(object_address, IPv4Address):
                raise ValueError("object-storage network isolation currently requires an IPv4 address")
            listen_address = str(object_address)
            chain = f"SEEDVISTA_S3_{self._port}"
            firewall_rules = [
                f'S3_FIREWALL_CHAIN="{chain}"',
                'iptables -N "$S3_FIREWALL_CHAIN" 2>/dev/null || true',
                'iptables -F "$S3_FIREWALL_CHAIN"',
            ]
            firewall_rules.extend(
                f'iptables -A "$S3_FIREWALL_CHAIN" -p tcp -s {address}/32 '
                f'-d {object_address}/32 --dport {self._port} -j ACCEPT'
                for address in sorted(self._allowed_addresses)
            )
            firewall_rules.extend(
                [
                    f'iptables -A "$S3_FIREWALL_CHAIN" -p tcp -d {object_address}/32 '
                    f'--dport {self._port} -j REJECT --reject-with tcp-reset',
                    f'iptables -C INPUT -p tcp -d {object_address}/32 --dport {self._port} '
                    f'-j "$S3_FIREWALL_CHAIN" 2>/dev/null || '
                    f'iptables -I INPUT 1 -p tcp -d {object_address}/32 --dport {self._port} '
                    f'-j "$S3_FIREWALL_CHAIN"',
                ]
            )
            network_isolation_commands = "\n".join(firewall_rules)
        script = OBJECT_STORAGE_START_TEMPLATE.format(
            data_directory=quote(self._data_directory),
            listen_address=quote(listen_address),
            port=self._port,
            bucket=quote(self._bucket),
            access_key=quote(self._access_key),
            secret_key=quote(self._secret_key),
            network_isolation_commands=network_isolation_commands,
        )
        node.addSoftware("nodejs npm iptables")
        node.addBuildCommand(f"npm install --global s3rver@{self._version}")
        node.setFile(
            "/opt/seedvista/cloud-drive/s3-credentials.js",
            OBJECT_STORAGE_CREDENTIALS_TEMPLATE,
        )
        node.setFile("/opt/seedvista/cloud-drive/object-storage-start", script)
        node.appendStartCommand(
            "chmod +x /opt/seedvista/cloud-drive/object-storage-start && "
            "/opt/seedvista/cloud-drive/object-storage-start",
            fork=True,
        )
        node.appendClassName("CloudDriveObjectStorage")


class NextcloudServer(Server):
    """A Nextcloud application role using PostgreSQL and S3-compatible storage."""

    def __init__(self, credentials: Optional[DriveAdminCredentials] = None) -> None:
        super().__init__()
        credentials = credentials or CloudDriveCredentialManager().driveAdmin("standalone")
        self._version = "30.0.12"
        self._archive_sha256 = "9e19b25f42273d4361218426b4762a766bee408cfa6aa8219f8c27f72095a7a8"
        self._port = 80
        self._server_name = ["_"]
        self._database_vnode: Optional[str] = None
        self._object_storage_vnode: Optional[str] = None
        self._credentials = credentials
        self._admin_user = credentials.username
        self._admin_password = credentials.password
        self._https_enabled = False
        self._https_callback: Optional[Callable[[Node, NextcloudServer], None]] = None
        self._node: Optional[Node] = None
        self._address: Optional[str] = None
        self._database: Optional[PostgreSQLServer] = None
        self._object_storage: Optional[ObjectStorageServer] = None

    def setVersion(self, version: str, sha256: str) -> NextcloudServer:
        if not fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
            raise ValueError("Nextcloud version must contain three numeric components")
        if not fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Nextcloud archive SHA-256 must contain 64 lowercase hex digits")
        self._version = version
        self._archive_sha256 = sha256
        return self

    def setPort(self, value: int) -> NextcloudServer:
        self._port = _validate_port(value)
        return self

    def setServerNames(self, values: list[str]) -> NextcloudServer:
        if not values:
            raise ValueError("at least one server name is required")
        self._server_name = [_validate_server_name(value) for value in values]
        return self

    def setDatabase(self, vnode: str) -> NextcloudServer:
        if not vnode:
            raise ValueError("database vnode cannot be empty")
        self._database_vnode = vnode
        return self

    def setObjectStorage(self, vnode: str) -> NextcloudServer:
        if not vnode:
            raise ValueError("object-storage vnode cannot be empty")
        self._object_storage_vnode = vnode
        return self

    def setAdminCredentials(self, username: str, password: str) -> NextcloudServer:
        self._admin_user = _validate_identifier(username, "admin username")
        self._admin_password = _validate_secret(password, "admin password")
        self._credentials.username = self._admin_user
        self._credentials.password = self._admin_password
        return self

    def setCAServer(self, ca_server) -> NextcloudServer:
        self._https_callback = ca_server.enableHTTPSFunc
        return self

    def enableHTTPS(self, enabled: bool = True) -> NextcloudServer:
        self._https_enabled = enabled
        return self

    def getDatabaseVnode(self) -> str:
        if self._database_vnode is None:
            raise ValueError("NextcloudServer requires setDatabase()")
        return self._database_vnode

    def getObjectStorageVnode(self) -> str:
        if self._object_storage_vnode is None:
            raise ValueError("NextcloudServer requires setObjectStorage()")
        return self._object_storage_vnode

    def configure(
        self,
        node: Node,
        database: PostgreSQLServer,
        object_storage: ObjectStorageServer,
    ) -> None:
        self._node = node
        self._address = service_address(node)
        self._database = database
        self._object_storage = object_storage
        if self._https_enabled and self._https_callback is None:
            raise ValueError("HTTPS requires setCAServer() before enableHTTPS()")
        if self._https_enabled and self._server_name == ["_"]:
            raise ValueError("HTTPS requires a concrete server name")

    def getAddress(self) -> str:
        if self._address is None:
            raise RuntimeError("NextcloudServer has not been configured")
        return self._address

    def install(self, node: Node) -> None:
        if node is not self._node or self._database is None or self._object_storage is None:
            raise RuntimeError("NextcloudServer installation target changed after configure")

        archive_url = (
            "https://download.nextcloud.com/server/releases/"
            f"nextcloud-{self._version}.tar.bz2"
        )
        apache_port = 8080 if self._https_enabled else self._port
        concrete_names = [name for name in self._server_name if name != "_"]
        trusted_domains = ["localhost", "127.0.0.1", node.getName(), self.getAddress()]
        for name in concrete_names:
            if name not in trusted_domains:
                trusted_domains.append(name)
        trusted_commands = "\n".join(
            "php /var/www/html/occ config:system:set trusted_domains "
            f"{index} --value={quote(domain)}"
            for index, domain in enumerate(trusted_domains)
        )
        https_commands = ""
        if self._https_enabled:
            https_commands = "\n".join(
                [
                    "php /var/www/html/occ config:system:set trusted_proxies 0 --value=127.0.0.1",
                    "php /var/www/html/occ config:system:set overwriteprotocol --value=https",
                ]
            )

        init_script = NEXTCLOUD_INIT_TEMPLATE.format(
            db_password_q=quote(self._database._database_password),
            db_host_q=quote(self._database.getAddress()),
            db_port=self._database._port,
            db_user_q=quote(self._database._database_user),
            db_name_q=quote(self._database._database_name),
            object_host_q=quote(self._object_storage.getAddress()),
            object_port=self._object_storage._port,
            admin_user_q=quote(self._admin_user),
            admin_password_q=quote(self._admin_password),
            trusted_domain_commands=trusted_commands,
            bucket_q=quote(self._object_storage._bucket),
            access_key_q=quote(self._object_storage._access_key),
            secret_key_q=quote(self._object_storage._secret_key),
            region_q=quote(self._object_storage._region),
            path_style=str(self._object_storage._path_style).lower(),
            object_ssl=str(self._object_storage._use_ssl).lower(),
            https_commands=https_commands,
        )

        packages = (
            "apache2 libapache2-mod-php php-cli php-apcu php-bz2 php-curl php-gd "
            "php-gmp php-intl php-mbstring php-pgsql php-xml php-zip "
            "postgresql-client bzip2 ca-certificates curl netcat-openbsd"
        )
        if self._https_enabled:
            packages += " nginx-light"
        node.addSoftware(packages)
        node.addBuildCommand(
            "curl --fail --location --silent --show-error "
            "--retry 30 --retry-all-errors --retry-delay 2 --continue-at - "
            f"{quote(archive_url)} -o /tmp/nextcloud.tar.bz2"
        )
        node.addBuildCommand(
            f"echo '{self._archive_sha256}  /tmp/nextcloud.tar.bz2' | sha256sum --check -"
        )
        node.addBuildCommand(
            "rm -rf /var/www/html && tar -xjf /tmp/nextcloud.tar.bz2 -C /var/www "
            "&& mv /var/www/nextcloud /var/www/html && rm -f /tmp/nextcloud.tar.bz2"
        )
        node.addBuildCommand("a2enmod rewrite headers env dir mime setenvif")
        node.addBuildCommand("chown -R www-data:www-data /var/www/html")

        primary_name = concrete_names[0] if concrete_names else "_"
        # Apache requires at least one argument after ServerAlias. Reusing the
        # primary name is harmless and keeps the generated vhost valid when a
        # deployment has exactly one public name.
        aliases = " ".join(concrete_names[1:]) or primary_name
        node.setFile(
            "/etc/apache2/sites-available/000-default.conf",
            APACHE_SITE_TEMPLATE.format(
                port=apache_port,
                primary_server_name=primary_name,
                server_aliases=aliases,
            ),
        )
        if self._https_enabled:
            node.setFile("/etc/apache2/ports.conf", f"Listen {apache_port}\n")
            node.setFile(
                "/etc/nginx/sites-available/default",
                NGINX_PROXY_TEMPLATE.format(
                    server_names=" ".join(concrete_names),
                    apache_port=apache_port,
                ),
            )

        node.setFile("/opt/seedvista/cloud-drive/nextcloud-init", init_script)
        node.appendStartCommand("apachectl -D FOREGROUND", fork=True)
        if self._https_enabled:
            node.appendStartCommand("service nginx start")
        node.appendStartCommand(
            "chmod +x /opt/seedvista/cloud-drive/nextcloud-init && "
            "/opt/seedvista/cloud-drive/nextcloud-init"
        )
        if self._https_enabled:
            self._https_callback(node, self)
        node.appendClassName("CloudDriveNextcloud")
        node.setDisplayName("Cloud Drive")
        for name in concrete_names:
            node.addHostName(name)
