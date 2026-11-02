"""Private-key and CSR PKI tool implementations."""

import hashlib

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.private_key_csr.models import (
    CSRGenerationResult,
    CSRInspectionResult,
    PrivateKeyGenerationResult,
    PrivateKeyInspectionResult,
    PrivateKeyMatchResult,
)
from seedemu_tool_service.tools.pki.shared.parsing import (
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

    def generate_private_key(
        self,
        source: str,
        output_path: str,
        algorithm: str = "RSA",
        bits: int = 2048,
        curve: str = "prime256v1",
        overwrite: bool = False,
    ) -> PrivateKeyGenerationResult:
        """Generate a private key at an explicit output path."""

        if not overwrite:
            preflight = self._backend.execute(source, ["test", "!", "-e", output_path])
            if preflight.exit_code != 0:
                return PrivateKeyGenerationResult(
                    source=source,
                    output_path=output_path,
                    algorithm=algorithm,
                    bits=bits if algorithm == "RSA" else None,
                    curve=curve if algorithm == "EC" else None,
                    created_paths=[],
                    overwritten_paths=[],
                    successful=False,
                    exit_code=preflight.exit_code,
                    stderr=preflight.stderr or "output path already exists",
                )

        command = ["openssl", "genpkey", "-out", output_path]
        if algorithm == "RSA":
            command.extend(["-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{bits}"])
        else:
            command.extend(["-algorithm", "EC", "-pkeyopt", f"ec_paramgen_curve:{curve}"])
        result = self._backend.execute(source, command)
        chmod_result = self._backend.execute(source, ["chmod", "600", output_path])
        exit_code = result.exit_code if result.exit_code != 0 else chmod_result.exit_code
        return PrivateKeyGenerationResult(
            source=source,
            output_path=output_path,
            algorithm=algorithm,
            bits=bits if algorithm == "RSA" else None,
            curve=curve if algorithm == "EC" else None,
            created_paths=[output_path] if exit_code == 0 and not overwrite else [],
            overwritten_paths=[output_path] if exit_code == 0 and overwrite else [],
            successful=exit_code == 0,
            exit_code=exit_code,
            stderr=f"{result.stderr}\n{chmod_result.stderr}".strip(),
        )

    def generate_csr(
        self,
        source: str,
        key_path: str,
        output_path: str,
        subject: str,
        subject_alt_names: list[str] | None = None,
        overwrite: bool = False,
    ) -> CSRGenerationResult:
        """Generate a CSR from a private key and requested identity."""

        if not overwrite:
            preflight = self._backend.execute(source, ["test", "!", "-e", output_path])
            if preflight.exit_code != 0:
                return CSRGenerationResult(
                    source=source,
                    key_path=key_path,
                    output_path=output_path,
                    created_paths=[],
                    overwritten_paths=[],
                    successful=False,
                    exit_code=preflight.exit_code,
                    stderr=preflight.stderr or "output path already exists",
                )

        command = [
            "openssl",
            "req",
            "-new",
            "-key",
            key_path,
            "-out",
            output_path,
            "-subj",
            subject,
        ]
        if subject_alt_names:
            command.extend(["-addext", f"subjectAltName={','.join(subject_alt_names)}"])
        result = self._backend.execute(source, command)
        return CSRGenerationResult(
            source=source,
            key_path=key_path,
            output_path=output_path,
            created_paths=[output_path] if result.exit_code == 0 and not overwrite else [],
            overwritten_paths=[output_path] if result.exit_code == 0 and overwrite else [],
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
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
