"""Registry bindings for ACME certificate lifecycle tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.acme.inspection import ACMEInspectionTools
from seedemu_tool_service.tools.pki.acme.inspection_models import (
    InspectACMEReadinessArguments,
    InspectEnvironmentArguments,
    InspectRenewalStatusArguments,
    ListManagedCertificatesArguments,
)
from seedemu_tool_service.tools.pki.acme.models import (
    DeployACMECertificateToNginxArguments,
    RenewACMECertificateArguments,
    RequestACMECertificateArguments,
    RevokeACMECertificateArguments,
)
from seedemu_tool_service.tools.pki.acme.tools import ACMETools


def register_acme_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register real ACME operations backed by Certbot in emulator nodes."""
    inspections = ACMEInspectionTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_environment",
            domain="pki",
            description="Inspect node PKI executables and CA bundle availability.",
        ),
        handler=inspections.inspect_environment,
        arguments_model=InspectEnvironmentArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.list_managed_certificates",
            domain="pki",
            description="List existing Certbot certificate lineages without changes.",
        ),
        handler=inspections.list_managed_certificates,
        arguments_model=ListManagedCertificatesArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_acme_readiness",
            domain="pki",
            description=(
                "Check the selected ACME authenticator and local prerequisites; "
                "CA-side challenge success remains unverified."
            ),
        ),
        handler=inspections.inspect_acme_readiness,
        arguments_model=InspectACMEReadinessArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_renewal_status",
            domain="pki",
            description="Inspect saved renewal configuration and scheduler observations.",
        ),
        handler=inspections.inspect_renewal_status,
        arguments_model=InspectRenewalStatusArguments,
    )
    tools = ACMETools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.request_acme_certificate",
            domain="pki",
            description=(
                "Request a certificate using HTTP-01 or the configured RFC 2136 DNS-01 plugin."
            ),
        ),
        handler=tools.request_acme_certificate,
        arguments_model=RequestACMECertificateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.deploy_acme_certificate_to_nginx",
            domain="pki",
            description=(
                "Add an isolated nginx TLS site without replacing the default site "
                "or duplicating an existing TLS name."
            ),
        ),
        handler=tools.deploy_acme_certificate_to_nginx,
        arguments_model=DeployACMECertificateToNginxArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.renew_acme_certificate",
            domain="pki",
            description="Renew a Certbot-managed ACME certificate.",
        ),
        handler=tools.renew_acme_certificate,
        arguments_model=RenewACMECertificateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.revoke_acme_certificate",
            domain="pki",
            description="Revoke a certificate through its ACME CA.",
        ),
        handler=tools.revoke_acme_certificate,
        arguments_model=RevokeACMECertificateArguments,
    )
