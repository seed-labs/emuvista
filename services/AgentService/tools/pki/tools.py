"""Compatibility aggregate for PKI-domain tool implementations."""

from .acme.inspection import ACMEInspectionTools
from .acme.tools import ACMETools
from .ca_service.tools import CAServiceTools
from .certificate_inspection.tools import (
    CertificateInspectionTools,
)
from .expiration.tools import ExpirationTools
from .installation.tools import InstallationTools
from .private_key_csr.tools import PrivateKeyCSRTools
from .remote_tls.tools import RemoteTLSTools
from .remote_tls.verification import TLSVerificationTools
from .trust_store.tools import TrustStoreTools
from .trust_verification.status import CertificateStatusTools
from .trust_verification.tools import TrustVerificationTools


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
