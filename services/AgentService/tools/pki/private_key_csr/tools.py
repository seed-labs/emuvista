"""Private-key and CSR PKI tool implementations."""

import hashlib

from ..execution import RuntimeBackend
from ..private_key_csr.models import (
    CSRInspectionResult,
    PrivateKeyInspectionResult,
    PrivateKeyMatchResult,
)
from ..shared.parsing import (
    parse_prefixed_value,
    parse_public_key_algorithm,
    parse_public_key_bits,
    parse_subject_alt_names,
)


class PrivateKeyCSRTools:
    """Bound-method tools for private-key and CSR workflows."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def inspect_private_key(self, source: str, key_path: str) -> PrivateKeyInspectionResult:
        """Inspect private-key metadata without returning key material."""

        result = self._backend.execute(
            source,
            ["openssl", "pkey", "-in", key_path, "-noout", "-text_pub"],
        )
        return PrivateKeyInspectionResult(
            source=source,
            key_path=key_path,
            successful=result.exit_code == 0,
            algorithm=parse_public_key_algorithm(result.stdout),
            bits=parse_public_key_bits(result.stdout),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def verify_private_key_matches_certificate(
        self,
        source: str,
        key_path: str,
        certificate_path: str,
    ) -> PrivateKeyMatchResult:
        """Check whether a private key corresponds to a certificate."""

        key_result = self._backend.execute(
            source,
            ["openssl", "pkey", "-in", key_path, "-pubout", "-outform", "PEM"],
        )
        cert_result = self._backend.execute(
            source,
            ["openssl", "x509", "-in", certificate_path, "-noout", "-pubkey"],
        )
        key_hash = _sha256_text(key_result.stdout) if key_result.exit_code == 0 else None
        cert_hash = _sha256_text(cert_result.stdout) if cert_result.exit_code == 0 else None
        return PrivateKeyMatchResult(
            source=source,
            key_path=key_path,
            certificate_path=certificate_path,
            matches=key_hash is not None and key_hash == cert_hash,
            key_public_hash=key_hash,
            certificate_public_hash=cert_hash,
            exit_code=cert_result.exit_code if key_result.exit_code == 0 else key_result.exit_code,
            stderr=f"{key_result.stderr}\n{cert_result.stderr}".strip(),
        )

    def inspect_csr(self, source: str, csr_path: str) -> CSRInspectionResult:
        """Inspect a CSR subject, requested SANs, and raw text."""

        result = self._backend.execute(
            source,
            ["openssl", "req", "-in", csr_path, "-noout", "-text"],
        )
        return CSRInspectionResult(
            source=source,
            csr_path=csr_path,
            successful=result.exit_code == 0,
            subject=parse_prefixed_value(result.stdout, "Subject"),
            subject_alt_names=parse_subject_alt_names(result.stdout),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
