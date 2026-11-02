"""Certificate expiration PKI tool implementations."""

import ssl
import tempfile
import time

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.expiration.models import (
    CertificateExpirationResult,
    CertificateVersionComparisonResult,
    ExpiringCertificateEntry,
    ExpiringCertificatesResult,
)
from seedemu_tool_service.tools.pki.shared.parsing import (
    extract_pem_certificates,
    parse_certificate_fields,
    parse_prefixed_value,
)


class ExpirationTools:
    """Bound-method tools for certificate expiration checks."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def check_certificate_expiration(
        self,
        source: str,
        path: str,
        warning_seconds: int = 0,
    ) -> CertificateExpirationResult:
        """Check whether a certificate is expired or near expiration."""

        command = [
            "openssl",
            "x509",
            "-in",
            path,
            "-noout",
            "-enddate",
            "-checkend",
            str(warning_seconds),
        ]
        result = self._backend.execute(source, command)
        details = result.stdout
        successful = "notAfter=" in details
        expires_within_window = result.exit_code != 0 if successful else None
        expired = expires_within_window if successful and warning_seconds == 0 else None

        return CertificateExpirationResult(
            source=source,
            path=path,
            successful=successful,
            expired=expired,
            expires_within_warning_window=expires_within_window,
            not_after=parse_prefixed_value(details, "notAfter"),
            details=details,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def check_remote_certificate_expiration(
        self,
        source: str,
        target: str,
        port: int = 443,
        server_name: str | None = None,
        warning_seconds: int = 0,
        timeout_seconds: int = 5,
    ) -> CertificateExpirationResult:
        """Check expiration details for a remote TLS service certificate."""

        command = [
            "timeout",
            str(timeout_seconds),
            "openssl",
            "s_client",
            "-connect",
            f"{target}:{port}",
            "-showcerts",
        ]
        if server_name is not None:
            command.extend(["-servername", server_name])
        result = self._backend.execute(source, command)
        details = result.stdout
        certificates = extract_pem_certificates(details)
        not_after = _decode_not_after(certificates[0]) if certificates else None
        successful = result.exit_code == 0 and not_after is not None
        expires_within_window = None
        expired = None
        if successful and not_after is not None:
            seconds_remaining = ssl.cert_time_to_seconds(not_after) - time.time()
            expires_within_window = seconds_remaining <= warning_seconds
            expired = seconds_remaining <= 0
        return CertificateExpirationResult(
            source=source,
            path=f"{target}:{port}",
            successful=successful,
            expired=expired,
            expires_within_warning_window=expires_within_window,
            not_after=not_after,
            details=details,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def list_expiring_certificates(
        self,
        source: str,
        directory_path: str,
        warning_seconds: int = 2_592_000,
        max_depth: int = 1,
    ) -> ExpiringCertificatesResult:
        """Scan a bounded directory for certificates expiring within a window."""

        find_command = [
            "find",
            directory_path,
            "-maxdepth",
            str(max_depth),
            "-type",
            "f",
        ]
        find_result = self._backend.execute(source, find_command)
        scanned_paths = [
            line.strip() for line in find_result.stdout.splitlines() if line.strip()
        ]
        expiring: list[ExpiringCertificateEntry] = []

        for path in scanned_paths:
            result = self._backend.execute(
                source,
                [
                    "openssl",
                    "x509",
                    "-in",
                    path,
                    "-noout",
                    "-enddate",
                    "-checkend",
                    str(warning_seconds),
                ],
            )
            not_after = parse_prefixed_value(result.stdout, "notAfter")
            if not_after is not None and result.exit_code != 0:
                expiring.append(
                    ExpiringCertificateEntry(
                        path=path,
                        expires_within_warning_window=True,
                        not_after=not_after,
                        exit_code=result.exit_code,
                        stderr=result.stderr,
                    )
                )

        return ExpiringCertificatesResult(
            source=source,
            directory_path=directory_path,
            warning_seconds=warning_seconds,
            scanned_paths=scanned_paths,
            expiring_certificates=expiring,
            exit_code=find_result.exit_code,
            stderr=find_result.stderr,
        )

    def compare_certificate_versions(
        self,
        source: str,
        first_path: str,
        second_path: str,
    ) -> CertificateVersionComparisonResult:
        """Compare fingerprints and validity dates between two certificate files."""

        first_result = self._backend.execute(source, _inspection_command(first_path))
        second_result = self._backend.execute(source, _inspection_command(second_path))
        first_fields = parse_certificate_fields(first_result.stdout)
        second_fields = parse_certificate_fields(second_result.stdout)
        first_fp = first_fields.fingerprint_sha256
        second_fp = second_fields.fingerprint_sha256
        return CertificateVersionComparisonResult(
            source=source,
            first_path=first_path,
            second_path=second_path,
            first_fingerprint_sha256=first_fp,
            second_fingerprint_sha256=second_fp,
            same_certificate=(first_fp == second_fp)
            if first_fp is not None and second_fp is not None
            else None,
            first_not_after=first_fields.not_after,
            second_not_after=second_fields.not_after,
            details=f"{first_result.stdout}\n{second_result.stdout}",
            exit_code=second_result.exit_code
            if first_result.exit_code == 0
            else first_result.exit_code,
            stderr=f"{first_result.stderr}\n{second_result.stderr}".strip(),
        )


def _inspection_command(path: str) -> list[str]:
    return [
        "openssl",
        "x509",
        "-in",
        path,
        "-noout",
        "-dates",
        "-fingerprint",
        "-sha256",
    ]


def _decode_not_after(certificate_pem: str) -> str | None:
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem") as certificate_file:
            certificate_file.write(f"{certificate_pem}\n")
            certificate_file.flush()
            decoded = ssl._ssl._test_decode_cert(certificate_file.name)
    except (OSError, ssl.SSLError, ValueError):
        return None
    value = decoded.get("notAfter")
    return value if isinstance(value, str) else None
