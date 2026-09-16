"""Registration entry point for DNS-domain tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns.basic.registration import register_basic_tools
from seedemu_tool_service.tools.dns.diagnostics.registration import register_diagnostics_tools
from seedemu_tool_service.tools.dns.domain_registration.registration import (
    register_domain_registration_tools,
)


def register_dns_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register all implemented DNS tool categories."""

    register_basic_tools(registry, backend)
    register_domain_registration_tools(registry, backend)
    register_diagnostics_tools(registry, backend)
