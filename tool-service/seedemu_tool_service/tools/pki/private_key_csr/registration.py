"""Registry bindings for private-key and CSR PKI tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.private_key_csr.models import (
    InspectCSRArguments,
    InspectPrivateKeyArguments,
    VerifyPrivateKeyMatchesCertificateArguments,
)
from seedemu_tool_service.tools.pki.private_key_csr.tools import PrivateKeyCSRTools


def register_private_key_csr_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register private-key and CSR tools."""

    tools = PrivateKeyCSRTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_private_key",
            domain="pki",
            description="Inspect private-key metadata without returning key material.",
        ),
        handler=tools.inspect_private_key,
        arguments_model=InspectPrivateKeyArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.verify_private_key_matches_certificate",
            domain="pki",
            description="Check whether a private key corresponds to a certificate.",
        ),
        handler=tools.verify_private_key_matches_certificate,
        arguments_model=VerifyPrivateKeyMatchesCertificateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_csr",
            domain="pki",
            description="Inspect subject, SANs, public key, and extensions requested by a CSR.",
        ),
        handler=tools.inspect_csr,
        arguments_model=InspectCSRArguments,
    )
