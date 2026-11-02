"""DNS-domain tool tests."""

from collections.abc import Sequence

import anyio
import pytest
from pydantic import ValidationError

from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from tests.registry_support import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools


class FakeRuntimeBackend:
    def __init__(self, result: RuntimeCommandResult | None = None) -> None:
        self.result = result or RuntimeCommandResult(
            exit_code=0,
            stdout="192.0.2.10\n192.0.2.11\n",
            stderr="",
        )
        self.container: str | None = None
        self.command: list[str] | None = None

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.command = list(command)
        return self.result


def test_dns_domain_registers_lookup_tool() -> None:
    registry = ToolRegistry()

    register_dns_tools(registry, FakeRuntimeBackend())

    definitions = registry.list_tools()
    assert [tool.name for tool in definitions] == ["dns.lookup"]
    assert definitions[0].domain == "dns"
    properties = definitions[0].input_schema["properties"]
    assert properties["record_type"]["default"] == "A"
    assert properties["timeout_seconds"]["maximum"] == 30


def test_lookup_uses_source_resolver_by_default() -> None:
    backend = FakeRuntimeBackend()
    registry = ToolRegistry()
    register_dns_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "dns.lookup",
        {"source": "as150-host-0", "name": "www.example.test"},
    )

    assert backend.container == "as150-host-0"
    assert backend.command == [
        "dig",
        "+time=3",
        "+tries=1",
        "+short",
        "www.example.test",
        "A",
    ]
    assert result.successful is True
    assert result.answers == ["192.0.2.10", "192.0.2.11"]


def test_lookup_can_query_a_specific_server() -> None:
    backend = FakeRuntimeBackend()
    registry = ToolRegistry()
    register_dns_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "dns.lookup",
        {
            "source": "client",
            "name": "example.test",
            "record_type": "AAAA",
            "server": "10.0.0.53",
            "timeout_seconds": 5,
        },
    )

    assert backend.command == [
        "dig",
        "+time=5",
        "+tries=1",
        "+short",
        "@10.0.0.53",
        "example.test",
        "AAAA",
    ]
    assert result.record_type == "AAAA"
    assert result.server == "10.0.0.53"


def test_lookup_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(exit_code=9, stdout="", stderr="query timed out")
    )
    registry = ToolRegistry()
    register_dns_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "dns.lookup",
        {"source": "client", "name": "unavailable.test"},
    )

    assert result.successful is False
    assert result.answers == []
    assert result.stderr == "query timed out"


def test_lookup_arguments_are_validated_before_execution() -> None:
    registry = ToolRegistry()
    register_dns_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "dns.lookup",
            {"source": "client", "name": "example.test", "record_type": "INVALID"},
        )
