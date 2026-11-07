"""Register SEEDemu CA runtime tools."""

from ..execution import RuntimeBackend
from ..catalog import ToolDefinition
from ..catalog import Catalog
from ..ca_service.models import (
    InspectCAEventsArguments,
    InspectCAServiceArguments,
)
from ..ca_service.tools import CAServiceTools


def register_ca_service_tools(registry: Catalog, backend: RuntimeBackend) -> None:
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
