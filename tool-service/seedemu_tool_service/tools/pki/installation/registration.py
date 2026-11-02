"""Registry bindings for certificate installation PKI tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.installation.models import (
    BackupCertificateMaterialArguments,
    PathPairArguments,
    RestoreCertificateMaterialArguments,
)
from seedemu_tool_service.tools.pki.installation.tools import InstallationTools


def register_installation_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register certificate installation tools."""

    tools = InstallationTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.backup_certificate_material",
            domain="pki",
            description="Back up application certificate material outside Certbot-managed paths.",
        ),
        handler=tools.backup_certificate_material,
        arguments_model=BackupCertificateMaterialArguments,
    )
    for name, description, handler in [
        (
            "pki.install_certificate",
            "Install a certificate outside Certbot-managed paths.",
            tools.install_certificate,
        ),
        (
            "pki.install_private_key",
            "Install an application private key outside Certbot-managed paths with restrictive permissions.",
            tools.install_private_key,
        ),
        (
            "pki.install_certificate_chain",
            "Install a certificate chain bundle outside Certbot-managed paths.",
            tools.install_certificate_chain,
        ),
    ]:
        registry.register(
            definition=ToolDefinition(name=name, domain="pki", description=description),
            handler=handler,
            arguments_model=PathPairArguments,
        )
    registry.register(
        definition=ToolDefinition(
            name="pki.restore_certificate_material",
            domain="pki",
            description="Restore backed-up material outside Certbot-managed paths.",
        ),
        handler=tools.restore_certificate_material,
        arguments_model=RestoreCertificateMaterialArguments,
    )
