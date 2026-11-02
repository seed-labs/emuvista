"""Run the SEEDemu MCP server over stdio."""

import anyio

from seedemu_tool_service.api.dependencies import get_tool_registry
from seedemu_tool_service.mcp.server import run_stdio_server


def main() -> None:
    """Start the stdio MCP transport."""

    anyio.run(run_stdio_server, get_tool_registry())


if __name__ == "__main__":
    main()
