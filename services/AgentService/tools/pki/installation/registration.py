"""Registry bindings for certificate installation PKI tools."""

from ..execution import RuntimeBackend
from ..catalog import ToolDefinition
from ..catalog import Catalog
from ..installation.models import (
    BackupCertificateMaterialArguments,
    PathPairArguments,
    RestoreCertificateMaterialArguments,
)
from ..installation.tools import InstallationTools


def register_installation_tools(registry: Catalog, backend: RuntimeBackend) -> None:
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
    registry.register(
        definition=ToolDefinition(
            name="pki.install_certificate",
            domain="pki",
            description="Install a certificate outside Certbot-managed paths.",
        ),
        handler=tools.install_certificate,
        arguments_model=PathPairArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.install_private_key",
            domain="pki",
            description=(
                "Install an application private key outside Certbot-managed paths "
                "with restrictive permissions."
            ),
        ),
        handler=tools.install_private_key,
        arguments_model=PathPairArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.install_certificate_chain",
            domain="pki",
            description="Install a certificate chain bundle outside Certbot-managed paths.",
        ),
        handler=tools.install_certificate_chain,
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
