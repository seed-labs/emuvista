"""FastAPI application entry point."""

from fastapi import FastAPI

from seedemu_tool_service import __version__
from seedemu_tool_service.api.router import api_router
from seedemu_tool_service.config import get_settings
from seedemu_tool_service.models.service import ServiceInfo


def create_app() -> FastAPI:
    """Create and configure the REST application."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Agent-facing actions and observations for SEED-Emulator.",
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", tags=["service"], response_model=ServiceInfo)
    def service_info() -> ServiceInfo:
        return ServiceInfo(
            name=settings.app_name,
            version=__version__,
            docs_url=application.docs_url,
        )

    return application


app = create_app()
