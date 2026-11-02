"""MCP adapter tests."""

from typing import Any

import anyio
from mcp import Client
from pydantic import BaseModel, Field

from seedemu_tool_service.main import create_app
from seedemu_tool_service.mcp import create_mcp_server
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry.registry import ToolRegistry
from tests.registry_support import TEST_ACCESS


class EchoArguments(BaseModel):
    """Arguments for the MCP adapter test tool."""

    message: str = Field(min_length=1)


class EchoResult(BaseModel):
    """Structured result returned by the MCP adapter test tool."""

    echoed: str


def _test_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        definition=ToolDefinition(
            name="test.echo",
            domain="test",
            description="Echo a test message.",
        ),
        handler=lambda message: EchoResult(echoed=message),
        arguments_model=EchoArguments,
    )
    return registry


def test_mcp_lists_registry_tools_with_original_schema() -> None:
    async def exercise() -> None:
        async with Client(
            create_mcp_server(_test_registry(), access_provider=lambda: TEST_ACCESS)
        ) as client:
            result = await client.list_tools()

        assert [tool.name for tool in result.tools] == ["test.echo"]
        assert result.tools[0].description == "Echo a test message."
        assert result.tools[0].input_schema["required"] == ["message"]

    anyio.run(exercise)


def test_mcp_invokes_registry_tool_with_structured_result() -> None:
    async def exercise() -> None:
        async with Client(
            create_mcp_server(_test_registry(), access_provider=lambda: TEST_ACCESS)
        ) as client:
            result = await client.call_tool("test.echo", {"message": "hello"})

        assert result.is_error is False
        assert result.structured_content == {"echoed": "hello"}
        assert result.content[0].text == '{\n  "echoed": "hello"\n}'

    anyio.run(exercise)


def test_mcp_returns_readable_validation_error() -> None:
    async def exercise() -> None:
        async with Client(
            create_mcp_server(_test_registry(), access_provider=lambda: TEST_ACCESS)
        ) as client:
            result = await client.call_tool("test.echo", {"message": ""})

        assert result.is_error is True
        assert "String should have at least 1 character" in result.content[0].text

    anyio.run(exercise)


def test_fastapi_mounts_streamable_http_mcp() -> None:
    application = create_app()

    mounts: list[Any] = [
        route
        for route in application.routes
        if getattr(route, "path", None) == "" and getattr(route, "name", None) == "mcp"
    ]
    assert len(mounts) == 1
