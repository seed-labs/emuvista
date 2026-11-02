"""Expose registered SEEDemu tools through the Model Context Protocol."""

import json
import os
from collections.abc import Callable
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python

from seedemu_tool_service import __version__
from seedemu_tool_service.auth.audit import configure_audit_logging
from seedemu_tool_service.auth.authentication import (
    AuthenticationError,
    PolicyUnavailable,
    TokenAuthenticator,
)
from seedemu_tool_service.auth.authorization import AccessContext, AccessDenied
from seedemu_tool_service.registry.registry import ToolRegistry


def create_mcp_server(
    registry: ToolRegistry,
    *,
    authenticator: TokenAuthenticator | None = None,
    access_provider: Callable[[], AccessContext] | None = None,
) -> Server[Any]:
    """Create an MCP server backed by an existing tool registry."""

    authenticator = authenticator or TokenAuthenticator()

    def request_access(context: Any) -> AccessContext:
        headers = context.request.headers if context.request is not None else None
        # HTTP credentials must be checked per request, never inherited from a session.
        if headers is not None:
            return authenticator.from_header(headers.get("authorization"))
        if access_provider is not None:
            return access_provider()
        raise AuthenticationError("Authenticated agent identity required")

    async def list_tools(
        _context: Any,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=definition.name,
                    description=definition.description,
                    inputSchema=definition.input_schema,
                )
                for definition in registry.list_tools(access=request_access(_context))
            ]
        )

    async def call_tool(
        _context: Any,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        try:
            result = await registry.invoke(
                params.name,
                params.arguments or {},
                access=request_access(_context),
            )
        except (AuthenticationError, AccessDenied, PolicyUnavailable) as error:
            return _error_result(str(error))
        except (KeyError, ValidationError, ValueError) as error:
            return _error_result(str(error))
        except Exception:
            return _error_result("Tool execution failed")

        payload = _result_payload(result)
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=json.dumps(payload, ensure_ascii=False, indent=2),
                )
            ],
            structuredContent=payload,
        )

    return Server(
        "seedemu-agent-tools",
        version=__version__,
        description="Agent-facing tools for inspecting and operating SEED Emulator labs.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def run_stdio_server(registry: ToolRegistry) -> None:
    """Run the registry-backed MCP server over standard input and output."""

    configure_audit_logging()
    authenticator = TokenAuthenticator()
    token = os.environ.get("SEEDEMU_AGENT_TOKEN", "")
    authenticator.authenticate(token)  # Fail before serving if configuration is invalid.
    server = create_mcp_server(
        registry,
        access_provider=lambda: authenticator.authenticate(token),
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        value = result.model_dump(mode="json")
    else:
        value = to_jsonable_python(result)
    return value if isinstance(value, dict) else {"result": value}


def _error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        isError=True,
    )
