"""Composite SEED Emulator service for a reusable Nextcloud cloud drive."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from re import sub
from typing import Dict

from seedemu.core import Emulator, Node, Server, Service

from .CloudDriveCredentials import CloudDriveCredentialManager
from .CloudDriveServer import NextcloudServer, ObjectStorageServer, PostgreSQLServer


class CloudDriveService(Service):
    """Coordinate Nextcloud, PostgreSQL, and object-storage logical roles.

    A drive vnode is always bound normally. Database and object-storage vnodes
    inherit the referencing drive's physical node unless the topology supplies
    an explicit Binding for that role vnode.
    """

    def __init__(
        self,
        credentials: CloudDriveCredentialManager | None = None,
        saveState: bool = False,
        savePath: str = "./cloud-drive-states",
        override: bool = False,
    ) -> None:
        """Create the service and optionally bind role state to the host.

        The persistence shape follows EthereumService: it is disabled by
        default, uses a caller-selected host directory, and archives an
        existing directory when ``override`` is true. Unlike EthereumService,
        an existing directory is loaded by default because all CloudDrive
        roles must reuse the credentials associated with their saved data.
        """
        super().__init__()
        self._save_state = bool(saveState)
        self._save_path = Path(savePath).expanduser().resolve()
        self._override_state = bool(override)
        self._persistence_prepared = False
        self._persistence_attached: set[tuple[int, str]] = set()
        state_file = self._credential_state_file()
        if self._save_state and self._save_path.exists() and not self._override_state:
            if state_file.exists():
                saved_credentials = CloudDriveCredentialManager.load(state_file)
                if credentials is None:
                    credentials = saved_credentials
                elif credentials.isEmpty():
                    credentials.importState(saved_credentials.toDict())
                elif credentials.toDict() != saved_credentials.toDict():
                    raise ValueError(
                        "explicit credentials do not match the saved CloudDrive state"
                    )
            elif any(self._save_path.iterdir()):
                raise ValueError(
                    f'CloudDrive state directory "{self._save_path}" has data but no credentials.json'
                )
        self._credentials = credentials or CloudDriveCredentialManager()
        self._drives: Dict[str, NextcloudServer] = {}
        self._databases: Dict[str, PostgreSQLServer] = {}
        self._object_storages: Dict[str, ObjectStorageServer] = {}
        self._install_plan: list[tuple[Server, Node]] = []
        self.addDependency("Base", False, False)
        self.addDependency("Routing", False, True)
        self.addDependency("CertificateAuthority", False, True)

    @classmethod
    def loadState(cls, savePath: str) -> CloudDriveService:
        """Load an existing persistent deployment using its saved credentials."""
        return cls(saveState=True, savePath=savePath)

    def isSave(self) -> bool:
        return self._save_state

    def getSavePath(self) -> str:
        return str(self._save_path)

    def _credential_state_file(self) -> Path:
        return self._save_path / "credentials.json"

    @staticmethod
    def _state_component(vnode: str) -> str:
        readable = sub(r"[^A-Za-z0-9_.-]+", "-", vnode).strip("-.") or "role"
        return f"{readable[:48]}-{sha256(vnode.encode('utf-8')).hexdigest()[:10]}"

    def _archive_existing_state(self) -> None:
        suffix = 1
        while True:
            candidate = self._save_path.with_name(f"{self._save_path.name}-{suffix}")
            if not candidate.exists():
                self._save_path.rename(candidate)
                self._log(
                    f'CloudDrive state "{self._save_path}" archived as "{candidate}"'
                )
                return
            suffix += 1

    def _prepare_persistence(self) -> None:
        if not self._save_state or self._persistence_prepared:
            return
        if self._save_path.exists() and self._override_state:
            self._archive_existing_state()
        self._save_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._credentials.save(self._credential_state_file())
        self._persistence_prepared = True

    def _attach_persistent_directory(
        self,
        node: Node,
        container_path: str,
        host_path: Path,
    ) -> None:
        identity = (id(node), container_path)
        if identity in self._persistence_attached:
            raise ValueError(
                f'multiple CloudDrive roles requested persistent path "{container_path}" '
                f'on as{node.getAsn()}/{node.getName()}'
            )
        host_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        node.addSharedFolder(container_path, str(host_path))
        self._persistence_attached.add(identity)

    def _attach_persistence(
        self,
        database_nodes: dict[str, Node],
        object_nodes: dict[str, Node],
        drive_nodes: dict[str, Node],
    ) -> None:
        if not self._save_state:
            return
        self._prepare_persistence()
        roles = self._save_path / "roles"
        for vnode, node in database_nodes.items():
            root = roles / "database" / self._state_component(vnode)
            self._attach_persistent_directory(node, "/var/lib/postgresql", root)
        for vnode, node in object_nodes.items():
            root = roles / "object-storage" / self._state_component(vnode)
            self._attach_persistent_directory(node, "/var/lib/seedvista-s3", root)
        for vnode, node in drive_nodes.items():
            root = roles / "drive" / self._state_component(vnode)
            self._attach_persistent_directory(node, "/var/www/html/config", root / "config")
            self._attach_persistent_directory(node, "/var/www/html/data", root / "data")
            self._attach_persistent_directory(
                node, "/var/www/html/custom_apps", root / "custom_apps"
            )
            self._attach_persistent_directory(node, "/var/www/html/themes", root / "themes")

    def getName(self) -> str:
        return "CloudDriveService"

    def _createServer(self) -> Server:
        raise AssertionError(
            "CloudDriveService has multiple roles; use createDrive(), "
            "createDatabase(), or createObjectStorage()"
        )

    def install(self, vnode: str) -> Server:
        raise AssertionError(
            "CloudDriveService has multiple roles; use createDrive(), "
            "createDatabase(), or createObjectStorage()"
        )

    def _assert_new_name(self, vnode: str) -> None:
        if not vnode or vnode in self._drives or vnode in self._databases or vnode in self._object_storages:
            raise ValueError(f'CloudDriveService vnode "{vnode}" is empty or already in use')

    def createDrive(self, vnode: str) -> NextcloudServer:
        self._assert_new_name(vnode)
        server = NextcloudServer(self._credentials.driveAdmin(vnode))
        self._drives[vnode] = server
        self._pending_targets[vnode] = server
        return server

    def createDatabase(self, vnode: str) -> PostgreSQLServer:
        self._assert_new_name(vnode)
        server = PostgreSQLServer(self._credentials.database(vnode))
        self._databases[vnode] = server
        return server

    def createObjectStorage(self, vnode: str) -> ObjectStorageServer:
        self._assert_new_name(vnode)
        server = ObjectStorageServer(self._credentials.objectStorage(vnode))
        self._object_storages[vnode] = server
        return server

    @staticmethod
    def _has_explicit_binding(emulator: Emulator, vnode: str) -> bool:
        return any(binding.shoudBind(vnode) for binding in emulator.getBindings())

    @staticmethod
    def _register_service_on_node(service: CloudDriveService, node: Node) -> None:
        services = node.getAttribute("services", {})
        for name, service_info in services.items():
            other = service_info["__self"]
            if name in service.getConflicts() or service.getName() in other.getConflicts():
                raise ValueError(
                    f"{service.getName()} conflicts with {other.getName()} "
                    f"on as{node.getAsn()}/{node.getName()}"
                )
        services.setdefault(service.getName(), {"__self": service})

    def _resolve_optional_role_node(
        self,
        emulator: Emulator,
        vnode: str,
        server: Server,
        default_node: Node,
    ) -> Node:
        if not self._has_explicit_binding(emulator, vnode):
            return default_node
        self._pending_targets.setdefault(vnode, server)
        return emulator.resolvVnode(vnode)

    def configure(self, emulator: Emulator) -> None:
        if not self._drives:
            raise ValueError("CloudDriveService requires at least one drive")

        drive_nodes: dict[str, Node] = {}
        database_nodes: dict[str, Node] = {}
        object_nodes: dict[str, Node] = {}
        database_users: dict[str, set[Node]] = defaultdict(set)
        object_storage_users: dict[str, set[Node]] = defaultdict(set)

        for drive_vnode, drive in self._drives.items():
            drive_node = emulator.getBindingFor(drive_vnode)
            drive_nodes[drive_vnode] = drive_node
            database_vnode = drive.getDatabaseVnode()
            object_vnode = drive.getObjectStorageVnode()
            if database_vnode not in self._databases:
                raise ValueError(f'drive "{drive_vnode}" references unknown database "{database_vnode}"')
            if object_vnode not in self._object_storages:
                raise ValueError(f'drive "{drive_vnode}" references unknown object storage "{object_vnode}"')

            database = self._databases[database_vnode]
            object_storage = self._object_storages[object_vnode]
            database_node = self._resolve_optional_role_node(
                emulator, database_vnode, database, drive_node
            )
            object_node = self._resolve_optional_role_node(
                emulator, object_vnode, object_storage, drive_node
            )

            if database_vnode in database_nodes and database_nodes[database_vnode] is not database_node:
                raise ValueError(f'database "{database_vnode}" has ambiguous inherited placement')
            if object_vnode in object_nodes and object_nodes[object_vnode] is not object_node:
                raise ValueError(f'object storage "{object_vnode}" has ambiguous inherited placement')
            database_nodes[database_vnode] = database_node
            object_nodes[object_vnode] = object_node
            database_users[database_vnode].add(drive_node)
            object_storage_users[object_vnode].add(drive_node)

        self._attach_persistence(database_nodes, object_nodes, drive_nodes)

        self._install_plan = []
        for vnode, server in self._databases.items():
            if vnode not in database_nodes:
                raise ValueError(f'database "{vnode}" is not referenced by a drive')
            node = database_nodes[vnode]
            addresses = [
                self._node_address(drive_node) for drive_node in database_users[vnode]
            ]
            server.configure(node, addresses)
            self._install_plan.append((server, node))

        for vnode, server in self._object_storages.items():
            if vnode not in object_nodes:
                raise ValueError(f'object storage "{vnode}" is not referenced by a drive')
            node = object_nodes[vnode]
            addresses = [
                self._node_address(drive_node) for drive_node in object_storage_users[vnode]
            ]
            server.configure(node, addresses)
            self._install_plan.append((server, node))

        for vnode, server in self._drives.items():
            node = drive_nodes[vnode]
            server.configure(
                node,
                self._databases[server.getDatabaseVnode()],
                self._object_storages[server.getObjectStorageVnode()],
            )
            self._install_plan.append((server, node))

        for server, node in self._install_plan:
            self._register_service_on_node(self, node)
            node.setBaseSystem(server.getBaseSystem())

    @staticmethod
    def _node_address(node: Node) -> str:
        from .CloudDriveServer import service_address

        return service_address(node)

    def render(self, emulator: Emulator) -> None:
        seen: set[tuple[int, int]] = set()
        for server, node in self._install_plan:
            identity = (id(server), id(node))
            if identity in seen:
                continue
            seen.add(identity)
            server.install(node)
            for class_name in server.getClassNames():
                node.appendClassName(class_name)
            if server.getDisplayName():
                node.setDisplayName(server.getDisplayName())
            for host_name in server.getHostNames():
                node.addHostName(host_name)

    def getDrives(self) -> Dict[str, NextcloudServer]:
        return dict(self._drives)

    def getDatabases(self) -> Dict[str, PostgreSQLServer]:
        return dict(self._databases)

    def getObjectStorages(self) -> Dict[str, ObjectStorageServer]:
        return dict(self._object_storages)

    def getCredentialManager(self) -> CloudDriveCredentialManager:
        return self._credentials
