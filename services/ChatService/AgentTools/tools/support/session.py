"""Service-owned session objects and a durable, server-scoped contact directory."""

import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from threading import RLock


class ChatSessionManager:
    """Internal infrastructure, not an object NetworkBlock needs to construct."""

    def __init__(self, backend=None, *, state_directory=None, config_path=None):
        from seedemu_tool_service.backends import DockerRuntimeBackend

        self.backend = backend if backend is not None else DockerRuntimeBackend()
        path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("ChatService configuration must be an object")
        self.timeout_seconds = config.get("timeout_seconds", 30)
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("Invalid ChatService timeout_seconds")
        self._contacts = config.get("contacts", {})
        if not isinstance(self._contacts, dict):
            raise ValueError("contacts must map server URLs to contact mappings")
        self._aliases = {}
        for server, contacts in self._contacts.items():
            if not isinstance(server, str) or not isinstance(contacts, dict):
                raise ValueError("Invalid ChatService contacts configuration")
            normalized = {}
            for name, target in contacts.items():
                if (not isinstance(name, str) or not name.strip()
                        or not isinstance(target, str)
                        or not re.fullmatch(r"(?:usr|grp)[A-Za-z0-9_-]+", target)):
                    raise ValueError("Invalid ChatService contact name or ID")
                key = name.strip().casefold()
                if key in normalized and normalized[key] != target:
                    raise ValueError("Ambiguous ChatService contact name")
                normalized[key] = target
            self._aliases[server] = normalized
        directory = Path(state_directory or os.environ.get(
            "EMUVISTA_CHAT_STATE_DIR", str(Path.home() / ".emuvista" / "chat_service"),
        ))
        directory.mkdir(parents=True, exist_ok=True)
        self._database = directory / "contacts.sqlite3"
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS contacts (
                server TEXT, name TEXT, user_id TEXT, display TEXT,
                PRIMARY KEY(server, name, user_id))""")
        self._sessions = {}
        self._lock = RLock()

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self._database)) as db:
            with db:
                yield db

    def session(self, container):
        # Creation is short; each container object separately locks its operations.
        from ...tool_execuate import _ContainerTools

        with self._lock:
            if container not in self._sessions:
                self._sessions[container] = _ContainerTools(self, container)
            return self._sessions[container]

    def remember_identity(self, identity):
        if not isinstance(identity, dict):
            raise ValueError("Missing internal chat identity")
        server, name, user_id = (identity.get(key) for key in ("server", "username", "user_id"))
        if (not isinstance(server, str) or not server
                or not isinstance(name, str) or not name.strip()
                or not isinstance(user_id, str)
                or not re.fullmatch(r"usr[A-Za-z0-9_-]+", user_id)):
            raise ValueError("Invalid internal chat identity")
        with self._connection() as db:
            db.execute("INSERT OR REPLACE INTO contacts VALUES (?, ?, ?, ?)",
                       (server, name.strip().casefold(), user_id, name.strip()))
        return server

    def resolve_contact(self, server, name):
        key = name.strip().casefold()
        configured = self._aliases.get(server, {}).get(key)
        if configured:
            return configured
        with self._connection() as db:
            matches = db.execute("SELECT user_id FROM contacts WHERE server=? AND name=?",
                                 (server, key)).fetchall()
        if len(matches) > 1:
            raise ValueError("该联系人名称对应多个账号，请使用实际用户 ID 或由服务侧配置唯一名称。")
        if not matches:
            raise ValueError("找不到该联系人，请确认对方已在本服务登录，或由服务侧补充联系人配置。")
        return matches[0][0]

    def display_name(self, server, target):
        for name, value in self._contacts.get(server, {}).items():
            if value == target:
                return name
        try:
            with self._connection() as db:
                row = db.execute("SELECT display FROM contacts WHERE server=? AND user_id=? ORDER BY name LIMIT 1",
                                 (server, target)).fetchone()
        except sqlite3.Error:
            return target  # Presentation must not prevent delivery of a message batch.
        if row:
            try:
                # A displayed name should resolve back to the same sender.
                if self.resolve_contact(server, row[0]) == target:
                    return row[0]
            except (ValueError, sqlite3.Error):
                pass
        return target


_manager = None
_manager_lock = RLock()


def get_session_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ChatSessionManager()
        return _manager
