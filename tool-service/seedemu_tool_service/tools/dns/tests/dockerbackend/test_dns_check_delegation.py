"""Docker integration tests for DNS parent-child delegation checks."""

from collections.abc import Callable
from typing import Any

import anyio
import pytest

from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools

SOURCE_CONTAINER = "as150h-host_1-10.150.0.72"
ZONE = "example.net"
PARENT_SERVER = "10.152.0.72"
CHILD_SERVER = "10.163.0.71"
CHILD_NS = "ns1.example.net."
UNREACHABLE_SERVER = "192.0.2.1"


@pytest.fixture(scope="module")
def tool_registry() -> ToolRegistry:
    """Register DNS tools against the running Docker-based emulator."""

    registry = ToolRegistry()
    register_dns_tools(registry, DockerRuntimeBackend())
    return registry


def test_delegation_matches_parent_referral_glue_and_child_authority(
    tool_registry: ToolRegistry,
    show_dns_result: Callable[[Any], None],
) -> None:
    """Verify the real example.net parent and child delegation data."""

    result = anyio.run(
        tool_registry.invoke,
        "dns.check_delegation",
        {
            "source": SOURCE_CONTAINER,
            "zone": ZONE,
            "parent_server": PARENT_SERVER,
            "child_servers": [CHILD_SERVER],
        },
    )

    show_dns_result(result)

    assert result.consistent is True, result.issues
    assert result.parent_command_successful is True
    assert result.parent_response_status == "NOERROR"
    assert result.parent_ns_names == [CHILD_NS]
    assert result.missing_glue_names == []
    assert any(
        record.name == CHILD_NS
        and record.record_type == "A"
        and record.value == CHILD_SERVER
        for record in result.glue_records
    )

    assert len(result.child_results) == 1
    child_result = result.child_results[0]
    assert child_result.server == CHILD_SERVER
    assert child_result.command_successful is True
    assert child_result.response_status == "NOERROR"
    assert child_result.authoritative is True
    assert child_result.ns_names == [CHILD_NS]
    assert child_result.ns_matches_parent is True
    assert child_result.issues == []


def test_delegation_reports_an_unreachable_child_server(
    tool_registry: ToolRegistry,
    show_dns_result: Callable[[Any], None],
) -> None:
    """Keep the valid parent referral while diagnosing a child timeout."""

    result = anyio.run(
        tool_registry.invoke,
        "dns.check_delegation",
        {
            "source": SOURCE_CONTAINER,
            "zone": ZONE,
            "parent_server": PARENT_SERVER,
            "child_servers": [UNREACHABLE_SERVER],
            "timeout_seconds": 1,
        },
    )

    show_dns_result(result)

    assert result.parent_command_successful is True
    assert result.parent_response_status == "NOERROR"
    assert result.parent_ns_names == [CHILD_NS]
    assert result.missing_glue_names == []
    assert result.consistent is False

    child_result = result.child_results[0]
    assert child_result.server == UNREACHABLE_SERVER
    assert child_result.command_successful is False
    assert child_result.response_status == "timeout"
    assert child_result.authoritative is False
    assert child_result.ns_names == []
    assert child_result.ns_matches_parent is False
    assert "query failed" in child_result.issues
    assert "returned timeout" in child_result.issues
    assert any(UNREACHABLE_SERVER in issue for issue in result.issues)
