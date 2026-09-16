"""Registry bindings for diagnostics DNS tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns.diagnostics.models import (
    DNSCompareArguments,
    DNSDelegationArguments,
    DNSTraceArguments,
)
from seedemu_tool_service.tools.dns.diagnostics.tools import DiagnosticTools


def register_diagnostics_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register diagnostics DNS tools."""

    tools = DiagnosticTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="dns.compare",
            domain="dns",
            description=(
                "Query the same record from multiple DNS servers using one source "
                "node and compare statuses, answers, TTLs, latency, and timeouts."
            ),
        ),
        handler=tools.compare,
        arguments_model=DNSCompareArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="dns.trace",
            domain="dns",
            description=(
                "Trace DNS resolution through the delegation chain. Use this to "
                "diagnose authority paths; use dns.lookup for ordinary resolution."
            ),
        ),
        handler=tools.trace,
        arguments_model=DNSTraceArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="dns.check_delegation",
            domain="dns",
            description=(
                "Compare a parent zone's referral and glue records with NS records "
                "returned authoritatively by the delegated child servers."
            ),
        ),
        handler=tools.check_delegation,
        arguments_model=DNSDelegationArguments,
    )
