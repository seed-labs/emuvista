"""Tests for stateless Benchmark topology facts and operations."""

from seedemu_tool_service.models.runtime import RuntimeCommandResult
from tests.registry_support import ToolRegistry
from seedemu_tool_service.tools.benchmark.registration import register_benchmark_tools
from seedemu_tool_service.tools.benchmark.tools import BenchmarkTools


class FakeBackend:
    def __init__(self) -> None:
        self.running = True
        self.commands: list[list[str]] = []

    def list_projects(self): return [{"project": "lab", "total": 1, "running": 1}]
    def describe_project(self, project): return {"project": project, "services": [{"service": "host", "status": "running"}], "networks": []}
    def list_project_containers(self, project): return [{"service": "host", "status": "running", "name": "host", "image": "seed"}]
    def service_status(self, project, service): return {"project": project, "service": service, "running": self.running, "status": "running" if self.running else "exited"}
    def stop_service(self, project, service): self.running = False; return self.service_status(project, service)
    def start_service(self, project, service): self.running = True; return self.service_status(project, service)
    def execute_service(self, project, service, command):
        self.commands.append(list(command))
        if command[:2] == ["getent", "hosts"]: return RuntimeCommandResult(exit_code=0, stdout="192.0.2.2 host\n", stderr="")
        return RuntimeCommandResult(exit_code=0, stdout="nameserver 127.0.0.11\n", stderr="")


def test_registry_exposes_only_facts_and_generic_operations() -> None:
    registry = ToolRegistry(); register_benchmark_tools(registry, FakeBackend())
    names = {item.name for item in registry.list_tools()}
    assert "benchmark.runtime.describe" in names
    assert "operation.container.stop" in names
    assert "operation.dns.set_nameserver" in names
    assert not any(name.startswith("benchmark.session.") for name in names)
    assert not any(name.startswith("benchmark.grant.") for name in names)
    assert not any("inject" in name or "recover" in name for name in names)


def test_operations_are_project_service_scoped_and_stateless() -> None:
    backend = FakeBackend(); tools = BenchmarkTools(backend)
    assert tools.container_stop("lab", "host")["running"] is False
    assert tools.container_start("lab", "host")["running"] is True
    probe = tools.dns_probe("lab", "host", "example.test")
    assert probe["healthy"] is True
    changed = tools.dns_set_nameserver("lab", "host", "192.0.2.1")
    assert changed["changed"] is True
    assert not hasattr(tools, "check_grant")
    assert not hasattr(tools, "session_create")


def test_service_capabilities_never_classify_faults() -> None:
    result = BenchmarkTools(FakeBackend()).runtime_service_capabilities("lab", "host")
    assert result["read_only"] is True
    assert "available_faults" not in result
    assert result["operations"]["dns.resolver"] is True
