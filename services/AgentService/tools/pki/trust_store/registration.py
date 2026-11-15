"""Registry bindings for trust-store PKI tools."""

from ..execution import RuntimeBackend
from ..catalog import ToolDefinition
from ..catalog import Catalog
from ..trust_store.models import (
    CheckCAInstalledArguments,
    InspectTrustStoreArguments,
    RemoveCACertificateArguments,
    UpdateTrustStoreArguments,
)
from ..trust_store.tools import TrustStoreTools


def register_trust_store_tools(registry: Catalog, backend: RuntimeBackend) -> None:
    """Register trust-store tools."""

    tools = TrustStoreTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_trust_store",
            domain="pki",
            description="Inspect trust-store material.",
        ),
        handler=tools.inspect_trust_store,
        arguments_model=InspectTrustStoreArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.check_ca_installed",
            domain="pki",
            description="Check whether a CA certificate is trusted.",
        ),
        handler=tools.check_ca_installed,
        arguments_model=CheckCAInstalledArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.remove_ca_certificate",
            domain="pki",
            description=(
                "Remove a fingerprint-pinned CA certificate from the SEEDEmu trust-store "
                "directory, then refresh trust."
            ),
        ),
        handler=tools.remove_ca_certificate,
        arguments_model=RemoveCACertificateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.update_trust_store",
            domain="pki",
            description="Run the fixed update-ca-certificates command.",
        ),
        handler=tools.update_trust_store,
        arguments_model=UpdateTrustStoreArguments,
    )
