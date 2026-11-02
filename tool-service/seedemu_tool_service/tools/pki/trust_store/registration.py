"""Registry bindings for trust-store PKI tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.pki.trust_store.models import (
    CheckCAInstalledArguments,
    InspectTrustStoreArguments,
    RemoveCACertificateArguments,
    UpdateTrustStoreArguments,
)
from seedemu_tool_service.tools.pki.trust_store.tools import TrustStoreTools


def register_trust_store_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Register trust-store tools."""

    tools = TrustStoreTools(backend)
    registrations = [
        (
            "pki.inspect_trust_store",
            "Inspect trust-store material.",
            tools.inspect_trust_store,
            InspectTrustStoreArguments,
        ),
        (
            "pki.check_ca_installed",
            "Check whether a CA certificate is trusted.",
            tools.check_ca_installed,
            CheckCAInstalledArguments,
        ),
        (
            "pki.remove_ca_certificate",
            "Remove a fingerprint-pinned CA certificate from the SEEDEmu trust-store directory, then refresh trust.",
            tools.remove_ca_certificate,
            RemoveCACertificateArguments,
        ),
        (
            "pki.update_trust_store",
            "Run the fixed update-ca-certificates command.",
            tools.update_trust_store,
            UpdateTrustStoreArguments,
        ),
    ]
    for name, description, handler, arguments_model in registrations:
        registry.register(
            definition=ToolDefinition(name=name, domain="pki", description=description),
            handler=handler,
            arguments_model=arguments_model,
        )
