"""PKI-domain tool tests."""

from collections.abc import Sequence

import anyio

from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from seedemu_tool_service.tools.pki import register_pki_tools
from tests.registry_support import ToolRegistry


class FakeRuntimeBackend:
    def __init__(self, result: RuntimeCommandResult | None = None) -> None:
        self.result = result or RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "subject=CN=example.test\n"
                "issuer=CN=Example CA\n"
                "serial=01\n"
                "notBefore=Aug 20 00:00:00 2026 GMT\n"
                "notAfter=Aug 20 00:00:00 2027 GMT\n"
                "sha256 Fingerprint=AA:BB:CC\n"
            ),
            stderr="",
        )
        self.container: str | None = None
        self.command: list[str] | None = None
        self.commands: list[list[str]] = []

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.command = list(command)
        self.commands.append(list(command))
        return self.result


class QueueRuntimeBackend(FakeRuntimeBackend):
    def __init__(self, results: list[RuntimeCommandResult]) -> None:
        super().__init__(results[0] if results else None)
        self.results = results

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.command = list(command)
        self.commands.append(list(command))
        return self.results.pop(0)


def test_pki_domain_registers_certificate_tool() -> None:
    registry = ToolRegistry()

    register_pki_tools(registry, FakeRuntimeBackend())

    definitions = registry.list_tools()
    assert [tool.name for tool in definitions] == sorted(
        [
            "pki.inspect_environment",
            "pki.list_managed_certificates",
            "pki.inspect_acme_readiness",
            "pki.inspect_renewal_status",
            "pki.verify_tls_deployment",
            "pki.test_mtls_connection",
            "pki.check_certificate_status",
            "pki.inspect_ca_service",
            "pki.inspect_ca_events",
            "pki.backup_certificate_material",
            "pki.check_ca_installed",
            "pki.check_certificate_expiration",
            "pki.check_remote_certificate_expiration",
            "pki.check_tls_cipher",
            "pki.check_tls_hostname",
            "pki.check_tls_protocols",
            "pki.compare_certificate_versions",
            "pki.deploy_acme_certificate_to_nginx",
            "pki.explain_verification_failure",
            "pki.get_certificate_fingerprint",
            "pki.inspect_certificate_extensions",
            "pki.inspect_certificate_file",
            "pki.inspect_certificate_names",
            "pki.inspect_certificate_public_key",
            "pki.inspect_csr",
            "pki.inspect_private_key",
            "pki.inspect_remote_tls_certificate",
            "pki.inspect_remote_tls_chain",
            "pki.inspect_tls_handshake",
            "pki.inspect_trust_store",
            "pki.install_certificate",
            "pki.install_certificate_chain",
            "pki.install_private_key",
            "pki.list_expiring_certificates",
            "pki.remove_ca_certificate",
            "pki.renew_acme_certificate",
            "pki.request_acme_certificate",
            "pki.restore_certificate_material",
            "pki.revoke_acme_certificate",
            "pki.update_trust_store",
            "pki.verify_certificate_against_ca",
            "pki.verify_certificate_chain",
            "pki.verify_certificate_with_intermediates",
            "pki.verify_private_key_matches_certificate",
            "pki.verify_remote_tls_chain",
        ]
    )
    assert definitions[0].domain == "pki"
    inspect_file = next(tool for tool in definitions if tool.name == "pki.inspect_certificate_file")
    assert set(inspect_file.input_schema["properties"]) == {"source", "path"}


def test_inspect_certificate_executes_openssl_in_source() -> None:
    backend = FakeRuntimeBackend()
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_certificate_file",
        {"source": "web-server", "path": "/etc/ssl/certs/server.pem"},
    )

    assert backend.container == "web-server"
    assert backend.command == [
        "openssl",
        "x509",
        "-in",
        "/etc/ssl/certs/server.pem",
        "-noout",
        "-subject",
        "-issuer",
        "-serial",
        "-dates",
        "-fingerprint",
        "-sha256",
    ]
    assert result.successful is True
    assert "subject=CN=example.test" in result.details
    assert result.certificate.subject == "CN=example.test"
    assert result.certificate.issuer == "CN=Example CA"
    assert result.certificate.fingerprint_sha256 == "AA:BB:CC"


def test_inspect_certificate_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(exit_code=1, stdout="", stderr="unable to load certificate")
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_certificate_file",
        {"source": "web-server", "path": "/missing.pem"},
    )

    assert result.successful is False
    assert result.stderr == "unable to load certificate"


def test_inspect_certificate_names_extracts_subject_and_sans() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "subject=CN=www.example.test\n"
                "X509v3 Subject Alternative Name:\n"
                "    DNS:www.example.test, DNS:api.example.test, IP Address:10.0.0.5\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_certificate_names",
        {"source": "web-server", "path": "/etc/ssl/certs/server.pem"},
    )

    assert backend.command == [
        "openssl",
        "x509",
        "-in",
        "/etc/ssl/certs/server.pem",
        "-noout",
        "-subject",
        "-ext",
        "subjectAltName",
    ]
    assert result.successful is True
    assert result.names.subject == "CN=www.example.test"
    assert result.names.common_name == "www.example.test"
    assert result.names.subject_alt_names == [
        "DNS:www.example.test",
        "DNS:api.example.test",
        "IP Address:10.0.0.5",
    ]


def test_inspect_certificate_extensions_extracts_common_extensions() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "Certificate:\n"
                "    X509v3 Basic Constraints: critical\n"
                "        CA:FALSE\n"
                "    X509v3 Key Usage: critical\n"
                "        Digital Signature, Key Encipherment\n"
                "    X509v3 Extended Key Usage:\n"
                "        TLS Web Server Authentication\n"
                "    X509v3 Subject Alternative Name:\n"
                "        DNS:www.example.test\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_certificate_extensions",
        {"source": "web-server", "path": "/etc/ssl/certs/server.pem"},
    )

    assert backend.command == [
        "openssl",
        "x509",
        "-in",
        "/etc/ssl/certs/server.pem",
        "-noout",
        "-text",
    ]
    assert result.successful is True
    assert result.extensions.basic_constraints == "CA:FALSE"
    assert result.extensions.key_usage == "Digital Signature, Key Encipherment"
    assert result.extensions.extended_key_usage == "TLS Web Server Authentication"
    assert result.extensions.subject_alt_names == ["DNS:www.example.test"]


def test_inspect_certificate_public_key_extracts_algorithm_and_bits() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "Certificate:\n"
                "    Subject Public Key Info:\n"
                "        Public Key Algorithm: rsaEncryption\n"
                "            Public-Key: (2048 bit)\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_certificate_public_key",
        {"source": "web-server", "path": "/etc/ssl/certs/server.pem"},
    )

    assert backend.command == [
        "openssl",
        "x509",
        "-in",
        "/etc/ssl/certs/server.pem",
        "-noout",
        "-text",
    ]
    assert result.successful is True
    assert result.public_key.algorithm == "rsaEncryption"
    assert result.public_key.bits == 2048


def test_get_certificate_fingerprint_uses_requested_digest() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout="sha512 Fingerprint=11:22:33\n",
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.get_certificate_fingerprint",
        {
            "source": "web-server",
            "path": "/etc/ssl/certs/server.pem",
            "digest": "sha512",
        },
    )

    assert backend.command == [
        "openssl",
        "x509",
        "-in",
        "/etc/ssl/certs/server.pem",
        "-noout",
        "-fingerprint",
        "-sha512",
    ]
    assert result.digest == "sha512"
    assert result.fingerprint == "11:22:33"


def test_inspect_remote_tls_certificate_executes_s_client_from_source() -> None:
    backend = FakeRuntimeBackend()
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_remote_tls_certificate",
        {
            "source": "client",
            "target": "web1",
            "port": 443,
            "server_name": "www.example.test",
            "timeout_seconds": 7,
        },
    )

    assert backend.container == "client"
    assert backend.command == [
        "timeout",
        "7",
        "openssl",
        "s_client",
        "-connect",
        "web1:443",
        "-showcerts",
        "-servername",
        "www.example.test",
    ]
    assert result.successful is True
    assert result.certificate.not_after == "Aug 20 00:00:00 2027 GMT"


def test_inspect_remote_tls_certificate_can_omit_server_name() -> None:
    backend = FakeRuntimeBackend()
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_remote_tls_certificate",
        {"source": "client", "target": "web1"},
    )

    assert backend.command == [
        "timeout",
        "5",
        "openssl",
        "s_client",
        "-connect",
        "web1:443",
        "-showcerts",
    ]
    assert result.server_name is None


def test_inspect_remote_tls_chain_extracts_presented_certificates() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "CONNECTED\n"
                "-----BEGIN CERTIFICATE-----\n"
                "leaf\n"
                "-----END CERTIFICATE-----\n"
                "-----BEGIN CERTIFICATE-----\n"
                "intermediate\n"
                "-----END CERTIFICATE-----\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_remote_tls_chain",
        {
            "source": "client",
            "target": "web1",
            "server_name": "www.example.test",
        },
    )

    assert backend.command == [
        "timeout",
        "5",
        "openssl",
        "s_client",
        "-connect",
        "web1:443",
        "-showcerts",
        "-servername",
        "www.example.test",
    ]
    assert result.successful is True
    assert result.certificate_count == 2
    assert result.certificates_pem == [
        "-----BEGIN CERTIFICATE-----\nleaf\n-----END CERTIFICATE-----",
        "-----BEGIN CERTIFICATE-----\nintermediate\n-----END CERTIFICATE-----",
    ]


def test_inspect_tls_handshake_extracts_protocol_cipher_and_verify_code() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "SSL-Session:\n"
                "    Protocol  : TLSv1.3\n"
                "    Cipher    : TLS_AES_256_GCM_SHA384\n"
                "    Verify return code: 0 (ok)\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_tls_handshake",
        {"source": "client", "target": "web1", "port": 8443},
    )

    assert backend.command == [
        "timeout",
        "5",
        "openssl",
        "s_client",
        "-connect",
        "web1:8443",
    ]
    assert result.successful is True
    assert result.handshake.protocol == "TLSv1.3"
    assert result.handshake.cipher == "TLS_AES_256_GCM_SHA384"
    assert result.handshake.verify_return_code == "0 (ok)"


def test_inspect_tls_handshake_parses_openssl_1_1_1_summary() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=("New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384\nVerify return code: 0 (ok)\n"),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_tls_handshake",
        {"source": "client", "target": "web1"},
    )

    assert result.handshake.protocol == "TLSv1.3"
    assert result.handshake.cipher == "TLS_AES_256_GCM_SHA384"


def test_check_tls_hostname_uses_expected_hostname_for_default_sni() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "Verification: OK\n"
                "Verified peername: www.example.test\n"
                "Verify return code: 0 (ok)\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_hostname",
        {
            "source": "client",
            "target": "web1",
            "expected_hostname": "www.example.test",
        },
    )

    assert backend.command == [
        "timeout",
        "5",
        "openssl",
        "s_client",
        "-connect",
        "web1:443",
        "-showcerts",
        "-servername",
        "www.example.test",
        "-verify_hostname",
        "www.example.test",
        "-verify_return_error",
    ]
    assert result.matched is True
    assert result.trusted is True
    assert result.verification_error_category is None
    assert result.server_name == "www.example.test"


def test_check_tls_hostname_reports_mismatch() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=1,
            stdout="",
            stderr="hostname mismatch",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_hostname",
        {
            "source": "client",
            "target": "web1",
            "expected_hostname": "www.example.test",
            "server_name": "default.example.test",
        },
    )

    assert result.matched is False
    assert result.trusted is True
    assert result.verification_error_category == "hostname_mismatch"
    assert result.server_name == "default.example.test"
    assert result.stderr == "hostname mismatch"


def test_check_tls_hostname_accepts_explicit_ca_file() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout="Verified peername: www.example.test\nVerify return code: 0 (ok)\n",
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_hostname",
        {
            "source": "client",
            "target": "web1",
            "expected_hostname": "www.example.test",
            "ca_file_path": "/tmp/ca.crt",
        },
    )

    assert ["-CAfile", "/tmp/ca.crt"] == backend.command[-5:-3]
    assert result.matched is True
    assert result.trusted is True


def test_check_tls_hostname_reports_unknown_match_when_trust_fails_first() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=1,
            stdout="Verify return code: 20 (unable to get local issuer certificate)\n",
            stderr="unable to get local issuer certificate",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_hostname",
        {
            "source": "client",
            "target": "web1",
            "expected_hostname": "www.example.test",
        },
    )

    assert result.matched is None
    assert result.trusted is False
    assert result.verification_error_category == "incomplete_chain"


def test_check_tls_protocols_runs_one_command_per_protocol() -> None:
    backend = QueueRuntimeBackend(
        [
            RuntimeCommandResult(exit_code=0, stdout="", stderr=""),
            RuntimeCommandResult(exit_code=1, stdout="", stderr="disabled"),
        ]
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_protocols",
        {
            "source": "client",
            "target": "web1",
            "protocols": ["tls1_2", "tls1_3"],
        },
    )

    assert backend.commands[0][-1] == "-tls1_2"
    assert backend.commands[1][-1] == "-tls1_3"
    assert [check.accepted for check in result.results] == [True, False]


def test_check_tls_cipher_uses_cipher_option() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout="Cipher    : ECDHE-RSA-AES128-GCM-SHA256\n",
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_cipher",
        {
            "source": "client",
            "target": "web1",
            "cipher": "ECDHE-RSA-AES128-GCM-SHA256",
        },
    )

    assert backend.command[-2:] == ["-cipher", "ECDHE-RSA-AES128-GCM-SHA256"]
    assert result.accepted is True
    assert result.negotiated_cipher == "ECDHE-RSA-AES128-GCM-SHA256"


def test_check_tls_cipher_rejects_different_negotiated_cipher() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout="New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384\n",
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_tls_cipher",
        {
            "source": "client",
            "target": "web1",
            "cipher": "ECDHE-RSA-AES256-GCM-SHA384",
        },
    )

    assert result.accepted is False
    assert result.negotiated_cipher == "TLS_AES_256_GCM_SHA384"


def test_verify_certificate_chain_executes_openssl_verify() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(exit_code=0, stdout="/tmp/server.pem: OK\n", stderr="")
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.verify_certificate_chain",
        {
            "source": "client",
            "certificate_path": "/tmp/server.pem",
            "ca_file_path": "/etc/ssl/certs/ca.pem",
            "untrusted_chain_path": "/tmp/intermediate.pem",
        },
    )

    assert backend.command == [
        "openssl",
        "verify",
        "-CAfile",
        "/etc/ssl/certs/ca.pem",
        "-untrusted",
        "/tmp/intermediate.pem",
        "/tmp/server.pem",
    ]
    assert result.trusted is True
    assert result.output == "/tmp/server.pem: OK\n"


def test_verify_certificate_chain_reports_untrusted_certificate() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(exit_code=2, stdout="", stderr="certificate verify failed")
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.verify_certificate_chain",
        {"source": "client", "certificate_path": "/tmp/server.pem"},
    )

    assert result.trusted is False
    assert result.stderr == "certificate verify failed"


def test_verify_remote_tls_chain_executes_s_client_verify() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(exit_code=0, stdout="Verify return code: 0 (ok)", stderr="")
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.verify_remote_tls_chain",
        {
            "source": "client",
            "target": "web1",
            "ca_file_path": "/tmp/ca.pem",
        },
    )

    assert "-verify_return_error" in backend.command
    assert backend.command[-2:] == ["-CAfile", "/tmp/ca.pem"]
    assert result.trusted is True


def test_explain_verification_failure_normalizes_error() -> None:
    registry = ToolRegistry()
    register_pki_tools(registry, FakeRuntimeBackend())

    result = anyio.run(
        registry.invoke,
        "pki.explain_verification_failure",
        {"stderr": "unable to get local issuer certificate"},
    )

    assert result.category == "incomplete_chain"


def test_check_certificate_expiration_reports_valid_certificate() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=("notAfter=Aug 20 00:00:00 2027 GMT\nCertificate will not expire\n"),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_certificate_expiration",
        {"source": "web-server", "path": "/etc/ssl/certs/server.pem"},
    )

    assert backend.command == [
        "openssl",
        "x509",
        "-in",
        "/etc/ssl/certs/server.pem",
        "-noout",
        "-enddate",
        "-checkend",
        "0",
    ]
    assert result.successful is True
    assert result.expired is False
    assert result.expires_within_warning_window is False
    assert result.not_after == "Aug 20 00:00:00 2027 GMT"


def test_check_certificate_expiration_reports_warning_window() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=1,
            stdout="notAfter=Aug 20 00:00:00 2026 GMT\nCertificate will expire\n",
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_certificate_expiration",
        {
            "source": "web-server",
            "path": "/etc/ssl/certs/server.pem",
            "warning_seconds": 86400,
        },
    )

    assert backend.command[-1] == "86400"
    assert result.expired is None
    assert result.expires_within_warning_window is True


def test_check_remote_certificate_expiration_decodes_leaf_certificate(
    monkeypatch,
) -> None:
    certificate = """-----BEGIN CERTIFICATE-----
MIICtDCCAZwCFClOQ4U9FRfQ70IZow5ASzj0t51yMA0GCSqGSIb3DQEBCwUAMBox
GDAWBgNVBAMMD1NFRURlbXUgVGVzdCBDQTAeFw0yNjA5MjIxNDE0MThaFw0yNjEw
MjIxNDE0MThaMBMxETAPBgNVBAMMCHBraS50ZXN0MIIBIjANBgkqhkiG9w0BAQEF
AAOCAQ8AMIIBCgKCAQEA1qKy52FvLuEayajLsSuhvE9o4WOEdVay+8QoRVUdzde4
3B26APgfp6LmF7UFbOjHrVmtXYVpaosYCZu9v8ds7nJJMG/DacGT7WVPGVU8zMYJ
F5rMpQGyxfi1PSIZhdRcbQpux+quqCAeFnc8h8xMmyRVndA0v7a9Ip3tB5MoYHeC
166zyNj8/SAceo9KMu1wg3CSc4EKtj74XtCafYKlUeTVByh1ZXWwVxGcn1IaIwnu
1II9blII07/J0ItOsrtyi60gV6Amg/2vT54RTHOyehbcJL3xccr1SbNC+TK3gLNA
H+TvRFcBcLGpaedilk9soDagd8GZg2lrFVzRk24ffwIDAQABMA0GCSqGSIb3DQEB
CwUAA4IBAQA3FocQ4QURuQq7W228Bwk7VObb+NkvrIvKAFyPo8mwPDdyxBPe4lhW
TO2/IwpnLZ5cPaS0qGGqpzqZEsORVMwa1Oor4sa7p7brrq/XCIFtC8t1npI0IYbm
+8tJqszrtXw7D9MeBbErg2i9bCqwl3GV1W8AY4nYxS4BtY+UvLXyOWbYuE/uhchf
M7e9FeJDgpVKArrsHihWhLWBnV4kQL9JP0J7+OXLEvhgzMIi9yJ3aujyiOykKHgv
ysfwk2w3EhF1wL5DyeGgm61YyE7GOp7t6n6IDws7OLj7u+U+gB50lXaRw8XnM7fA
t8LQ+xLAm/QCs28MUmj/fxO3j3k0Hwug
-----END CERTIFICATE-----"""
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=f"CONNECTED\n{certificate}\nVerify return code: 21\n",
            stderr="unable to verify the first certificate",
        )
    )
    monkeypatch.setattr(
        "seedemu_tool_service.tools.pki.expiration.tools.time.time",
        lambda: 1_758_499_200,
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.check_remote_certificate_expiration",
        {
            "source": "client",
            "target": "web1",
            "warning_seconds": 2_592_000,
        },
    )

    assert result.successful is True
    assert result.not_after == "Oct 22 14:14:18 2026 GMT"
    assert result.expired is False


def test_list_expiring_certificates_scans_find_results() -> None:
    backend = QueueRuntimeBackend(
        [
            RuntimeCommandResult(exit_code=0, stdout="/tmp/a.pem\n/tmp/b.pem\n", stderr=""),
            RuntimeCommandResult(exit_code=1, stdout="notAfter=tomorrow\n", stderr=""),
            RuntimeCommandResult(exit_code=0, stdout="notAfter=next year\n", stderr=""),
        ]
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.list_expiring_certificates",
        {"source": "web-server", "directory_path": "/tmp"},
    )

    assert backend.commands[0][:4] == ["find", "/tmp", "-maxdepth", "1"]
    assert result.scanned_paths == ["/tmp/a.pem", "/tmp/b.pem"]
    assert [entry.path for entry in result.expiring_certificates] == ["/tmp/a.pem"]


def test_inspect_csr_parses_indented_subject_and_sans() -> None:
    backend = FakeRuntimeBackend(
        RuntimeCommandResult(
            exit_code=0,
            stdout=(
                "Certificate Request:\n"
                "    Data:\n"
                "        Subject: CN = pki.test\n"
                "        Requested Extensions:\n"
                "            X509v3 Subject Alternative Name:\n"
                "                DNS:pki.test, IP Address:127.0.0.1\n"
            ),
            stderr="",
        )
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.inspect_csr",
        {"source": "web-server", "csr_path": "/tmp/server.csr"},
    )

    assert result.subject == "CN = pki.test"
    assert result.subject_alt_names == ["DNS:pki.test", "IP Address:127.0.0.1"]


def test_verify_private_key_matches_certificate_compares_public_key_digest() -> None:
    public_key = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
    backend = QueueRuntimeBackend(
        [
            RuntimeCommandResult(exit_code=0, stdout=public_key, stderr=""),
            RuntimeCommandResult(exit_code=0, stdout=public_key, stderr=""),
        ]
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.verify_private_key_matches_certificate",
        {
            "source": "web-server",
            "key_path": "/tmp/server.key",
            "certificate_path": "/tmp/server.crt",
        },
    )

    assert backend.commands[0] == [
        "openssl",
        "pkey",
        "-in",
        "/tmp/server.key",
        "-pubout",
        "-outform",
        "PEM",
    ]
    assert backend.commands[1] == [
        "openssl",
        "x509",
        "-in",
        "/tmp/server.crt",
        "-noout",
        "-pubkey",
    ]
    assert result.matches is True
    assert result.key_public_hash == result.certificate_public_hash
    assert len(result.key_public_hash) == 64


def test_install_private_key_copies_and_chmods_destination() -> None:
    backend = QueueRuntimeBackend(
        [
            RuntimeCommandResult(exit_code=0, stdout="", stderr=""),
            RuntimeCommandResult(exit_code=0, stdout="", stderr=""),
            RuntimeCommandResult(exit_code=0, stdout="", stderr=""),
        ]
    )
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.install_private_key",
        {
            "source": "web-server",
            "source_path": "/tmp/server.key",
            "destination_path": "/etc/ssl/private/server.key",
        },
    )

    assert backend.commands[0] == [
        "test",
        "!",
        "-e",
        "/etc/ssl/private/server.key",
    ]
    assert backend.commands[1] == [
        "cp",
        "/tmp/server.key",
        "/etc/ssl/private/server.key",
    ]
    assert backend.commands[2] == ["chmod", "600", "/etc/ssl/private/server.key"]
    assert result.created_paths == ["/etc/ssl/private/server.key"]


def test_install_certificate_rejects_existing_destination() -> None:
    backend = FakeRuntimeBackend(RuntimeCommandResult(exit_code=1, stdout="", stderr=""))
    registry = ToolRegistry()
    register_pki_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.install_certificate",
        {
            "source": "web-server",
            "source_path": "/tmp/server.crt",
            "destination_path": "/etc/ssl/certs/server.crt",
        },
    )

    assert result.successful is False
    assert result.created_paths == []
    assert result.stderr == "destination path already exists: /etc/ssl/certs/server.crt"
    assert len(backend.commands) == 1
