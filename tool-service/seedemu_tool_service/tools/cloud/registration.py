"""Registration entry point for cloud-storage tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.cloud.models import (
    CloudStorageFindArguments,
    FileDownloadArguments,
    FileShareArguments,
    FileUploadArguments,
)
from seedemu_tool_service.tools.cloud.tools import CloudTools


def register_cloud_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register the explicit, agent-facing Nextcloud operation set."""

    tools = CloudTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="cloud.storage_find", domain="cloud",
            description="Discover Nextcloud services explicitly assigned to an emulated source.",
        ), handler=tools.storage_find, arguments_model=CloudStorageFindArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="cloud.file_upload", domain="cloud",
            description="Upload bounded base64 content to an assigned Nextcloud service through WebDAV.",
        ), handler=tools.file_upload, arguments_model=FileUploadArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="cloud.file_download", domain="cloud",
            description="Download one bounded file through WebDAV from an assigned Nextcloud service.",
        ), handler=tools.file_download, arguments_model=FileDownloadArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="cloud.file_share", domain="cloud",
            description="Create a read-only Nextcloud user share through the owner source's OCS API.",
        ), handler=tools.file_share, arguments_model=FileShareArguments,
    )
