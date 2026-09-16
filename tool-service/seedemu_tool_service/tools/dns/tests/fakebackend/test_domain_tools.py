"""Fake-backend tests for Registrar discovery and interface-driven requests."""

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools
from seedemu_tool_service.tools.dns.models import (
    RddsLookupArguments,
    RegistrarFindArguments,
    RegistrarRequestArguments,
)
from seedemu_tool_service.tools.dns.tools import DNSTools, RegistrarMetadataError

REGISTRAR_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.registrar_url"
CREDENTIAL_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.registrar_credential_ref"
REGISTRAR_URL = "http://10.0.0.10:8080"
RDDS_AUTHORITY_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.rdds.authority"
RDDS_WHOIS_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.rdds.whois_server"
RDDS_RDAP_LABEL = "org.seedsecuritylabs.seedemu.meta.agent.exposed.rdds.rdap_url"


class FakeRuntimeBackend:
    def __init__(self, result: RuntimeCommandResult) -> None:
        self.result = result
        self.container: str | None = None
        self.command: list[str] | None = None

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.command = list(command)
        return self.result


def expose_registrars(monkeypatch: pytest.MonkeyPatch, labels: list[dict[str, str]]) -> None:
    class Container:
        def __init__(self, values: dict[str, str]) -> None:
            self.attrs = {"Config": {"Labels": values}}

    class Containers:
        def list(self, *, filters: dict[str, str]) -> list[Container]:
            assert filters == {"label": REGISTRAR_LABEL}
            return [Container(values) for values in labels]

    class Client:
        containers = Containers()

    monkeypatch.setattr(
        "seedemu_tool_service.tools.dns.domain_registration.tools.docker.from_env", lambda: Client()
    )


def expose_source_owned_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    common = {
        "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.service_id": "owned-dns",
        "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.primary": "10.0.0.53",
        "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.secondary": "10.0.0.54",
        "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.credential_ref": "owned-dns.control",
    }

    class Container:
        def __init__(self, role: str) -> None:
            labels = (
                {
                    "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns."
                    "authoritative_services": "owned-dns"
                }
                if role == "source"
                else {
                    **common,
                    "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.role": role,
                }
            )
            self.attrs = {"Config": {"Labels": labels}}

    class Containers:
        def get(self, name: str) -> Container:
            assert name == "client"
            return Container("source")

        def list(self, *, filters: dict[str, str]) -> list[Container]:
            assert filters == {
                "label": "org.seedsecuritylabs.seedemu.meta.agent.exposed.dns.service_id"
            }
            return [Container("primary"), Container("secondary")]

    class Client:
        containers = Containers()

    monkeypatch.setattr(
        "seedemu_tool_service.tools.dns.domain_registration.tools.docker.from_env", lambda: Client()
    )


def expose_rdds(monkeypatch: pytest.MonkeyPatch) -> None:
    values = [
        {
            RDDS_AUTHORITY_LABEL: "registrar",
            RDDS_WHOIS_LABEL: "whois.registrar.test",
            RDDS_RDAP_LABEL: "http://rdap.registrar.test",
        },
        {
            RDDS_AUTHORITY_LABEL: "registry",
            RDDS_WHOIS_LABEL: "whois.registry.test",
            RDDS_RDAP_LABEL: "http://rdap.registry.test",
        },
    ]

    class Container:
        def __init__(self, labels: dict[str, str]) -> None:
            self.attrs = {"Config": {"Labels": labels}}

    class Containers:
        def list(self, *, filters: dict[str, str]) -> list[Container]:
            assert filters == {"label": RDDS_AUTHORITY_LABEL}
            return [Container(labels) for labels in values]

    class Client:
        containers = Containers()

    monkeypatch.setattr(
        "seedemu_tool_service.tools.dns.domain_registration.tools.docker.from_env", lambda: Client()
    )


def test_registers_documented_registrar_tools() -> None:
    registry = ToolRegistry()
    register_dns_tools(
        registry, FakeRuntimeBackend(RuntimeCommandResult(exit_code=0, stdout="", stderr=""))
    )
    names = {tool.name for tool in registry.list_tools() if tool.name.startswith("domain.")}
    assert names == {"domain.registrar_find", "domain.registrar_request", "domain.rdds_lookup"}
    dns_names = {tool.name for tool in registry.list_tools() if tool.domain == "dns"}
    assert {"dns.authoritative_find", "dns.configure"} <= dns_names


def test_configure_uses_source_private_identity_and_verifies_both_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expose_source_owned_dns(monkeypatch)
    stdout = "\n".join([
        "__SEED_DNS_PRIMARY_SOA__ns1.example.com. hostmaster.example.com. 5 300 60 86400 60",
        "__SEED_DNS_SECONDARY_SOA__ns1.example.com. hostmaster.example.com. 5 300 60 86400 60",
        "__SEED_DNS_PRIMARY_NS__ns1.example.com.,ns2.example.com.",
        "__SEED_DNS_SECONDARY_NS__ns1.example.com.,ns2.example.com.",
        "__SEED_DNS_PRIMARY_AA__1",
        "__SEED_DNS_SECONDARY_AA__1",
    ])
    backend = FakeRuntimeBackend(RuntimeCommandResult(exit_code=0, stdout=stdout, stderr=""))
    result = DNSTools(backend).configure(
        source="client", dns_service_id="owned-dns", zone="example.com",
        changes=[{"name": "www.example.com", "record_type": "A",
                  "operation": "replace", "ttl": 300, "value": "192.0.2.8"}],
    )
    assert backend.container == "client"
    assert backend.command is not None
    script = backend.command[-1]
    assert "/opt/seedemu/dns/owned-dns/control.key" in script
    assert "StrictHostKeyChecking=yes" in script
    assert "root@10.0.0.53" in script and "root@10.0.0.54" in script
    assert result.successful is True
    assert result.primary_authoritative is True
    assert result.secondary_authoritative is True
    assert result.primary_soa == result.secondary_soa


def test_authoritative_find_returns_services_owned_by_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expose_source_owned_dns(monkeypatch)
    tools = DNSTools(FakeRuntimeBackend(RuntimeCommandResult(exit_code=0, stdout="", stderr="")))

    result = tools.authoritative_find("client")

    assert result.source == "client"
    assert [service.model_dump() for service in result.services] == [{
        "service_id": "owned-dns",
        "primary": "10.0.0.53",
        "secondary": "10.0.0.54",
        "credential_ref": "owned-dns.control",
    }]


def test_registrar_find_filter_is_an_empty_future_extension_point() -> None:
    assert RegistrarFindArguments.model_validate({}).model_dump() == {"filter": {}}
    assert RegistrarFindArguments.model_validate({"filter": {}}).model_dump() == {"filter": {}}
    with pytest.raises(ValidationError, match="must currently be empty"):
        RegistrarFindArguments.model_validate({"filter": {"tld": "com"}})


def test_registrar_find_returns_only_location_and_opaque_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expose_registrars(
        monkeypatch,
        [
            {REGISTRAR_LABEL: "http://10.0.0.2:8080/", CREDENTIAL_LABEL: "principal:registrar-2"},
            {REGISTRAR_LABEL: "http://10.0.0.1:8080", "private.node": "hidden"},
        ],
    )
    tools = DNSTools(FakeRuntimeBackend(RuntimeCommandResult(exit_code=0, stdout="", stderr="")))
    result = tools.registrar_find()
    assert [item.model_dump() for item in result.registrars] == [
        {"registrar_url": "http://10.0.0.1:8080", "credential_ref": None},
        {"registrar_url": "http://10.0.0.2:8080", "credential_ref": "principal:registrar-2"},
    ]
    assert "domain.registrar_request" in result.next_step


def test_registrar_request_reads_html_without_following_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expose_registrars(monkeypatch, [{REGISTRAR_LABEL: REGISTRAR_URL}])
    response = (
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><script src='/app.js'></script></html>\n__SEED_REGISTRAR_HEADERS__200"
    )
    backend = FakeRuntimeBackend(RuntimeCommandResult(exit_code=0, stdout=response, stderr=""))
    result = DNSTools(backend).registrar_request("client", REGISTRAR_URL, path="/")
    assert result.successful is True
    assert result.content_type == "text/html; charset=utf-8"
    assert result.body == "<html><script src='/app.js'></script></html>"
    assert backend.container == "client"
    assert backend.command is not None
    assert f"{REGISTRAR_URL}/" in backend.command[-1]
    assert "--max-redirs" in backend.command[-1]


def test_registrar_request_rejects_unexposed_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    expose_registrars(monkeypatch, [{REGISTRAR_LABEL: REGISTRAR_URL}])
    tools = DNSTools(FakeRuntimeBackend(RuntimeCommandResult(exit_code=0, stdout="", stderr="")))
    with pytest.raises(RegistrarMetadataError, match="not present"):
        tools.registrar_request("client", "http://attacker.invalid", path="/")


def test_rdds_lookup_selects_whois_protocol_and_registry_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expose_rdds(monkeypatch)
    backend = FakeRuntimeBackend(RuntimeCommandResult(
        exit_code=0, stdout="Domain Name: EXAMPLE.COM\n", stderr=""
    ))
    result = DNSTools(backend).rdds_lookup("client", "whois", "registry", "Example.COM.")
    assert backend.command == ["whois", "-h", "whois.registry.test", "example.com"]
    assert result.successful and result.found is True
    assert result.authority == "registry"


def test_rdds_lookup_selects_rdap_protocol_and_registrar_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expose_rdds(monkeypatch)
    payload = '{"objectClassName":"domain","ldhName":"example.com"}'
    backend = FakeRuntimeBackend(RuntimeCommandResult(
        exit_code=0,
        stdout=payload + "\n__SEED_RDDS_RESPONSE__200|application/rdap+json",
        stderr="",
    ))
    result = DNSTools(backend).rdds_lookup("client", "rdap", "registrar", "example.com")
    assert backend.command is not None
    assert backend.command[-1] == "http://rdap.registrar.test/domain/example.com"
    assert result.successful and result.rdap is not None
    assert result.rdap["ldhName"] == "example.com"


def test_rdds_lookup_arguments_reject_invalid_domains() -> None:
    with pytest.raises(ValidationError):
        RddsLookupArguments.model_validate({
            "source": "client", "protocol": "rdap", "authority": "registry",
            "domain": "https://example.com/path",
        })


@pytest.mark.parametrize(
    "change",
    [
        {"path": "https://attacker.invalid/"},
        {"path": "//attacker.invalid/"},
        {"path": "/page#fragment"},
        {"method": "GET", "body": "x=1", "content_type": "application/x-www-form-urlencoded"},
        {"method": "POST", "body": None, "content_type": None},
        {"registrar_url": "http://user:password@registrar.invalid"},
    ],
)
def test_registrar_request_schema_rejects_unsafe_requests(change: dict[str, object]) -> None:
    arguments: dict[str, object] = {
        "source": "client",
        "registrar_url": REGISTRAR_URL,
        "method": "GET",
        "path": "/",
    }
    arguments.update(change)
    with pytest.raises(ValidationError):
        RegistrarRequestArguments.model_validate(arguments)
