"""Deploy Stock Service and its QuantReplay venue as a SEED ContainerBundle."""

from __future__ import annotations

import ipaddress
import base64
import json
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from seedemu.containerBundle import ContainerBundle
from seedemu.containerBundle.ContainerBundle import PreparedContainer


ROLES = ("api", "stock-db", "quantreplay", "quantreplay-db", "quantreplay-liquibase")
DEFAULT_IMAGES = {"api": "emuvista/stock-api:0.1.0", "stock-db": "postgres:16-alpine"}
QUANTREPLAY_ROLES = ("quantreplay", "quantreplay-db", "quantreplay-liquibase")


class RoutedContainer(PreparedContainer):
    """Wrap a Linux image with iproute2 while preserving its image defaults."""

    def _generateDockerfile(self):
        image = self._service.pop("image")
        return "\n".join(
            [
                f"FROM {image}",
                "USER root",
                "RUN if ! command -v ip >/dev/null 2>&1; then "
                "if command -v apk >/dev/null 2>&1; then apk add --no-cache iproute2; "
                "else apt-get update && apt-get install -y --no-install-recommends iproute2 "
                "&& rm -rf /var/lib/apt/lists/*; fi; fi",
            ]
        ) + "\n"


class StockBundle(ContainerBundle):
    """Run Stock API, its ledger database, and a single QuantReplay venue."""

    def __init__(self, emulator=None, images=None, name="stock"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", name):
            raise ValueError("bundle name requires 1 to 32 lowercase letters, digits or hyphens")
        super().__init__(emulator=emulator)
        self._name = name
        self._images = dict(DEFAULT_IMAGES)
        for role, image in (images or {}).items():
            self.setImage(role, image)
        self._state_path: Path | None = None
        self._host_port: int | None = None
        self._default_network = None
        self._addresses: dict[str, str] = {}
        self._email = {
            "host": "", "port": 587, "user": "", "password": "",
            "sender": "stock@seed.example", "starttls": True,
        }
        self._api_admin_token: str | None = None
        self._configured = False
        self._hostname: str | None = None
        self._tls_material: tuple[Path, Path] | None = None
        self._banks: dict[str, tuple[object, str, str]] = {}
        self._bank_providers: dict[str, dict] = {}
        self._required_internal_address_count = len(ROLES)
        for role in ROLES:
            container = RoutedContainer(name=f"{name}-{role}", emulator=self._emulator)
            # Stock API and PostgreSQL use the bundle's mounted routing script.
            # The QuantReplay images keep their upstream entrypoints.
            container.setStartScriptName("")
            self._containers[role] = container

    def setImage(self, role: str, image: str) -> "StockBundle":
        if role not in ROLES:
            raise ValueError(f"unknown stock image role: {role}")
        if not isinstance(image, str) or not image or any(char.isspace() for char in image):
            raise ValueError("image reference must be nonempty and contain no whitespace")
        self._images[role] = image
        return self

    def setSavePath(self, path: str | Path) -> "StockBundle":
        self._state_path = Path(path).expanduser().resolve()
        return self

    def setHostname(self, hostname: str) -> "StockBundle":
        if not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", hostname):
            raise ValueError("invalid Stock Service hostname")
        self._hostname = hostname.lower()
        return self

    def connectBank(self, bank, alias: str | None = None) -> "StockBundle":
        if self._configured:
            raise RuntimeError("connect banks before configuring StockBundle")
        alias = alias or getattr(bank, "_name", None)
        if not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", alias):
            raise ValueError("bank alias requires 1 to 32 lowercase letters, digits or hyphens")
        if alias in self._banks:
            raise ValueError("bank alias is already connected")
        client_id = self._name + "-stock-" + alias
        if len(client_id) > 80:
            raise ValueError("generated Bank API client ID is too long")
        callback = f"http://{self._address_for_tools()}:8447/bank-callback"
        bank.registerAPIClient(client_id, [callback])
        self._banks[alias] = (bank, client_id, callback)
        return self

    def getURL(self) -> str:
        address = self._hostname or self._address_for_tools()
        return f"https://{address}:8447"

    def _address_for_tools(self) -> str:
        if "api" in self._addresses:
            return self._addresses["api"]
        api_networks = self.getContainer("api")._internal_networks
        if api_networks:
            return api_networks[0]["ip_address"]
        if self._default_network and self._default_network["ip_addresses"]:
            return self._default_network["ip_addresses"][0]
        for network in self.getInternalNetworks():
            if network["ip_addresses"]:
                return network["ip_addresses"][0]
        raise RuntimeError("configure a Stock Service internal network before exporting its Agent tools")

    def _ensure_tls_material(self) -> tuple[Path, Path]:
        if self._tls_material and all(path.is_file() for path in self._tls_material):
            return self._tls_material
        if self._state_path and (self._state_path / "server.crt").is_file() and (self._state_path / "server.key").is_file():
            self._tls_material = (self._state_path / "server.crt", self._state_path / "server.key")
            return self._tls_material
        directory = Path(tempfile.mkdtemp(prefix="seedemu-stock-tls-"))
        cert_file, key_file = directory / "server.crt", directory / "server.key"
        subprocess.run(
            ["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "365",
             "-keyout", str(key_file), "-out", str(cert_file), "-subj", "/CN=SEED Stock Service",
             "-addext", "subjectAltName=DNS:localhost,DNS:stock-api,IP:127.0.0.1"],
            check=True, capture_output=True,
        )
        key_file.chmod(0o600)
        self._tls_material = (cert_file, key_file)
        return self._tls_material

    def getAgentTools(self) -> dict:
        cert_file, _ = self._ensure_tls_material()
        return {
            "name": "stock",
            "source": Path(__file__).parent / "tools",
            "configuration": {
                self._name: {
                    "url": self.getURL(),
                    "sender": self._email["sender"],
                    "certificate": cert_file.read_text(encoding="ascii"),
                }
            },
        }

    def setDefaultInternalNetwork(self, name: str, ip_addresses: list[str], default_route: str):
        self._default_network = {
            "network": name,
            "ip_addresses": list(ip_addresses),
            "default_route": str(ipaddress.IPv4Address(default_route)),
        }
        return self

    def setEmailServer(
        self,
        host: str,
        username: str = "",
        password: str = "",
        port: int = 587,
        sender: str = "stock@seed.example",
        starttls: bool = True,
    ) -> "StockBundle":
        if not host or not 1 <= port <= 65535 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", sender):
            raise ValueError("valid SMTP host, port, and sender email are required")
        self._email = {
            "host": host, "port": port, "user": username, "password": password,
            "sender": sender, "starttls": bool(starttls),
        }
        return self

    def enableHostAccess(self, port: int = 8447) -> "StockBundle":
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("host access port must be an integer between 1 and 65535")
        self._host_port = port
        return self

    def getAdminToken(self) -> str:
        if self._api_admin_token is None:
            raise RuntimeError("configure StockBundle before reading its admin token")
        return self._api_admin_token

    def getAddress(self, role: str = "api") -> str:
        if role not in self._addresses:
            raise RuntimeError("configure StockBundle before reading component addresses")
        return self._addresses[role]

    def _getDefaultRoute(self, role: str) -> str:
        return str(self.getContainer(role)._internal_networks[0]["default_route"])

    def configure(self):
        if self._configured:
            return
        super().configure()
        if self._emulator is None or not self._emulator.rendered():
            raise RuntimeError("render the emulator before configuring StockBundle")
        missing_images = [role for role in QUANTREPLAY_ROLES if role not in self._images]
        if missing_images:
            raise ValueError(
                "set pinned QuantReplay images before configuring StockBundle: "
                + ", ".join(missing_images)
            )
        networks = {
            obj.getFullName(): (scope, obj)
            for (scope, kind, _), obj in self._emulator.getRegistry().getAll().items()
            if kind == "net"
        }
        missing = [container for container in self._containers.values() if not container._internal_networks]
        if missing:
            pools = self.getInternalNetworks()
            if self._default_network:
                network = networks.get(self._default_network["network"])
                if network is None:
                    raise ValueError("StockBundle default network must be a rendered SEED network")
                asn, obj = network
                pools = [{**self._default_network, "asn": asn, "network_name": obj.getName()}]
            assigned = {
                str(attachment["ip_address"])
                for container in self._containers.values()
                for attachment in container._internal_networks
            }
            addresses = []
            for pool in pools:
                for address in pool["ip_addresses"]:
                    address = str(address)
                    if address not in assigned:
                        addresses.append((pool, address))
                        assigned.add(address)
            if len(addresses) < len(missing):
                raise ValueError(f"StockBundle requires {len(missing)} free emulated IP addresses")
            for container, (pool, address) in zip(missing, addresses):
                container.joinInternalNetwork(
                    pool["asn"], pool["network_name"], address, container.getHostname(), pool["default_route"]
                )
        self._validate_networks(networks)
        self._configure_admin_token()
        for alias, (bank, client_id, _) in self._banks.items():
            connection = bank.getOpenBankingConnection(client_id)
            self._bank_providers[alias] = {
                key: connection[key] for key in
                ("id", "name", "apiURL", "browserURL", "clientId", "clientSecret", "redirectURIs", "currencies")
            }
        self._configured = True

    def _validate_networks(self, networks) -> None:
        selected = set()
        for role, container in self._containers.items():
            if len(container._internal_networks) != 1:
                raise ValueError("each stock component requires exactly one emulated network")
            attachment = container._internal_networks[0]
            address = str(attachment["ip_address"])
            _, network = networks[attachment["full_network_name"]]
            if address in selected or not network.isIpAddressAvailable(address):
                raise ValueError(f"{role}: emulated IP address is unavailable")
            gateway = network.getDefaultRouter()
            if gateway is None or str(attachment["default_route"]) != str(gateway):
                raise ValueError(f"{role}: default route must use the emulated network router")
            selected.add(address)
            self._addresses[role] = address

    def _configure_admin_token(self) -> None:
        identity = {"name": self._name, "addresses": self._addresses}
        if self._state_path is None:
            self._api_admin_token = secrets.token_urlsafe(40)
            return
        self._state_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        credentials = self._state_path / "credentials.json"
        if credentials.exists():
            if credentials.stat().st_mode & 0o077:
                raise ValueError("saved stock credentials must have mode 0600")
            saved = json.loads(credentials.read_text(encoding="utf-8"))
            if saved.get("identity") != identity:
                raise ValueError("saved stock state uses another network layout; use a new state directory")
            self._api_admin_token = saved["admin_token"]
        else:
            unexpected = {item.name for item in self._state_path.iterdir()} - {"server.crt", "server.key"}
            if unexpected:
                raise ValueError("stock state contains data but no matching credentials.json")
            self._api_admin_token = secrets.token_urlsafe(40)
            self._write_credentials(credentials, identity, {"admin_token": self._api_admin_token})

    @staticmethod
    def _write_credentials(path: Path, identity: dict, service_secrets: dict) -> None:
        path.write_text(
            json.dumps({"identity": identity, **service_secrets}, indent=2) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _saved_or_generated_secret(self, state: Path, key: str) -> str:
        credentials = state / "credentials.json"
        saved = json.loads(credentials.read_text(encoding="utf-8")) if credentials.exists() else {}
        generated = (base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
                     if key == "stock_token_encryption_key" else secrets.token_urlsafe(32))
        value = saved.get(key) or generated
        saved[key] = value
        credentials.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        credentials.chmod(0o600)
        return value

    def install(self):
        if not self._configured:
            raise RuntimeError("configure StockBundle before installing it")

        root = Path(self._name)
        config = root / "config"
        config.mkdir(parents=True, exist_ok=True, mode=0o755)
        state = self._state_path or Path(tempfile.mkdtemp(prefix="seedemu-stock-"))
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        source_cert, source_key = self._ensure_tls_material()
        cert_file, key_file = config / "server.crt", config / "server.key"
        shutil.copy2(source_cert, cert_file)
        shutil.copy2(source_key, key_file)
        if self._state_path:
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            if source_cert != state / "server.crt":
                shutil.copy2(source_cert, state / "server.crt")
            if source_key != state / "server.key":
                shutil.copy2(source_key, state / "server.key")
            (state / "server.key").chmod(0o600)
        key_file.chmod(0o600)
        if self._state_path:
            shutil.copy2(cert_file, state / cert_file.name)
            shutil.copy2(key_file, state / key_file.name)
            (state / key_file.name).chmod(0o600)

        start_script = config / "route-and-start.sh"
        start_script.write_text(
            "#!/bin/sh\nset -eu\n"
            "if [ -n \"${STOCK_DEFAULT_ROUTE:-}\" ]; then "
            "ip route replace default via \"$STOCK_DEFAULT_ROUTE\" || true; fi\n"
            "exec \"$@\"\n",
            encoding="utf-8",
        )
        start_script.chmod(0o700)
        config_mount = f"./{self._name}/config:/stock-config:ro"
        db_password = self._saved_or_generated_secret(state, "stock_db_password")
        token_encryption_key = self._saved_or_generated_secret(state, "stock_token_encryption_key")
        # The upstream Quickstart's bundled simulator and Liquibase config use this
        # credential. The database has no published port and stays on the emulated network.
        qr_password = "postgres"
        api_url = f"https://{self.getAddress('api')}:8447"
        address = lambda role: self.getAddress(role)
        service_name = lambda role: self.getContainer(role).getHostname()

        def set_service(role, image, content):
            container = self._containers[role]
            content.setdefault("image", image)
            content.setdefault("restart", "unless-stopped")
            content.setdefault("cap_add", ["NET_ADMIN"])
            content.setdefault("volumes", [config_mount])
            content["labels"] = {
                **container._service.get("labels", {}),
                "org.emuvista.bundle": "StockBundle", "org.emuvista.component": role,
            }
            container.updateServiceConfig(content)

        def data_volume(role, target):
            directory = state / role
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            return f"{directory}:{target}"

        set_service(
            "stock-db",
            self._images["stock-db"],
            {
                "entrypoint": ["/bin/sh", "/stock-config/route-and-start.sh"],
                "command": ["docker-entrypoint.sh", "postgres"],
                "environment": {
                    "POSTGRES_DB": "stock", "POSTGRES_USER": "stock",
                    "POSTGRES_PASSWORD": db_password, "STOCK_DEFAULT_ROUTE": self._getDefaultRoute("stock-db"),
                },
                "volumes": [config_mount, data_volume("stock-db", "/var/lib/postgresql/data")],
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U stock -d stock"],
                    "interval": "3s", "timeout": "5s", "retries": 120,
                },
            },
        )

        api_env = {
            "STOCK_DATABASE_URL": f"postgresql://stock:{db_password}@{address('stock-db')}:5432/stock",
            "STOCK_ADMIN_TOKEN": self._api_admin_token,
            "STOCK_TOKEN_ENCRYPTION_KEY": token_encryption_key,
            "STOCK_BANK_PROVIDERS": json.dumps(self._bank_providers, separators=(",", ":")),
            "STOCK_DEFAULT_ROUTE": self._getDefaultRoute("api"),
            "STOCK_EMAIL_HOST": self._email["host"],
            "STOCK_EMAIL_PORT": self._email["port"],
            "STOCK_EMAIL_USER": self._email["user"],
            "STOCK_EMAIL_PASSWORD": self._email["password"],
            "STOCK_EMAIL_FROM": self._email["sender"],
            "STOCK_EMAIL_STARTTLS": str(self._email["starttls"]).lower(),
            "QUANTREPLAY_FIX_HOST": address("quantreplay"),
            "QUANTREPLAY_FIX_PORT": 9051,
            "QUANTREPLAY_FIX_SENDER_COMP_ID": "CLIENT_XETRA",
            "QUANTREPLAY_FIX_TARGET_COMP_ID": "SIM_XETRA",
        }
        api_env = {key: str(value).replace("$", "$$") for key, value in api_env.items()}
        api_env.update({
            name: f"${{{name}:-{default}}}"
            for name, default in {
                "STOCK_MARKET_SYMBOLS": "",
                "STOCK_ALPACA_API_KEY": "",
                "STOCK_ALPACA_API_SECRET": "",
                "STOCK_ALPACA_FEED": "iex",
                "STOCK_ALPACA_HTTPS_PROXY": "",
                "STOCK_MARKET_MAX_AGE_SECONDS": "120",
            }.items()
        })
        set_service(
            "api",
            self._images["api"],
            {
                "entrypoint": ["/bin/sh", "/stock-config/route-and-start.sh"],
                "command": [
                    "uvicorn", "stock_service.api:app", "--host", "0.0.0.0", "--port", "8447",
                    "--ssl-certfile", "/stock-config/server.crt", "--ssl-keyfile", "/stock-config/server.key",
                ],
                "environment": api_env,
                "depends_on": {
                    **{service_name("stock-db"): {"condition": "service_healthy"}},
                    **{bank.getContainer("gateway").getHostname(): {"condition": "service_started"}
                       for bank, _, _ in self._banks.values()},
                },
                "healthcheck": {
                    "test": [
                        "CMD", "python", "-c",
                        "import urllib.request,ssl; urllib.request.urlopen('https://127.0.0.1:8447/health', context=ssl._create_unverified_context())",
                    ],
                    "interval": "5s", "timeout": "5s", "retries": 60,
                },
            },
        )
        if self._host_port is not None:
            self.getContainer("api").updateServiceConfig({"ports": [f"127.0.0.1:{self._host_port}:8447/tcp"]})

        set_service(
            "quantreplay-db",
            self._images["quantreplay-db"],
            {
                "environment": {
                    "POSTGRES_DB": "simdb", "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": qr_password,
                },
                "volumes": [config_mount, data_volume("quantreplay-db", "/var/lib/postgresql/data")],
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U postgres -d simdb"],
                    "interval": "3s", "timeout": "5s", "retries": 120,
                },
                "extra_hosts": [f"database:{address('quantreplay-db')}"]
            },
        )
        set_service(
            "quantreplay-liquibase",
            self._images["quantreplay-liquibase"],
            {
                "restart": "no",
                "depends_on": {service_name("quantreplay-db"): {"condition": "service_healthy"}},
                "extra_hosts": [f"database:{address('quantreplay-db')}"]
            },
        )
        set_service(
            "quantreplay",
            self._images["quantreplay"],
            {
                "environment": {"INSTANCE_ID": "XETRA", "PREFIX": "QUOD"},
                "volumes": [config_mount, data_volume("quantreplay", "/market-simulator/quod/data")],
                "depends_on": {
                    service_name("quantreplay-db"): {"condition": "service_healthy"},
                    service_name("quantreplay-liquibase"): {"condition": "service_completed_successfully"},
                },
                "extra_hosts": [f"database:{address('quantreplay-db')}"]
            },
        )

        (root / "deployment.json").write_text(
            json.dumps(
                {
                    "url": api_url, "addresses": self._addresses, "images": self._images,
                    "state_path": str(state), "persistent": self._state_path is not None,
                    "quantreplay_fix_port": 9051,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        Path("docker-compose.yml").touch(mode=0o600, exist_ok=True)
        Path("docker-compose.yml").chmod(0o600)
        return super().install()


__all__ = ["StockBundle"]
