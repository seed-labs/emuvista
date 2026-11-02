"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from seedemu_tool_service import __version__
from seedemu_tool_service.api.dependencies import get_tool_registry
from seedemu_tool_service.api.errors import register_exception_handlers
from seedemu_tool_service.api.router import api_router
from seedemu_tool_service.auth.audit import configure_audit_logging
from seedemu_tool_service.auth.authentication import TokenAuthenticator
from seedemu_tool_service.auth.http import FixedTokenMiddleware
from seedemu_tool_service.config import get_settings
from seedemu_tool_service.mcp import create_mcp_server
from seedemu_tool_service.models.service import ServiceInfo


def create_app(*, authenticator: TokenAuthenticator | None = None) -> FastAPI:
    """Create the REST and MCP service with shared token authorization."""

    configure_audit_logging()
    settings = get_settings()
    authenticator = authenticator or TokenAuthenticator()
    mcp_server = create_mcp_server(get_tool_registry(), authenticator=authenticator)
    mcp_application = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Agent-facing actions and observations for SEED-Emulator.",
        lifespan=lifespan,
    )
    register_exception_handlers(application)
    application.add_middleware(FixedTokenMiddleware, authenticator=authenticator)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", tags=["service"], response_model=ServiceInfo)
    def service_info() -> ServiceInfo:
        return ServiceInfo(
            name=settings.app_name,
            version=__version__,
            docs_url=application.docs_url,
        )

    application.mount("/", mcp_application, name="mcp")
    return application


app = create_app()
