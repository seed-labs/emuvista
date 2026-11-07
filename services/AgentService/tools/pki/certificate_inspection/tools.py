"""Certificate inspection PKI tool implementations."""

from ..execution import RuntimeBackend
from ..certificate_inspection.models import (
    CertificateExtensions,
    CertificateExtensionsResult,
    CertificateFingerprintResult,
    CertificateInspectionResult,
    CertificateNames,
    CertificateNamesResult,
    CertificatePublicKey,
    CertificatePublicKeyResult,
)
from ..shared.parsing import (
    parse_certificate_fields,
    parse_extension_value,
    parse_prefixed_value,
    parse_public_key_algorithm,
    parse_public_key_bits,
    parse_subject_alt_names,
    parse_subject_common_name,
)


class CertificateInspectionTools:
    """Bound-method tools for local certificate inspection."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def inspect_certificate_file(
        self,
        source: str,
        path: str,
    ) -> CertificateInspectionResult:
        """Inspect an X.509 certificate file inside an emulated node."""

        command = [
            "openssl",
            "x509",
            "-in",
            path,
            "-noout",
            "-subject",
            "-issuer",
            "-serial",
            "-dates",
            "-fingerprint",
            "-sha256",
        ]
        result = self._backend.execute(source, command)
        return CertificateInspectionResult(
            source=source,
            path=path,
            successful=result.exit_code == 0,
            certificate=parse_certificate_fields(result.stdout),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def inspect_certificate_names(
        self,
        source: str,
        path: str,
    ) -> CertificateNamesResult:
        """Inspect subject and subjectAltName values for a certificate."""

        command = [
            "openssl",
            "x509",
            "-in",
            path,
            "-noout",
            "-subject",
            "-ext",
            "subjectAltName",
        ]
        result = self._backend.execute(source, command)
        subject = parse_prefixed_value(result.stdout, "subject")
        return CertificateNamesResult(
            source=source,
            path=path,
            successful=result.exit_code == 0,
            names=CertificateNames(
                subject=subject,
                common_name=parse_subject_common_name(subject),
                subject_alt_names=parse_subject_alt_names(result.stdout),
            ),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def inspect_certificate_extensions(
        self,
        source: str,
        path: str,
    ) -> CertificateExtensionsResult:
        """Inspect common X.509 extensions for a certificate."""

        command = [
            "openssl",
            "x509",
            "-in",
            path,
            "-noout",
            "-text",
        ]
        result = self._backend.execute(source, command)
        return CertificateExtensionsResult(
            source=source,
            path=path,
            successful=result.exit_code == 0,
            extensions=CertificateExtensions(
                subject_alt_names=parse_subject_alt_names(result.stdout),
                key_usage=parse_extension_value(result.stdout, "X509v3 Key Usage"),
                extended_key_usage=parse_extension_value(
                    result.stdout,
                    "X509v3 Extended Key Usage",
                ),
                basic_constraints=parse_extension_value(
                    result.stdout,
                    "X509v3 Basic Constraints",
                ),
            ),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def inspect_certificate_public_key(
        self,
        source: str,
        path: str,
    ) -> CertificatePublicKeyResult:
        """Inspect public-key properties embedded in a certificate."""

        command = [
            "openssl",
            "x509",
            "-in",
            path,
            "-noout",
            "-text",
        ]
        result = self._backend.execute(source, command)
        return CertificatePublicKeyResult(
            source=source,
            path=path,
            successful=result.exit_code == 0,
            public_key=CertificatePublicKey(
                algorithm=parse_public_key_algorithm(result.stdout),
                bits=parse_public_key_bits(result.stdout),
            ),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def get_certificate_fingerprint(
        self,
        source: str,
        path: str,
        digest: str = "sha256",
    ) -> CertificateFingerprintResult:
        """Return a certificate fingerprint using the requested digest."""

        command = [
            "openssl",
            "x509",
            "-in",
            path,
            "-noout",
            "-fingerprint",
            f"-{digest}",
        ]
        result = self._backend.execute(source, command)
        return CertificateFingerprintResult(
            source=source,
            path=path,
            digest=digest,
            successful=result.exit_code == 0,
            fingerprint=parse_prefixed_value(result.stdout, f"{digest} Fingerprint"),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )
