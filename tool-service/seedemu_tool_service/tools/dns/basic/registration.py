"""Registry bindings for basic DNS tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns.basic.models import (
    DNSLookupArguments,
    DNSReverseLookupArguments,
)
from seedemu_tool_service.tools.dns.basic.tools import BasicTools


def register_basic_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register basic DNS tools."""

    tools = BasicTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="dns.lookup",
            domain="dns",
            description=(
                "Resolve DNS records from an emulated node and distinguish dig "
                "execution success from DNS response status and answer presence."
            ),
        ),
        handler=tools.lookup,
        arguments_model=DNSLookupArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="dns.reverse_lookup",
            domain="dns",
            description=(
                "Resolve PTR records for a validated IPv4 or IPv6 address using "
                "the standard reverse DNS name."
            ),
        ),
        handler=tools.reverse_lookup,
        arguments_model=DNSReverseLookupArguments,
    )
