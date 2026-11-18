"""Registry bindings for certificate expiration PKI tools."""

from ..execution import RuntimeBackend
from ..catalog import ToolDefinition
from ..catalog import Catalog
from ..expiration.models import (
    CheckCertificateExpirationArguments,
    CheckRemoteCertificateExpirationArguments,
    CompareCertificateVersionsArguments,
    ListExpiringCertificatesArguments,
)
from ..expiration.tools import ExpirationTools


def register_expiration_tools(registry: Catalog, backend: RuntimeBackend) -> None:
    """Register certificate expiration tools."""

    tools = ExpirationTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.check_certificate_expiration",
            domain="pki",
            description="Check whether a certificate is expired or near expiration.",
        ),
        handler=tools.check_certificate_expiration,
        arguments_model=CheckCertificateExpirationArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.check_remote_certificate_expiration",
            domain="pki",
            description="Check expiration for a certificate presented by a TLS service.",
        ),
        handler=tools.check_remote_certificate_expiration,
        arguments_model=CheckRemoteCertificateExpirationArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.list_expiring_certificates",
            domain="pki",
            description="Scan a bounded directory for certificates expiring within a window.",
        ),
        handler=tools.list_expiring_certificates,
        arguments_model=ListExpiringCertificatesArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.compare_certificate_versions",
            domain="pki",
            description="Compare fingerprints and validity dates for two certificates.",
        ),
        handler=tools.compare_certificate_versions,
        arguments_model=CompareCertificateVersionsArguments,
    )
