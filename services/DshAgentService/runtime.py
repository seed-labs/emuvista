"""Manage bundles through the running DSH Web Plugin Manager."""
from dataclasses import dataclass
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import time

from ._constants import BASE, LABEL

_RPC = Path(__file__).with_name("rpc.mjs").read_text()


@dataclass(frozen=True)
class PluginState:
    id: str
    package: str
    scope: str
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class BundleState:
    name: str
    package: str
    enabled: bool
    status: str
    plugins: tuple[PluginState, ...]


@dataclass(frozen=True)
class PluginChange:
    operation: str
    name: str
    status: str
    before: BundleState | None
    after: BundleState | None
    detail: str | None = None


class DshAgentRuntimeError(RuntimeError):
    def __init__(self, code, instance=None, bundle=None, *, change=None):
        self.code = code
        self.instance = instance
        self.bundle = bundle
        self.change = change
        message = f"{instance or 'Compose'}: {code}"
        if bundle:
            message += f" ({bundle})"
        if change and change.detail:
            message += f": {change.detail}"
        super().__init__(message)


class DshAgentRuntime:
    def __init__(self, command, services):
        self._command = command
        self._services = services

    @classmethod
    def from_compose(cls, compose_file, *, project=None):
        command = ["docker", "compose", "-f", str(Path(compose_file).resolve())]
        if project is not None:
            command += ["-p", project]
        try:
            raw = subprocess.check_output(command + ["config", "--format", "json"], text=True,
                                          stderr=subprocess.PIPE, timeout=30)
            services = json.loads(raw)["services"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            raise DshAgentRuntimeError("compose_config") from None
        return cls(command, services)

    def agent(self, name):
        matches = [service for service, config in self._services.items()
                   if (config.get("labels") or {}).get(LABEL) == name]
        if not matches:
            raise DshAgentRuntimeError("unknown_instance", name)
        if len(matches) != 1:
            raise DshAgentRuntimeError("ambiguous_instance", name)
        return DshAgentHandle(self._command, name, matches[0])


class DshAgentHandle:
    def __init__(self, command, name, service, *, port=None, log=None):
        self._command = command
        self.name = name
        self.service = service
        self._port = port
        self._log = log
        self.plugins = _Plugins(self)

    def for_process(self, *, port, log):
        """Select an isolated DSH Web process in this same instance's container."""
        if type(port) is not int or not 1 <= port <= 65535 or not PurePosixPath(log).is_absolute():
            raise ValueError("Expected a valid port and an absolute container log path")
        return DshAgentHandle(self._command, self.name, self.service, port=port, log=str(log))

    @property
    def container(self):
        try:
            ids = subprocess.check_output(self._command + ["ps", "-q", self.service],
                                          text=True, stderr=subprocess.PIPE, timeout=15).split()
        except (OSError, subprocess.SubprocessError):
            raise DshAgentRuntimeError("compose_ps", self.name) from None
        if len(ids) != 1:
            code = "instance_not_running" if not ids else "ambiguous_instance"
            raise DshAgentRuntimeError(code, self.name)
        return ids[0]

    def metadata(self, *, container=None):
        try:
            raw = subprocess.check_output(["docker", "exec", container or self.container, "cat", BASE + "/instance.json"],
                                          text=True, stderr=subprocess.PIPE, timeout=15)
            return json.loads(raw)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise DshAgentRuntimeError("instance_metadata", self.name) from None

    def _rpc(self, container, method, args, timeout):
        address = [str(self._port or 3080), self._log or BASE + "/web.log", method]
        try:
            result = subprocess.run(
                ["docker", "exec", "-i", container, "node", "--input-type=module", "-e", _RPC, *address],
                input=json.dumps(args), text=True, capture_output=True, timeout=timeout, check=True,
            )
            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            raise DshAgentRuntimeError("timeout", self.name) from None
        except (OSError, subprocess.SubprocessError, ValueError):
            raise DshAgentRuntimeError("disconnected", self.name) from None
        if "error" in data:
            raise DshAgentRuntimeError(data["error"], self.name)
        return data["value"]


class _Plugins:
    def __init__(self, agent):
        self._agent = agent

    def _list(self, container, metadata, timeout=15):
        bundles = self._agent._rpc(container, "pluginManager/listBundles", {}, timeout)
        live = self._agent._rpc(container, "pluginManager/listPlugins", {}, timeout)
        by_entry = {plugin.get("entryId"): plugin for plugin in live}
        declared = {b["package"]: b for b in metadata["bundles"]}
        states = []
        for bundle in bundles:
            package = bundle["name"]
            info = declared.get(package, {})
            rows = {r["rowId"]: r for r in bundle.get("rows", [])}
            members = info.get("rows", [
                {"row": i, "id": i, "package": r["moduleName"], "scope": "host"} for i, r in rows.items()
            ])
            plugins = []
            for member in members:
                row = rows.get(member["row"], {})
                entry = by_entry.get(row.get("entryId"), {})
                phase = entry.get("fiberPhase", entry.get("phase"))
                status = {"active": "active", "failed": "failed", "error": "failed",
                          "waiting": "pending", "loading": "pending", "inactive": "inactive",
                          "disabled": "inactive"}.get(phase, "unknown")
                if not bundle["enabled"] and not entry:
                    status = "inactive"
                plugins.append(PluginState(member["id"], member["package"], member["scope"], status))
            statuses = {p.status for p in plugins}
            if bundle.get("error") or "failed" in statuses:
                status = "failed"
            elif not bundle["enabled"]:
                status = "inactive" if statuses <= {"inactive"} else "pending"
            elif statuses == {"active"}:
                status = "active"
            elif "pending" in statuses:
                status = "pending"
            else:
                status = "unknown"
            states.append(BundleState(info.get("name", package), package, bundle["enabled"], status, tuple(plugins)))
        return tuple(sorted(states, key=lambda state: state.name))

    def list(self):
        container = self._agent.container
        return self._list(container, self._agent.metadata(container=container))

    def _select(self, states, name):
        matches = [b for b in states if name in (b.name, b.package)]
        if len(matches) != 1:
            code = "bundle_not_installed" if not matches else "ambiguous_bundle"
            raise DshAgentRuntimeError(code, self._agent.name, name)
        return matches[0]

    def get(self, name):
        return self._select(self.list(), name)

    def enable(self, name, *, wait=True, timeout=30, check=True):
        return self._change(name, True, wait, timeout, check)

    def disable(self, name, *, wait=True, timeout=30, check=True):
        return self._change(name, False, wait, timeout, check)

    def _change(self, name, enabled, wait, timeout, check):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        container = self._agent.container
        metadata = self._agent.metadata(container=container)
        before = self._select(self._list(container, metadata), name)
        operation = "enable" if enabled else "disable"
        target = "active" if enabled else "inactive"
        after, detail = before, None
        if before.enabled == enabled and before.status == target:
            status = "applied"
        else:
            deadline = time.monotonic() + timeout
            try:
                reply = self._agent._rpc(container, "pluginManager/setBundleEnabled",
                                         {"name": before.package, "enabled": enabled}, timeout)
                application = reply.get("application")
                if application == "restart-required":
                    status = "restart_required"
                elif application != "applied":
                    status = "failed"
                    detail = (reply.get("error") or {}).get("code") or application
                elif not wait:
                    status = "pending"
                else:
                    status = "timeout"
                    while (left := deadline - time.monotonic()) > 0:
                        after = self._select(self._list(container, metadata, left), name)
                        if after.enabled == enabled and after.status == target:
                            status = "applied"
                            break
                        if after.status == "failed":
                            status = "failed"
                            break
                        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            except DshAgentRuntimeError as exc:
                if exc.code not in ("timeout", "disconnected"):
                    raise
                status, detail = "timeout", "Query the running instance before retrying"
        result = PluginChange(operation, name, status, before, after, detail)
        if check and status not in ({"applied"} if wait else {"applied", "pending"}):
            raise DshAgentRuntimeError(status, self._agent.name, name, change=result)
        return result
