"""Fake-backend tests for DNS parent-child delegation checks."""

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools
from seedemu_tool_service.tools.dns.models import (
    DNSDelegationArguments,
    DNSDelegationResult,
)
from seedemu_tool_service.tools.dns.tools import DNSTools


def parent_response(*, include_second_glue: bool = True) -> str:
    """Build a parent referral for example.net."""

    second_glue = "ns2.example.net. 86400 IN A 192.0.2.54\n" if include_second_glue else ""
    return (
        ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n"
        ";; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 2, ADDITIONAL: 2\n\n"
        ";; AUTHORITY SECTION:\n"
        "example.net. 86400 IN NS ns1.example.net.\n"
        "example.net. 86400 IN NS ns2.example.net.\n\n"
        ";; ADDITIONAL SECTION:\n"
        "ns1.example.net. 86400 IN A 192.0.2.53\n"
        f"{second_glue}\n"
        ";; SERVER: 192.0.2.1#53(192.0.2.1) (UDP)\n"
    )


def child_response(*, matching: bool = True, authoritative: bool = True) -> str:
    """Build a child apex NS response."""

    flags = "qr aa" if authoritative else "qr"
    second_name = "ns2.example.net." if matching else "ns9.example.net."
    return (
        ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 2\n"
        f";; flags: {flags}; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 0\n\n"
        ";; ANSWER SECTION:\n"
        "example.net. 86400 IN NS ns1.example.net.\n"
        f"example.net. 86400 IN NS {second_name}\n\n"
        ";; SERVER: 192.0.2.53#53(192.0.2.53) (UDP)\n"
    )


def address_response(name: str, address: str) -> str:
    """Build an authoritative child address response."""

    return (
        ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 3\n"
        ";; flags: qr aa; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0\n\n"
        ";; ANSWER SECTION:\n"
        f"{name} 86400 IN A {address}\n"
    )


class FakeRuntimeBackend:
    """Return one configured result per queried server."""

    def __init__(self, results: dict[object, RuntimeCommandResult]) -> None:
        self.results = results
        self.commands: list[list[str]] = []

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        captured = list(command)
        self.commands.append(captured)
        server = next(part[1:] for part in captured if part.startswith("@"))
        return self.results.get((server, captured[-2], captured[-1]), self.results[server])


def invoke_delegation(
    backend: FakeRuntimeBackend, arguments: dict[str, object]
) -> DNSDelegationResult:
    validated = DNSDelegationArguments.model_validate(arguments)
    return DNSTools(backend).check_delegation(**validated.model_dump())


def test_delegation_tool_is_registered() -> None:
    registry = ToolRegistry()
    register_dns_tools(registry, FakeRuntimeBackend({}))

    definitions = {definition.name: definition for definition in registry.list_tools()}

    assert "dns.check_delegation" in definitions
    schema = definitions["dns.check_delegation"].input_schema
    assert schema["properties"]["timeout_seconds"]["maximum"] == 30


def test_delegation_is_consistent_when_parent_child_and_glue_match() -> None:
    backend = FakeRuntimeBackend(
        {
            "192.0.2.1": RuntimeCommandResult(
                exit_code=0, stdout=parent_response(), stderr=""
            ),
            "192.0.2.53": RuntimeCommandResult(
                exit_code=0, stdout=child_response(), stderr=""
            ),
            "192.0.2.54": RuntimeCommandResult(
                exit_code=0, stdout=child_response(), stderr=""
            ),
            ("192.0.2.53", "ns1.example.net.", "A"): RuntimeCommandResult(
                exit_code=0,
                stdout=address_response("ns1.example.net.", "192.0.2.53"),
                stderr="",
            ),
            ("192.0.2.53", "ns2.example.net.", "A"): RuntimeCommandResult(
                exit_code=0,
                stdout=address_response("ns2.example.net.", "192.0.2.54"),
                stderr="",
            ),
            ("192.0.2.54", "ns1.example.net.", "A"): RuntimeCommandResult(
                exit_code=0,
                stdout=address_response("ns1.example.net.", "192.0.2.53"),
                stderr="",
            ),
            ("192.0.2.54", "ns2.example.net.", "A"): RuntimeCommandResult(
                exit_code=0,
                stdout=address_response("ns2.example.net.", "192.0.2.54"),
                stderr="",
            ),
        }
    )

    result = invoke_delegation(
        backend,
        {
            "source": "client",
            "zone": "Example.NET",
            "parent_server": "192.0.2.1",
            "child_servers": ["192.0.2.53", "192.0.2.54"],
        },
    )

    assert result.consistent is True
    assert result.zone == "example.net."
    assert result.parent_ns_names == ["ns1.example.net.", "ns2.example.net."]
    assert result.missing_glue_names == []
    assert len(result.glue_records) == 2
    assert all(child.authoritative for child in result.child_results)
    assert all(child.ns_matches_parent for child in result.child_results)
    assert all(
        address.matches_parent
        for child in result.child_results
        for address in child.address_results
    )


def test_delegation_reports_missing_glue_and_child_mismatch() -> None:
    backend = FakeRuntimeBackend(
        {
            "192.0.2.1": RuntimeCommandResult(
                exit_code=0,
                stdout=parent_response(include_second_glue=False),
                stderr="",
            ),
            "192.0.2.53": RuntimeCommandResult(
                exit_code=0,
                stdout=child_response(matching=False, authoritative=False),
                stderr="",
            ),
            ("192.0.2.53", "ns1.example.net.", "A"): RuntimeCommandResult(
                exit_code=0,
                stdout=address_response("ns1.example.net.", "192.0.2.99"),
                stderr="",
            ),
        }
    )

    result = invoke_delegation(
        backend,
        {
            "source": "client",
            "zone": "example.net",
            "parent_server": "192.0.2.1",
            "child_servers": ["192.0.2.53"],
            "timeout_seconds": 5,
        },
    )

    assert result.consistent is False
    assert result.missing_glue_names == ["ns2.example.net."]
    assert result.child_results[0].authoritative is False
    assert result.child_results[0].ns_matches_parent is False
    assert "in-bailiwick name servers are missing glue records" in result.issues
    assert any("response is not authoritative" in issue for issue in result.issues)
    assert all("+time=5" in command for command in backend.commands)


@pytest.mark.parametrize(
    "arguments",
    [
        {"child_servers": []},
        {"child_servers": ["192.0.2.53", "192.0.2.53"]},
        {"child_servers": ["  "]},
        {"parent_server": "bad server"},
        {"timeout_seconds": 0},
    ],
)
def test_delegation_rejects_invalid_arguments(arguments: dict[str, object]) -> None:
    values: dict[str, object] = {
        "source": "client",
        "zone": "example.net",
        "parent_server": "192.0.2.1",
        "child_servers": ["192.0.2.53"],
    }
    values.update(arguments)

    with pytest.raises(ValidationError):
        DNSDelegationArguments(**values)
