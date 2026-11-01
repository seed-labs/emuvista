"""SEED Service bindings with a Docker ContainerBundle of prebuilt components."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from seedemu.core import Emulator, Node, Server, Service
from seedemu.core.enums import NetworkType


REVISION = "124a87b639c37952dc9a029fc7056e523a10de5b"
DEFAULT_IMAGES = {
    **{role: f"h20-komunitin-{role}:{REVISION[:12]}" for role in
       ("app", "auth", "social", "accounting", "notifications-ts", "cli")},
    "database": f"h20-komunitin-db-auth:{REVISION[:12]}",
    "redis": "redis:7-alpine",
    "stellar": "h20-stellar-quickstart:core-horizon-beb4f2f",
    "files": "h20-komunitin-s3:3.7.1",
    "gateway": "nginx:stable-alpine",
}


class PaymentServer(Server):
    """One wallet deployment, sharing its bound SEED host's network namespace."""

    def __init__(self):
        super().__init__()
        self._admin_email = "admin@payment.example"
        self._admin_password = secrets.token_urlsafe(24)
        self._admin_explicit = False
        self._initial_data: Path | bytes | None = None
        self._host_port: int | None = None
        self._state_path: Path | None = None
        self._node: Node | None = None
        self._address: str | None = None
        self._vnode = ""
        self._secrets: dict = {}

    def setAdminCredentials(self, email: str, password: str) -> PaymentServer:
        if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email):
            raise ValueError("invalid payment administrator email")
        if len(password) < 8 or any(c in password for c in "\x00\n\r"):
            raise ValueError("administrator password must have at least 8 characters and no newlines")
        self._admin_email, self._admin_password = email, password
        self._admin_explicit = True
        return self

    def setInitialData(self, bundle: str | Path | bytes) -> PaymentServer:
        """Configure a bundle path or bytes before render; compile writes the data."""
        if isinstance(bundle, bytes):
            self._initial_data = bundle
            return self
        path = Path(bundle).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"payment initial bundle does not exist: {path}")
        self._initial_data = path
        return self

    def setSavePath(self, path: str) -> PaymentServer:
        """Persist all databases, local ledger and matching credentials together."""
        self._state_path = Path(path).expanduser().resolve()
        return self

    def enableHostAccess(self, port: int = 8443) -> PaymentServer:
        """Publish a browser endpoint without changing emulated API addresses."""
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("host access port must be an integer between 1 and 65535")
        self._host_port = port
        return self

    def getAddress(self) -> str:
        if self._address is None:
            raise RuntimeError("render the emulator before reading the payment address")
        return self._address

    def getURL(self) -> str:
        return f"https://{self.getAddress()}"

    def getAdminCredentials(self) -> dict:
        return {"email": self._admin_email, "password": self._admin_password}

    def install(self, node: Node) -> None:
        node.appendClassName("PaymentService")
        if self._host_port is not None:
            node.addPort(self._host_port, 8443)
        node.setFile("/opt/seedvista/payment/service.json", json.dumps({
            "url": self.getURL(), "virtual_node": self._vnode,
            "note": "Prebuilt payment containers share this SEED host's network namespace.",
        }, indent=2))
        # Only TLS/API ports are public. All component/database ports stay local.
        node.addSoftware("iptables")
        node.appendStartCommand(
            "iptables -N SEEDVISTA_PAYMENT 2>/dev/null || true; "
            "iptables -F SEEDVISTA_PAYMENT; "
            "iptables -A SEEDVISTA_PAYMENT -i lo -j RETURN; "
            "iptables -A SEEDVISTA_PAYMENT -p tcp -m multiport --dports "
            "80,3023,3025,3026,3028,5432:5436,6379,8000:8003,9001,9090 -j REJECT; "
            "iptables -A SEEDVISTA_PAYMENT -j RETURN; "
            "iptables -C INPUT -j SEEDVISTA_PAYMENT 2>/dev/null || "
            "iptables -I INPUT 1 -j SEEDVISTA_PAYMENT"
        )


class PaymentService(Service):
    """Use ordinary SEED bindings and the existing external-container compiler API."""

    def __init__(self, images: dict[str, str] | None = None):
        super().__init__()
        self.addDependency("Base", False, False)
        self.addDependency("Routing", False, True)
        self._images = dict(DEFAULT_IMAGES)
        if images:
            for role, image in images.items():
                self.setImage(role, image)
        self._configured = False

    def setImage(self, role: str, image: str) -> PaymentService:
        if role not in DEFAULT_IMAGES:
            raise ValueError(f"unknown payment image role: {role}")
        if not image or any(c.isspace() for c in image):
            raise ValueError("payment image reference must be nonempty and contain no whitespace")
        self._images[role] = image
        return self

    def getImages(self) -> dict[str, str]:
        return dict(self._images)

    def getName(self) -> str:
        return "PaymentService"

    def _createServer(self) -> PaymentServer:
        return PaymentServer()

    def install(self, vnode: str) -> PaymentServer:
        return super().install(vnode)

    installServer = install

    def _doConfigure(self, node: Node, server: PaymentServer):
        if any(s._node is node for s in self._pending_targets.values() if s is not server):
            raise ValueError("only one PaymentServer can occupy a physical SEED host")
        address = next((str(i.getAddress()) for i in node.getInterfaces()
                        if i.getNet().getType() == NetworkType.Local), None)
        if address is None:
            raise ValueError("PaymentServer requires a local-network interface")
        server._node, server._address = node, address
        server._vnode = next(k for k, v in self._pending_targets.items() if v is server)
        server._secrets = self._credentials(server)

    @staticmethod
    def _credentials(server: PaymentServer) -> dict:
        identity = {"address": server.getAddress(), "admin_email": server._admin_email}
        path = server._state_path
        if path:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            file = path / "credentials.json"
            if file.exists():
                saved = json.loads(file.read_text())
                if saved.get("identity") != identity:
                    raise ValueError("saved PaymentService state belongs to a different address or administrator")
                if file.stat().st_mode & 0o077:
                    raise ValueError("saved PaymentService credentials must have mode 0600")
                if server._admin_explicit and server._admin_password != saved["admin_password"]:
                    raise ValueError("explicit administrator password does not match saved payment state")
                server._admin_password = saved["admin_password"]
                return saved
            if any(path.iterdir()):
                raise ValueError("payment state directory has data but no matching credentials.json")
        values = {"identity": identity, "admin_password": server._admin_password}
        for name in ("auth", "social", "accounting", "notifications", "master", "salt", "stellar", "db"):
            values[name] = secrets.token_urlsafe(32)
        if path:
            file.write_text(json.dumps(values, indent=2) + "\n")
            file.chmod(0o600)
        return values

    def configure(self, emulator: Emulator):
        super().configure(emulator)
        self._configured = True

    def getContainerBundle(self, emulator: Emulator):
        """Pass this bundle to Docker.addContainerBundle before emu.compile()."""
        from .PaymentBundle import PaymentBundle
        return PaymentBundle(emulator, self)

    def print(self, indent: int) -> str:
        return " " * indent + f"PaymentService ({len(self._pending_targets)} wallet deployments)\n"
