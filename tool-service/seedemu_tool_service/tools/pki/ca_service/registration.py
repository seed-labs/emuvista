"""Register SEEDemu CA runtime tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.ca_service.models import (
    InspectCAEventsArguments,
    InspectCAServiceArguments,
)
from seedemu_tool_service.tools.pki.ca_service.tools import CAServiceTools


def register_ca_service_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    tools = CAServiceTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_ca_service",
            domain="pki",
            description="Inspect SEEDemu step-ca configuration and process state.",
        ),
        handler=tools.inspect_ca_service,
        arguments_model=InspectCAServiceArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_ca_events",
            domain="pki",
            description="Read bounded, sanitized step-ca log events.",
        ),
        handler=tools.inspect_ca_events,
        arguments_model=InspectCAEventsArguments,
    )
