"""Registry bindings for certificate inspection PKI tools."""

from ..execution import RuntimeBackend
from ..catalog import ToolDefinition
from ..catalog import Catalog
from ..certificate_inspection.models import (
    GetCertificateFingerprintArguments,
    InspectCertificateExtensionsArguments,
    InspectCertificateFileArguments,
    InspectCertificateNamesArguments,
    InspectCertificatePublicKeyArguments,
)
from ..certificate_inspection.tools import (
    CertificateInspectionTools,
)


def register_certificate_inspection_tools(
    registry: Catalog,
    backend: RuntimeBackend,
) -> None:
    """Register certificate inspection tools."""

    tools = CertificateInspectionTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_certificate_file",
            domain="pki",
            description="Inspect an X.509 certificate file inside an emulated node.",
        ),
        handler=tools.inspect_certificate_file,
        arguments_model=InspectCertificateFileArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_certificate_names",
            domain="pki",
            description="Inspect certificate subject and subject alternative names.",
        ),
        handler=tools.inspect_certificate_names,
        arguments_model=InspectCertificateNamesArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_certificate_extensions",
            domain="pki",
            description="Inspect common X.509 certificate extensions.",
        ),
        handler=tools.inspect_certificate_extensions,
        arguments_model=InspectCertificateExtensionsArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.inspect_certificate_public_key",
            domain="pki",
            description="Inspect the public key embedded in a certificate.",
        ),
        handler=tools.inspect_certificate_public_key,
        arguments_model=InspectCertificatePublicKeyArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="pki.get_certificate_fingerprint",
            domain="pki",
            description="Return a certificate fingerprint using a selected digest.",
        ),
        handler=tools.get_certificate_fingerprint,
        arguments_model=GetCertificateFingerprintArguments,
    )
