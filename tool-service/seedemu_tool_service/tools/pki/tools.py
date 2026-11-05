"""Compatibility aggregate for PKI-domain tool implementations."""

from seedemu_tool_service.tools.pki.acme.inspection import ACMEInspectionTools
from seedemu_tool_service.tools.pki.acme.tools import ACMETools
from seedemu_tool_service.tools.pki.ca_service.tools import CAServiceTools
from seedemu_tool_service.tools.pki.certificate_inspection.tools import (
    CertificateInspectionTools,
)
from seedemu_tool_service.tools.pki.expiration.tools import ExpirationTools
from seedemu_tool_service.tools.pki.installation.tools import InstallationTools
from seedemu_tool_service.tools.pki.private_key_csr.tools import PrivateKeyCSRTools
from seedemu_tool_service.tools.pki.remote_tls.tools import RemoteTLSTools
from seedemu_tool_service.tools.pki.remote_tls.verification import TLSVerificationTools
from seedemu_tool_service.tools.pki.trust_store.tools import TrustStoreTools
from seedemu_tool_service.tools.pki.trust_verification.status import CertificateStatusTools
from seedemu_tool_service.tools.pki.trust_verification.tools import TrustVerificationTools


class PKITools(
    ACMETools,
    ACMEInspectionTools,
    CAServiceTools,
    TLSVerificationTools,
    CertificateStatusTools,
    CertificateInspectionTools,
    RemoteTLSTools,
    TrustVerificationTools,
    ExpirationTools,
    PrivateKeyCSRTools,
    InstallationTools,
    TrustStoreTools,
):
    """Backward-compatible aggregate of implemented PKI tool categories."""


__all__ = [
    "ACMETools",
    "CertificateInspectionTools",
    "ExpirationTools",
    "InstallationTools",
    "PKITools",
    "PrivateKeyCSRTools",
    "RemoteTLSTools",
    "TrustStoreTools",
    "TrustVerificationTools",
]
