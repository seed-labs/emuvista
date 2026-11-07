"""Registry bindings for certificate trust verification PKI tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.trust_verification.models import (
    ExplainVerificationFailureArguments,
    VerifyCertificateAgainstCAArguments,
    VerifyCertificateChainArguments,
    VerifyCertificateWithIntermediatesArguments,
    VerifyRemoteTLSChainArguments,
)
from seedemu_tool_service.tools.pki.trust_verification.tools import TrustVerificationTools


def register_trust_verification_tools(
    registry: ToolRegistry,
    backend: RuntimeBackend,
) -> None:
    """Register certificate trust verification tools."""

    from .status import CertificateStatusTools, CheckCertificateStatusArguments

    registry.register(
        ToolDefinition(
            name="pki.check_certificate_status",
            domain="pki",
            description="Check leaf revocation using an explicit CRL; unknown on failure.",
        ),
        CertificateStatusTools(backend).check_certificate_status,
        CheckCertificateStatusArguments,
    )
    tools = TrustVerificationTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.verify_certificate_chain",
            domain="pki",
            description="Verify a certificate chain against trusted CA material.",
        ),
        handler=tools.verify_certificate_chain,
        arguments_model=VerifyCertificateChainArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.verify_remote_tls_chain",
            domain="pki",
            description="Connect to a remote TLS service and verify its certificate chain.",
        ),
        handler=tools.verify_remote_tls_chain,
        arguments_model=VerifyRemoteTLSChainArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.verify_certificate_against_ca",
            domain="pki",
            description="Verify a certificate against a single CA certificate file.",
        ),
        handler=tools.verify_certificate_against_ca,
        arguments_model=VerifyCertificateAgainstCAArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.verify_certificate_with_intermediates",
            domain="pki",
            description="Verify a certificate with supplied intermediate certificates.",
        ),
        handler=tools.verify_certificate_with_intermediates,
        arguments_model=VerifyCertificateWithIntermediatesArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.explain_verification_failure",
            domain="pki",
            description="Normalize common OpenSSL verification errors.",
        ),
        handler=tools.explain_verification_failure,
        arguments_model=ExplainVerificationFailureArguments,
    )
