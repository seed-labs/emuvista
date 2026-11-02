"""BGP-domain tool tests."""

from collections.abc import Sequence

import anyio

from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from tests.registry_support import ToolRegistry
from seedemu_tool_service.tools.bgp import register_bgp_tools


class FakeRuntimeBackend:
    def __init__(self, result: RuntimeCommandResult | None = None) -> None:
        self.result = result or RuntimeCommandResult(
            exit_code=0,
            stdout="Neighbor V AS MsgRcvd MsgSent Up/Down State/PfxRcd\n",
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


def test_bgp_domain_registers_summary_tool() -> None:
    registry = ToolRegistry()

    register_bgp_tools(registry, FakeRuntimeBackend())

    definitions = registry.list_tools()
    assert [tool.name for tool in definitions] == ["bgp.summary"]
    assert definitions[0].domain == "bgp"
    assert list(definitions[0].input_schema["properties"]) == ["source"]


def test_summary_executes_vtysh_in_router() -> None:
    backend = FakeRuntimeBackend()
    registry = ToolRegistry()
    register_bgp_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "bgp.summary",
        {"source": "as150-router-0"},
    )

    assert backend.container == "as150-router-0"
    assert backend.command == ["vtysh", "-c", "show bgp ipv4 unicast summary"]
    assert result.successful is True
    assert "Neighbor" in result.output


def test_summary_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(exit_code=1, stdout="", stderr="vtysh unavailable")
    )
    registry = ToolRegistry()
    register_bgp_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "bgp.summary",
        {"source": "router"},
    )

    assert result.successful is False
    assert result.stderr == "vtysh unavailable"
