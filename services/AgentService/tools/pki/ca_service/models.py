"""Constrained arguments for read-only SEEDemu step-ca observations."""

from pydantic import Field

from ..shared.models import ToolArguments


class InspectCAServiceArguments(ToolArguments):
    source: str
    config_path: str = "/root/.step/config/ca.json"


class InspectCAEventsArguments(ToolArguments):
    source: str
    log_path: str = "/var/step-ca.log"
    limit: int = Field(default=100, ge=1, le=1000)
