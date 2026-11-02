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
    for name, description, model in (
        (
            "inspect_ca_service",
            "Inspect SEEDemu step-ca configuration and process state.",
            InspectCAServiceArguments,
        ),
        (
            "inspect_ca_events",
            "Read bounded, sanitized step-ca log events.",
            InspectCAEventsArguments,
        ),
    ):
        registry.register(
            ToolDefinition(name="pki." + name, domain="pki", description=description),
            getattr(tools, name),
            model,
        )
