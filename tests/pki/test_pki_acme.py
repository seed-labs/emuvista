"""Tests for real ACME operations executed inside emulator nodes."""

from collections.abc import Sequence
import json

import anyio

from services.AgentService.tools.pki.execution import RuntimeCommandResult, RuntimeStatus
from services.AgentService.tools.pki.acme import register_acme_tools
from services.AgentService.tools.pki.catalog import Catalog


class FakeRuntimeBackend:
    def __init__(self, result: RuntimeCommandResult | None = None) -> None:
        self.result = result or RuntimeCommandResult(exit_code=0, stdout="issued", stderr="")
        self.container: str | None = None
        self.command: list[str] | None = None
        self.commands: list[list[str]] = []

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.command = list(command)
        self.commands.append(list(command))
        if command and command[0] == "timeout" and command[-1].startswith("{"):
            arguments = json.loads(command[-1])
            if arguments.get("action") == "service":
                return RuntimeCommandResult(
                    exit_code=0,
                    stdout=json.dumps(
                        {
                            "data": {
                                "acme_directory_urls": [
                                    {"directory_url": "https://ca.pki.test/acme/acme/directory"}
                                ]
                            }
                        }
                    ),
                    stderr="",
                )
            if arguments.get("action") == "renewal_server":
                return RuntimeCommandResult(
                    exit_code=0,
                    stdout=json.dumps(
                        {"data": {"server": "https://ca.pki.test/acme/acme/directory"}}
                    ),
                    stderr="",
                )
        if list(command) == ["test", "-e", "/etc/letsencrypt/renewal/www.pki.test.conf"]:
            return RuntimeCommandResult(exit_code=1, stdout="", stderr="")
        if list(command) == ["certbot", "--version"]:
            return RuntimeCommandResult(exit_code=0, stdout="certbot 2.0", stderr="")
        return self.result


def test_request_acme_certificate_runs_certbot_http01() -> None:
    backend = FakeRuntimeBackend()
    registry = Catalog()
    register_acme_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.request_acme_certificate",
        {
            "source": "web",
            "ca_service_source": "ca",
            "directory_url": "https://ca.pki.test/acme/acme/directory",
            "domains": ["www.pki.test"],
            "email": "admin@pki.test",
            "authenticator": "nginx",
        },
    )

    assert backend.container == "web"
    assert backend.command == [
        "certbot",
        "certonly",
        "--non-interactive",
        "--agree-tos",
        "--no-eff-email",
        "--server",
        "https://ca.pki.test/acme/acme/directory",
        "--email",
        "admin@pki.test",
        "--cert-name",
        "www.pki.test",
        "--nginx",
        "-d",
        "www.pki.test",
    ]
    assert result.successful is True
    assert result.fullchain_path == "/etc/letsencrypt/live/www.pki.test/fullchain.pem"


def test_request_acme_certificate_rejects_wildcard_http01() -> None:
    registry = Catalog()
    register_acme_tools(registry, FakeRuntimeBackend())

    try:
        anyio.run(
            registry.invoke,
            "pki.request_acme_certificate",
            {
                "source": "web",
                "ca_service_source": "ca",
                "directory_url": "https://ca.pki.test/acme/acme/directory",
                "domains": ["*.pki.test"],
                "email": "admin@pki.test",
            },
        )
    except ValueError as error:
        assert "Wildcard names and DNS credentials require dns-rfc2136" in str(error)
    else:
        raise AssertionError("wildcard HTTP-01 request was accepted")


def test_renew_acme_certificate_runs_certbot_renew() -> None:
    backend = FakeRuntimeBackend()
    registry = Catalog()
    register_acme_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.renew_acme_certificate",
        {
            "source": "web",
            "ca_service_source": "ca",
            "cert_name": "www.pki.test",
            "force_renewal": True,
        },
    )

    assert backend.command == [
        "certbot",
        "renew",
        "--non-interactive",
        "--cert-name",
        "www.pki.test",
        "--force-renewal",
    ]
    assert result.modified_paths[-1] == "/etc/letsencrypt/renewal/www.pki.test.conf"


def test_revoke_acme_certificate_uses_supported_reason() -> None:
    backend = FakeRuntimeBackend()
    registry = Catalog()
    register_acme_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.revoke_acme_certificate",
        {
            "source": "web",
            "ca_service_source": "ca",
            "directory_url": "https://ca.pki.test/acme/acme/directory",
            "certificate_path": "/etc/letsencrypt/live/www.pki.test/cert.pem",
            "reason": "superseded",
        },
    )

    assert backend.command == [
        "certbot",
        "revoke",
        "--non-interactive",
        "--server",
        "https://ca.pki.test/acme/acme/directory",
        "--cert-path",
        "/etc/letsencrypt/live/www.pki.test/cert.pem",
        "--reason",
        "superseded",
    ]
    assert result.successful is True


def test_deploy_acme_certificate_validates_and_reloads_nginx() -> None:
    backend = FakeRuntimeBackend()
    registry = Catalog()
    register_acme_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "pki.deploy_acme_certificate_to_nginx",
        {"source": "web", "cert_name": "www.pki.test", "server_name": "www.pki.test"},
    )

    assert ["nginx", "-t"] in backend.commands
    assert backend.commands[-1] == ["nginx", "-s", "reload"]
    assert result.successful is True
    assert result.modified_paths == [
        "/etc/nginx/sites-available/seedemu-pki-www.pki.test.conf",
        "/etc/nginx/sites-enabled/seedemu-pki-www.pki.test.conf",
    ]
