"""Random, per-topology credentials for CloudDriveService roles."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from re import fullmatch
from secrets import token_hex, token_urlsafe
from tempfile import NamedTemporaryFile
from typing import Any


@dataclass
class DatabaseCredentials:
    username: str
    password: str


@dataclass
class ObjectStorageCredentials:
    access_key: str
    secret_key: str


@dataclass
class DriveAdminCredentials:
    username: str
    password: str


class CloudDriveCredentialManager:
    """Generate and retain credentials shared by related logical roles.

    Credentials are created once for each vnode while a topology is built.
    Server setters update the same managed objects, so explicit credentials
    remain supported for deterministic fixtures and externally managed secrets.
    """

    def __init__(self) -> None:
        self._databases: dict[str, DatabaseCredentials] = {}
        self._object_storages: dict[str, ObjectStorageCredentials] = {}
        self._drive_admins: dict[str, DriveAdminCredentials] = {}

    def database(self, vnode: str) -> DatabaseCredentials:
        return self._databases.setdefault(
            vnode,
            DatabaseCredentials(username="nextcloud", password=token_urlsafe(32)),
        )

    def objectStorage(self, vnode: str) -> ObjectStorageCredentials:
        return self._object_storages.setdefault(
            vnode,
            ObjectStorageCredentials(
                access_key=token_hex(16).upper(),
                secret_key=token_urlsafe(48),
            ),
        )

    def driveAdmin(self, vnode: str) -> DriveAdminCredentials:
        return self._drive_admins.setdefault(
            vnode,
            DriveAdminCredentials(username="admin", password=token_urlsafe(32)),
        )

    def getDatabase(self, vnode: str) -> DatabaseCredentials:
        return replace(self._databases[vnode])

    def getObjectStorage(self, vnode: str) -> ObjectStorageCredentials:
        return replace(self._object_storages[vnode])

    def getDriveAdmin(self, vnode: str) -> DriveAdminCredentials:
        return replace(self._drive_admins[vnode])

    def isEmpty(self) -> bool:
        return not (self._databases or self._object_storages or self._drive_admins)

    def toDict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "databases": {
                vnode: {"username": item.username, "password": item.password}
                for vnode, item in sorted(self._databases.items())
            },
            "object_storages": {
                vnode: {
                    "access_key": item.access_key,
                    "secret_key": item.secret_key,
                }
                for vnode, item in sorted(self._object_storages.items())
            },
            "drive_admins": {
                vnode: {"username": item.username, "password": item.password}
                for vnode, item in sorted(self._drive_admins.items())
            },
        }

    def importState(self, state: dict[str, Any]) -> None:
        if not self.isEmpty():
            raise ValueError("cannot import credentials into a non-empty manager")
        if state.get("version") != 1:
            raise ValueError("unsupported CloudDrive credential-state version")
        databases = state.get("databases", {})
        object_storages = state.get("object_storages", {})
        drive_admins = state.get("drive_admins", {})
        if not all(
            isinstance(section, dict)
            for section in (databases, object_storages, drive_admins)
        ):
            raise ValueError("CloudDrive credential sections must be JSON objects")

        def validate_vnode(vnode: Any) -> str:
            if not isinstance(vnode, str) or not vnode:
                raise ValueError("CloudDrive credential vnode names must be non-empty strings")
            return vnode

        def validate_identifier(value: Any, field: str) -> str:
            if not isinstance(value, str) or not fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]{0,62}", value
            ):
                raise ValueError(f"invalid {field} in CloudDrive credential state")
            return value

        def validate_secret(value: Any, field: str) -> str:
            if (
                not isinstance(value, str)
                or not value
                or any(character in value for character in ("\x00", "\n", "\r", "'"))
            ):
                raise ValueError(f"invalid {field} in CloudDrive credential state")
            return value

        self._databases = {}
        for vnode, item in databases.items():
            validate_vnode(vnode)
            if not isinstance(item, dict) or set(item) != {"username", "password"}:
                raise ValueError("invalid database credentials in CloudDrive state")
            self._databases[vnode] = DatabaseCredentials(
                username=validate_identifier(item["username"], "database username"),
                password=validate_secret(item["password"], "database password"),
            )

        self._object_storages = {}
        for vnode, item in object_storages.items():
            validate_vnode(vnode)
            if not isinstance(item, dict) or set(item) != {"access_key", "secret_key"}:
                raise ValueError("invalid object-storage credentials in CloudDrive state")
            self._object_storages[vnode] = ObjectStorageCredentials(
                access_key=validate_secret(item["access_key"], "object access key"),
                secret_key=validate_secret(item["secret_key"], "object secret key"),
            )

        self._drive_admins = {}
        for vnode, item in drive_admins.items():
            validate_vnode(vnode)
            if not isinstance(item, dict) or set(item) != {"username", "password"}:
                raise ValueError("invalid drive credentials in CloudDrive state")
            self._drive_admins[vnode] = DriveAdminCredentials(
                username=validate_identifier(item["username"], "drive admin username"),
                password=validate_secret(item["password"], "drive admin password"),
            )

    @classmethod
    def load(cls, state_file: str | Path) -> CloudDriveCredentialManager:
        path = Path(state_file)
        try:
            if path.stat().st_mode & 0o077:
                raise ValueError(
                    f'CloudDrive credential file "{path}" must not be accessible by group or others'
                )
            state = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f'cannot load CloudDrive credentials from "{path}"') from error
        if not isinstance(state, dict):
            raise ValueError("CloudDrive credential state must be a JSON object")
        manager = cls()
        manager.importState(state)
        return manager

    def save(self, state_file: str | Path) -> None:
        path = Path(state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                os.chmod(temporary_name, 0o600)
                json.dump(self.toDict(), temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
            os.chmod(path, 0o600)
        finally:
            if temporary_name is not None and os.path.exists(temporary_name):
                os.unlink(temporary_name)
