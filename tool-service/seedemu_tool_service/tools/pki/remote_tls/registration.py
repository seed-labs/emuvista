"""Registry bindings for remote TLS PKI tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.remote_tls.models import (
    CheckTLSCipherArguments,
    CheckTLSHostnameArguments,
    CheckTLSProtocolsArguments,
    InspectRemoteTLSCertificateArguments,
    InspectRemoteTLSChainArguments,
    InspectTLSHandshakeArguments,
)
from seedemu_tool_service.tools.pki.remote_tls.tools import RemoteTLSTools
from seedemu_tool_service.tools.pki.remote_tls.verification import TLSVerificationTools
from seedemu_tool_service.tools.pki.remote_tls.verification_models import (
    TestMTLSConnectionArguments,
    VerifyTLSDeploymentArguments,
)


def register_remote_tls_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register remote TLS inspection tools."""

    verification = TLSVerificationTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.verify_tls_deployment",
            domain="pki",
            description="Verify remote TLS trust, hostname and expected SHA-256 fingerprint.",
        ),
        handler=verification.verify_tls_deployment,
        arguments_model=VerifyTLSDeploymentArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.test_mtls_connection",
            domain="pki",
            description="Compare HTTPS HEAD requests with and without a client certificate.",
        ),
        handler=verification.test_mtls_connection,
        arguments_model=TestMTLSConnectionArguments,
    )
    tools = RemoteTLSTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_remote_tls_certificate",
            domain="pki",
            description="Inspect the certificate presented by a remote TLS service.",
        ),
        handler=tools.inspect_remote_tls_certificate,
        arguments_model=InspectRemoteTLSCertificateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_remote_tls_chain",
            domain="pki",
            description="Inspect every certificate presented by a remote TLS service.",
        ),
        handler=tools.inspect_remote_tls_chain,
        arguments_model=InspectRemoteTLSChainArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_tls_handshake",
            domain="pki",
            description="Inspect negotiated TLS version, cipher, and verification status.",
        ),
        handler=tools.inspect_tls_handshake,
        arguments_model=InspectTLSHandshakeArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.check_tls_hostname",
            domain="pki",
            description="Check whether a remote TLS certificate matches a hostname.",
        ),
        handler=tools.check_tls_hostname,
        arguments_model=CheckTLSHostnameArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.check_tls_protocols",
            domain="pki",
            description="Check which TLS protocol versions are accepted by a service.",
        ),
        handler=tools.check_tls_protocols,
        arguments_model=CheckTLSProtocolsArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.check_tls_cipher",
            domain="pki",
            description="Check whether a TLS service accepts or negotiates a cipher.",
        ),
        handler=tools.check_tls_cipher,
        arguments_model=CheckTLSCipherArguments,
    )
