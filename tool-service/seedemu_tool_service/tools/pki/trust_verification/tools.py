"""Certificate trust verification PKI tool implementations."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.shared.parsing import parse_openssl_error_category
from seedemu_tool_service.tools.pki.trust_verification.models import (
    CertificateChainVerificationResult,
    RemoteTLSChainVerificationResult,
    VerificationFailureExplanationResult,
)


class TrustVerificationTools:
    """Bound-method tools for certificate trust verification."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def verify_certificate_chain(
        self,
        source: str,
        certificate_path: str,
        ca_file_path: str | None = None,
        ca_directory_path: str | None = None,
        untrusted_chain_path: str | None = None,
    ) -> CertificateChainVerificationResult:
        """Verify a certificate against CA material inside an emulated node."""

        command = ["openssl", "verify"]
        if ca_file_path is not None:
            command.extend(["-CAfile", ca_file_path])
        if ca_directory_path is not None:
            command.extend(["-CApath", ca_directory_path])
        if untrusted_chain_path is not None:
            command.extend(["-untrusted", untrusted_chain_path])
        command.append(certificate_path)

        result = self._backend.execute(source, command)
        return CertificateChainVerificationResult(
            source=source,
            certificate_path=certificate_path,
            ca_file_path=ca_file_path,
            ca_directory_path=ca_directory_path,
            untrusted_chain_path=untrusted_chain_path,
            trusted=result.exit_code == 0,
            output=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def verify_remote_tls_chain(
        self,
        source: str,
        target: str,
        port: int = 443,
        server_name: str | None = None,
        ca_file_path: str | None = None,
        ca_directory_path: str | None = None,
        timeout_seconds: int = 5,
    ) -> RemoteTLSChainVerificationResult:
        """Verify a remote TLS service chain from an emulated node."""

        command = [
            "timeout",
            str(timeout_seconds),
            "openssl",
            "s_client",
            "-connect",
            f"{target}:{port}",
            "-verify_return_error",
        ]
        if server_name is not None:
            command.extend(["-servername", server_name])
        if ca_file_path is not None:
            command.extend(["-CAfile", ca_file_path])
        if ca_directory_path is not None:
            command.extend(["-CApath", ca_directory_path])

        result = self._backend.execute(source, command)
        return RemoteTLSChainVerificationResult(
            source=source,
            target=target,
            port=port,
            server_name=server_name,
            ca_file_path=ca_file_path,
            ca_directory_path=ca_directory_path,
            trusted=result.exit_code == 0,
            output=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def verify_certificate_against_ca(
        self,
        source: str,
        certificate_path: str,
        ca_file_path: str,
    ) -> CertificateChainVerificationResult:
        """Verify a certificate against one CA file."""

        return self.verify_certificate_chain(
            source=source,
            certificate_path=certificate_path,
            ca_file_path=ca_file_path,
        )

    def verify_certificate_with_intermediates(
        self,
        source: str,
        certificate_path: str,
        ca_file_path: str,
        intermediate_chain_path: str,
    ) -> CertificateChainVerificationResult:
        """Verify a certificate using supplied intermediate certificates."""

        return self.verify_certificate_chain(
            source=source,
            certificate_path=certificate_path,
            ca_file_path=ca_file_path,
            untrusted_chain_path=intermediate_chain_path,
        )

    def explain_verification_failure(
        self,
        output: str = "",
        stderr: str = "",
    ) -> VerificationFailureExplanationResult:
        """Normalize common OpenSSL verification failures."""

        return VerificationFailureExplanationResult(
            category=parse_openssl_error_category(output, stderr),
            output=output,
            stderr=stderr,
        )
