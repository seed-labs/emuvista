"""Verification from the caller's node; never controls the destination node."""

from pathlib import Path

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.shared.runtime import NodeObservation, observe


class TLSVerificationTools:
    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def verify_tls_deployment(
        self,
        source: str,
        target: str,
        expected_hostname: str,
        expected_fingerprint_sha256: str,
        ca_file_path: str,
        port: int,
        timeout_seconds: int,
    ) -> NodeObservation:
        return self._verify(
            "deployment",
            source,
            target=target,
            expected_hostname=expected_hostname,
            expected_fingerprint_sha256=expected_fingerprint_sha256,
            ca_file_path=ca_file_path,
            port=port,
            timeout_seconds=timeout_seconds,
        )

    def test_mtls_connection(
        self,
        source: str,
        target: str,
        expected_hostname: str,
        client_certificate_path: str,
        client_private_key_path: str,
        ca_file_path: str,
        port: int,
        timeout_seconds: int,
    ) -> NodeObservation:
        return self._verify(
            "mtls",
            source,
            target=target,
            expected_hostname=expected_hostname,
            client_certificate_path=client_certificate_path,
            client_private_key_path=client_private_key_path,
            ca_file_path=ca_file_path,
            port=port,
            timeout_seconds=timeout_seconds,
        )

    def _verify(self, action: str, source: str, **arguments: object) -> NodeObservation:
        return observe(
            self._backend,
            source,
            Path(__file__).with_name("verification_probe.py"),
            {"action": action, **arguments},
        )
