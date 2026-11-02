"""Remote TLS PKI tool implementations."""

import re

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.remote_tls.models import (
    RemoteTLSCertificateInspectionResult,
    RemoteTLSChainInspectionResult,
    TLSCipherCheckResult,
    TLSHandshakeFields,
    TLSHandshakeInspectionResult,
    TLSHostnameCheckResult,
    TLSProtocolCheck,
    TLSProtocolsCheckResult,
)
from seedemu_tool_service.tools.pki.shared.parsing import (
    extract_pem_certificates,
    parse_certificate_fields,
    parse_openssl_error_category,
)


class RemoteTLSTools:
    """Bound-method tools for inspecting remote TLS services."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def inspect_remote_tls_certificate(
        self,
        source: str,
        target: str,
        port: int = 443,
        server_name: str | None = None,
        timeout_seconds: int = 5,
    ) -> RemoteTLSCertificateInspectionResult:
        """Inspect the certificate presented by a remote TLS service."""

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
        return RemoteTLSCertificateInspectionResult(
            source=source,
            target=target,
            port=port,
            server_name=server_name,
            successful=result.exit_code == 0,
            certificate=parse_certificate_fields(details),
            details=details,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def inspect_remote_tls_chain(
        self,
        source: str,
        target: str,
        port: int = 443,
        server_name: str | None = None,
        timeout_seconds: int = 5,
    ) -> RemoteTLSChainInspectionResult:
        """Inspect every certificate presented by a remote TLS service."""

        command = _s_client_command(
            target=target,
            port=port,
            server_name=server_name,
            timeout_seconds=timeout_seconds,
            showcerts=True,
        )
        result = self._backend.execute(source, command)
        certificates = extract_pem_certificates(result.stdout)
        return RemoteTLSChainInspectionResult(
            source=source,
            target=target,
            port=port,
            server_name=server_name,
            successful=result.exit_code == 0,
            certificates_pem=certificates,
            certificate_count=len(certificates),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def inspect_tls_handshake(
        self,
        source: str,
        target: str,
        port: int = 443,
        server_name: str | None = None,
        timeout_seconds: int = 5,
    ) -> TLSHandshakeInspectionResult:
        """Inspect negotiated TLS handshake details."""

        command = _s_client_command(
            target=target,
            port=port,
            server_name=server_name,
            timeout_seconds=timeout_seconds,
            showcerts=False,
        )
        result = self._backend.execute(source, command)
        protocol, cipher = _parse_negotiated_tls(result.stdout)
        return TLSHandshakeInspectionResult(
            source=source,
            target=target,
            port=port,
            server_name=server_name,
            successful=result.exit_code == 0,
            handshake=TLSHandshakeFields(
                protocol=protocol,
                cipher=cipher,
                verify_return_code=_parse_colon_value(result.stdout, "Verify return code"),
            ),
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def check_tls_hostname(
        self,
        source: str,
        target: str,
        expected_hostname: str,
        port: int = 443,
        server_name: str | None = None,
        ca_file_path: str | None = None,
        ca_directory_path: str | None = None,
        timeout_seconds: int = 5,
    ) -> TLSHostnameCheckResult:
        """Check whether a TLS service certificate matches a hostname."""

        effective_server_name = server_name or expected_hostname
        command = _s_client_command(
            target=target,
            port=port,
            server_name=effective_server_name,
            timeout_seconds=timeout_seconds,
            showcerts=True,
        )
        if ca_file_path is not None:
            command.extend(["-CAfile", ca_file_path])
        if ca_directory_path is not None:
            command.extend(["-CApath", ca_directory_path])
        command.extend(["-verify_hostname", expected_hostname, "-verify_return_error"])
        result = self._backend.execute(source, command)
        details = result.stdout
        verify_value = _parse_colon_value(details, "Verify return code")
        verification_ok = verify_value is not None and verify_value.startswith("0 ")
        error_category = (
            None
            if verification_ok
            else parse_openssl_error_category(details, result.stderr)
        )
        trusted = verification_ok or error_category == "hostname_mismatch"
        if verification_ok or "Verified peername:" in details:
            matched: bool | None = True
        elif error_category == "hostname_mismatch":
            matched = False
        else:
            matched = None
        return TLSHostnameCheckResult(
            source=source,
            target=target,
            port=port,
            expected_hostname=expected_hostname,
            server_name=effective_server_name,
            matched=matched,
            trusted=trusted,
            verification_error_category=error_category,
            details=details,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    def check_tls_protocols(
        self,
        source: str,
        target: str,
        port: int = 443,
        server_name: str | None = None,
        protocols: list[str] | None = None,
        timeout_seconds: int = 5,
    ) -> TLSProtocolsCheckResult:
        """Check which TLS protocol versions a service accepts."""

        tested_protocols = protocols or ["tls1_2", "tls1_3"]
        checks: list[TLSProtocolCheck] = []
        for protocol in tested_protocols:
            command = _s_client_command(
                target=target,
                port=port,
                server_name=server_name,
                timeout_seconds=timeout_seconds,
                showcerts=False,
            )
            command.append(f"-{protocol}")
            result = self._backend.execute(source, command)
            checks.append(
                TLSProtocolCheck(
                    protocol=protocol,
                    accepted=result.exit_code == 0,
                    exit_code=result.exit_code,
                    stderr=result.stderr,
                )
            )

        return TLSProtocolsCheckResult(
            source=source,
            target=target,
            port=port,
            server_name=server_name,
            results=checks,
        )

    def check_tls_cipher(
        self,
        source: str,
        target: str,
        cipher: str,
        port: int = 443,
        server_name: str | None = None,
        timeout_seconds: int = 5,
    ) -> TLSCipherCheckResult:
        """Check whether a TLS service accepts or negotiates a cipher."""

        command = _s_client_command(
            target=target,
            port=port,
            server_name=server_name,
            timeout_seconds=timeout_seconds,
            showcerts=False,
        )
        command.extend(["-cipher", cipher])
        result = self._backend.execute(source, command)
        _, negotiated_cipher = _parse_negotiated_tls(result.stdout)
        return TLSCipherCheckResult(
            source=source,
            target=target,
            port=port,
            server_name=server_name,
            cipher=cipher,
            accepted=result.exit_code == 0 and negotiated_cipher == cipher,
            negotiated_cipher=negotiated_cipher,
            details=result.stdout,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )


def _s_client_command(
    target: str,
    port: int,
    server_name: str | None,
    timeout_seconds: int,
    showcerts: bool,
) -> list[str]:
    command = [
        "timeout",
        str(timeout_seconds),
        "openssl",
        "s_client",
        "-connect",
        f"{target}:{port}",
    ]
    if showcerts:
        command.append("-showcerts")
    if server_name is not None:
        command.extend(["-servername", server_name])
    return command


def _parse_colon_value(output: str, key: str) -> str | None:
    for line in output.splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        label, value = stripped.split(":", 1)
        if label.strip().lower() == key.lower():
            return value.strip()
    return None


def _parse_negotiated_tls(output: str) -> tuple[str | None, str | None]:
    protocol = _parse_colon_value(output, "Protocol")
    cipher = _parse_colon_value(output, "Cipher")
    if protocol is not None and cipher is not None:
        return protocol, cipher

    match = re.search(r"^New,\s*([^,]+),\s*Cipher is\s*(\S+)", output, re.MULTILINE)
    if match is None:
        return protocol, cipher
    return protocol or match.group(1).strip(), cipher or match.group(2).strip()
