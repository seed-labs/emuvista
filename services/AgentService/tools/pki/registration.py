"""Registration entry point for PKI-domain tools."""

from .execution import RuntimeBackend
from .catalog import Catalog
from .acme import register_acme_tools
from .ca_service import register_ca_service_tools
from .certificate_inspection import (
    register_certificate_inspection_tools,
)
from .expiration import register_expiration_tools
from .installation import register_installation_tools
from .private_key_csr import register_private_key_csr_tools
from .remote_tls import register_remote_tls_tools
from .trust_store import register_trust_store_tools
from .trust_verification import (
    register_trust_verification_tools,
)


def register_pki_tools(registry: Catalog, backend: RuntimeBackend) -> None:
    """Register all implemented PKI tool categories."""

    register_certificate_inspection_tools(registry, backend)
    register_acme_tools(registry, backend)
    register_ca_service_tools(registry, backend)
    register_remote_tls_tools(registry, backend)
    register_trust_verification_tools(registry, backend)
    register_expiration_tools(registry, backend)
    register_private_key_csr_tools(registry, backend)
    register_installation_tools(registry, backend)
    register_trust_store_tools(registry, backend)
