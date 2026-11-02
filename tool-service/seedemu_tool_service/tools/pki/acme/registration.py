"""Registry bindings for ACME certificate lifecycle tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.acme.models import (
    DeployACMECertificateToNginxArguments,
    RenewACMECertificateArguments,
    RequestACMECertificateArguments,
    RevokeACMECertificateArguments,
)
from seedemu_tool_service.tools.pki.acme.tools import ACMETools


def register_acme_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register real ACME operations backed by Certbot in emulator nodes."""
    from .inspection import ACMEInspectionTools
    from .inspection_models import (
        InspectACMEReadinessArguments,
        InspectEnvironmentArguments,
        InspectRenewalStatusArguments,
        ListManagedCertificatesArguments,
    )

    inspections = ACMEInspectionTools(backend)
    for name, description, model in (
        (
            "inspect_environment",
            "Inspect node PKI executables and CA bundle availability.",
            InspectEnvironmentArguments,
        ),
        (
            "list_managed_certificates",
            "List existing Certbot certificate lineages without changes.",
            ListManagedCertificatesArguments,
        ),
        (
            "inspect_acme_readiness",
            "Check the selected ACME authenticator and local prerequisites; CA-side challenge success remains unverified.",
            InspectACMEReadinessArguments,
        ),
        (
            "inspect_renewal_status",
            "Inspect saved renewal configuration and scheduler observations.",
            InspectRenewalStatusArguments,
        ),
    ):
        registry.register(
            ToolDefinition(name="pki." + name, domain="pki", description=description),
            getattr(inspections, name),
            model,
        )
    tools = ACMETools(backend)
    registrations = [
        (
            "pki.request_acme_certificate",
            "Request a certificate using HTTP-01 or the configured RFC 2136 DNS-01 plugin.",
            tools.request_acme_certificate,
            RequestACMECertificateArguments,
        ),
        (
            "pki.deploy_acme_certificate_to_nginx",
            "Add an isolated nginx TLS site without replacing the default site or duplicating an existing TLS name.",
            tools.deploy_acme_certificate_to_nginx,
            DeployACMECertificateToNginxArguments,
        ),
        (
            "pki.renew_acme_certificate",
            "Renew a Certbot-managed ACME certificate.",
            tools.renew_acme_certificate,
            RenewACMECertificateArguments,
        ),
        (
            "pki.revoke_acme_certificate",
            "Revoke a certificate through its ACME CA.",
            tools.revoke_acme_certificate,
            RevokeACMECertificateArguments,
        ),
    ]
    for name, description, handler, arguments_model in registrations:
        registry.register(
            ToolDefinition(name=name, domain="pki", description=description),
            handler,
            arguments_model,
        )
