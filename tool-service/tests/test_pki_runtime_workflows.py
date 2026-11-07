"""Test node probes with real files and TLS."""

import hashlib
import json
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import anyio
import pytest

from seedemu_tool_service.models.runtime import RuntimeCommandResult
from seedemu_tool_service.registry import ToolRegistry as ProductionRegistry
from seedemu_tool_service.tools.pki import register_pki_tools
from seedemu_tool_service.tools.pki.acme.inspection import ACMEInspectionTools
from seedemu_tool_service.tools.pki.ca_service.tools import CAServiceTools
from seedemu_tool_service.tools.pki.remote_tls.verification import TLSVerificationTools
from seedemu_tool_service.tools.pki.trust_verification.status import CertificateStatusTools
from seedemu_tool_service.registry import ToolRegistry


class LocalProbeBackend:
    """Run the node program locally in a bounded subprocess, no Docker."""

    def __init__(self):
        self.calls = []

    def execute(self, source, command):
        self.calls.append((source, command))
        assert command[:3] == ["timeout", "45", "python3"]
        result = subprocess.run(
            [sys.executable, *command[3:]],
            capture_output=True,
            text=True,
            timeout=50,
        )
        return RuntimeCommandResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def test_ca_inspection_redacts_secrets_and_reports_configured_state(tmp_path):
    config = tmp_path / "ca.json"
    config.write_text(
        json.dumps(
            {
                "address": ":443",
                "key": "secret-key",
                "password": "secret-password",
                "authority": {
                    "claims": {"defaultTLSCertDuration": "24h"},
                    "provisioners": [{"name": "acme", "type": "ACME", "key": "secret-jwk"}],
                },
            }
        )
    )
    result = CAServiceTools(LocalProbeBackend()).inspect_ca_service("ca", str(config))
    assert result.successful
    assert result.data["configured_default_duration"] == "24h"
    assert result.data["effective_policy_verified"] is False
    assert "secret" not in result.model_dump_json()


def test_ca_log_returns_bounded_metadata_not_raw_messages(tmp_path):
    log = tmp_path / "step.log"
    records = [
        {
            "time": "2026-10-07T00:00:00Z",
            "path": "/acme/acme/challenge/token",
            "status": 400,
            "method": "POST",
            "msg": "secret-token",
        }
    ] * 3
    log.write_text("unparseable secret-line\n" + "\n".join(map(json.dumps, records)))
    result = CAServiceTools(LocalProbeBackend()).inspect_ca_events("ca", str(log), 2)
    assert result.successful
    assert len(result.data["events"]) == 2
    assert result.data["truncated"]
    assert result.data["unparsed_lines"] == 1
    assert "secret" not in result.model_dump_json()
    assert result.data["events"][0]["kind"] == "challenge"


def test_discovery_handles_missing_and_malformed_lineages(tmp_path):
    tools = ACMEInspectionTools(LocalProbeBackend())
    result = tools.list_managed_certificates("web", str(tmp_path), 10)
    assert result.successful and result.data["directory_exists"] is False
    directory = tmp_path / "renewal"
    directory.mkdir()
    (directory / "bad.conf").write_text("invalid syntax")
    result = tools.list_managed_certificates("web", str(tmp_path), 10)
    assert result.data["certificates"][0]["error"] == "unreadable_renewal_config"


@pytest.fixture
def certificates(tmp_path):
    def openssl(*args):
        subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True)

    ca_key, ca_cert = tmp_path / "ca.key", tmp_path / "ca.crt"
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=Test CA",
        "-keyout",
        ca_key,
        "-out",
        ca_cert,
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    for name, usage in (("server", "serverAuth"), ("client", "clientAuth")):
        key, csr, cert = (tmp_path / (name + suffix) for suffix in (".key", ".csr", ".crt"))
        openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-keyout",
            key,
            "-out",
            csr,
        )
        extension = tmp_path / (name + ".ext")
        extension.write_text("subjectAltName=DNS:localhost\nextendedKeyUsage=" + usage + "\n")
        openssl(
            "x509",
            "-req",
            "-in",
            csr,
            "-CA",
            ca_cert,
            "-CAkey",
            ca_key,
            "-CAcreateserial",
            "-out",
            cert,
            "-days",
            "1",
            "-extfile",
            extension,
        )
    return tmp_path


@pytest.fixture
def tls_server(certificates):
    servers = []

    def start(require_client=False):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificates / "server.crt", certificates / "server.key")
        if require_client:
            context.load_verify_locations(certificates / "ca.crt")
            context.verify_mode = ssl.CERT_REQUIRED
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.2)
        stopped = threading.Event()

        def serve():
            while not stopped.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                try:
                    connection.settimeout(2)
                    with context.wrap_socket(connection, server_side=True) as tls:
                        request = tls.recv(4096)
                        if request:
                            tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                except (OSError, ssl.SSLError):
                    connection.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        servers.append((listener, stopped, thread))
        return listener.getsockname()[1]

    yield start
    for listener, stopped, thread in servers:
        stopped.set()
        listener.close()
        thread.join(timeout=3)


def test_real_tls_verifies_fingerprint_and_rejects_wrong_name(certificates, tls_server):
    port = tls_server()
    der = ssl.PEM_cert_to_DER_cert((certificates / "server.crt").read_text())
    fingerprint = hashlib.sha256(der).hexdigest()
    tools = TLSVerificationTools(LocalProbeBackend())
    args = dict(
        source="client",
        target="127.0.0.1",
        expected_hostname="localhost",
        expected_fingerprint_sha256=fingerprint,
        ca_file_path=str(certificates / "ca.crt"),
        port=port,
        timeout_seconds=2,
    )
    result = tools.verify_tls_deployment(**args)
    assert result.successful and result.data["deployment_verified"]
    result = tools.verify_tls_deployment(**{**args, "expected_fingerprint_sha256": "0" * 64})
    assert result.successful and not result.data["deployment_verified"]
    result = tools.verify_tls_deployment(**{**args, "expected_hostname": "wrong.test"})
    assert not result.data["tls_verified"]
    assert result.data["fingerprint_matches"] is None


@pytest.mark.parametrize("required", [True, False])
def test_real_mtls_distinguishes_optional_and_required_identity(certificates, tls_server, required):
    result = TLSVerificationTools(LocalProbeBackend()).test_mtls_connection(
        "client",
        "127.0.0.1",
        "localhost",
        str(certificates / "client.crt"),
        str(certificates / "client.key"),
        str(certificates / "ca.crt"),
        tls_server(required),
        2,
    )
    assert result.successful
    assert result.data["authenticated_http_request_accepted"]
    if required:
        assert result.data["client_certificate_required"] is not False
        assert result.data["without_client_identity"]["http_status"] is None
    else:
        assert result.data["client_certificate_required"] is False


@pytest.mark.parametrize(
    "exit_code,output,status",
    [
        (0, "leaf: OK", "not_revoked"),
        (2, "error 23 at 0 depth lookup: certificate revoked", "revoked"),
        (2, "error 12 at 0 depth lookup: CRL has expired", "unknown"),
        (2, "error 23 at 0 depth lookup\nerror 12 at 0 depth lookup", "unknown"),
        (124, "", "unknown"),
    ],
)
def test_crl_failure_never_becomes_good_status(exit_code, output, status):
    class Backend:
        def execute(self, source, command):
            assert "-crl_check" in command
            return RuntimeCommandResult(exit_code=exit_code, stdout="", stderr=output)

    result = CertificateStatusTools(Backend()).check_certificate_status(
        "client",
        "/leaf",
        "/ca",
        "/crl",
        None,
        5,
    )
    assert result.status == status
    assert result.successful == (status != "unknown")


def test_new_tools_reject_invalid_input_before_execution():
    backend = LocalProbeBackend()
    registry = ToolRegistry()
    register_pki_tools(registry, backend)
    with pytest.raises(ValueError):
        anyio.run(
            registry.invoke,
            "pki.inspect_renewal_status",
            {"source": "web", "cert_name": "../secrets"},
        )
    with pytest.raises(ValueError):
        anyio.run(
            registry.invoke,
            "pki.verify_tls_deployment",
            {
                "source": "web",
                "target": "localhost",
                "expected_hostname": "localhost",
                "expected_fingerprint_sha256": "not-a-fingerprint",
            },
        )
    assert not backend.calls


def test_real_crl_distinguishes_good_and_revoked(certificates):
    directory = certificates
    (directory / "index").touch()
    config = directory / "openssl-ca.cnf"
    config.write_text(
        "[ca]\ndefault_ca=CA\n[CA]\n"
        f"database={directory}/index\nnew_certs_dir={directory}\n"
        f"certificate={directory}/ca.crt\nprivate_key={directory}/ca.key\n"
        "default_md=sha256\ndefault_crl_days=1\n"
    )
    crl = directory / "ca.crl"

    def ca(*args):
        subprocess.run(
            ["openssl", "ca", "-batch", "-config", str(config), *map(str, args)],
            check=True,
            capture_output=True,
        )

    class Backend:
        def execute(self, source, command):
            result = subprocess.run(command[2:], capture_output=True, text=True, timeout=5)
            return RuntimeCommandResult(
                exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
            )

    ca("-valid", directory / "server.crt")
    ca("-gencrl", "-out", crl)
    tools = CertificateStatusTools(Backend())
    args = ("client", str(directory / "server.crt"), str(directory / "ca.crt"), str(crl), None, 5)
    assert tools.check_certificate_status(*args).status == "not_revoked"
    ca("-revoke", directory / "server.crt")
    ca("-gencrl", "-out", crl)
    assert tools.check_certificate_status(*args).status == "revoked"
    crl.write_text("invalid CRL")
    assert tools.check_certificate_status(*args).status == "unknown"


def test_certbot_discovery_and_renewal_preserve_unknown_outcome(certificates):
    directory = certificates / "renewal"
    directory.mkdir()
    (directory / "web.conf").write_text(
        f"cert = {certificates}/server.crt\nprivkey = {certificates}/server.key\n"
        "[renewalparams]\nserver = https://ca.test/acme/acme/directory\n"
        "authenticator = nginx\nrenew_hook = secret-command\n"
    )
    tools = ACMEInspectionTools(LocalProbeBackend())
    result = tools.list_managed_certificates("web", str(certificates), 10)
    assert result.successful
    entry = result.data["certificates"][0]
    assert entry["certificate_readable"]
    assert entry["hooks_configured"]
    assert "secret-command" not in result.model_dump_json()
    result = tools.inspect_renewal_status("web", "web", str(certificates))
    assert result.successful
    assert result.data["last_renewal_outcome"] == "unknown"
    assert not result.data["automatic_renewal_verified"]


def test_environment_missing_bundle_and_readiness_do_not_claim_success(tmp_path):
    tools = ACMEInspectionTools(LocalProbeBackend())
    result = tools.inspect_environment("web", str(tmp_path / "missing.crt"))
    assert result.successful
    assert not result.data["ca_bundle_loadable"]
    result = tools.inspect_acme_readiness(
        "web",
        str(tmp_path / "missing.crt"),
        "https://localhost/acme/directory",
        ["localhost"],
        str(tmp_path),
        1,
    )
    assert result.successful
    assert not result.data["directory_valid"]
    assert result.data["ready_for_issuance"] is None
    assert result.data["ca_http01_reachability"] == "unverified"


def test_renewal_log_signals_do_not_expose_raw_logs_or_claim_lineage_success(tmp_path):
    (tmp_path / "renewal").mkdir()
    (tmp_path / "renewal" / "web.conf").write_text("[renewalparams]\nauthenticator=nginx\n")
    log = tmp_path / "certbot.log"
    log.write_text("secret-token Congratulations, all renewals succeeded\n")
    result = ACMEInspectionTools(LocalProbeBackend()).inspect_renewal_status(
        "web", "web", str(tmp_path), str(log)
    )
    assert result.successful
    assert result.data["recent_log_signals"] == ["renewals_succeeded"]
    assert result.data["last_renewal_outcome"] == "unknown"
    assert "secret-token" not in result.model_dump_json()


def test_malformed_node_output_is_not_a_success():
    class Backend:
        def execute(self, source, command):
            return RuntimeCommandResult(exit_code=0, stdout="unexpected output", stderr="")

    result = ACMEInspectionTools(Backend()).inspect_environment("web", "/ca.crt")
    assert not result.successful
    assert result.data == {}
