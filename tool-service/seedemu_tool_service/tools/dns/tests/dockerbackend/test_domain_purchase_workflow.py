"""End-to-end B02a Registrar workflow through Agent-facing Docker tools.

Run this test against a freshly started B02a deployment.  It intentionally owns
``example.com`` and therefore must not share a Registry database with a prior
B02a topology test that already registered that domain.
"""

import json
import time
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

import anyio

from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools
from seedemu_tool_service.tools.dns.domain_registration.tools import RegistrarMetadataError

SOURCE = "as150h-host_1-10.150.0.72"
DNS_SERVICE_ID = "b02a.source-owned-dns"
REGISTRAR_URL = "https://10.150.0.74:443"
ZONE = "example.com"
NAME = "www.example.com"
ANSWER = "11.160.0.80"
UPDATED_ANSWER = "11.160.0.81"
AVAILABLE_ZONE = "available-check.com"
UPDATED_AUTH_INFO = "B02a-Example-Auth-Updated-2"
COM_SERVERS = ("10.152.0.71", "10.153.0.73")
RECURSIVE_RESOLVERS = ("10.152.0.53", "10.153.0.53")
OWNER_DNS = ["11.160.0.53", "11.160.0.54"]


class _HiddenFields(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("type") == "hidden":
            name = values.get("name")
            value = values.get("value")
            if name is not None and value is not None:
                self.fields[name] = value


def _hidden_fields(html: str) -> dict[str, str]:
    parser = _HiddenFields()
    parser.feed(html)
    assert parser.fields, "Loom form did not expose its CSRF fields"
    return parser.fields


def _invoke(registry: ToolRegistry, name: str, arguments: dict):
    return anyio.run(registry.invoke, name, arguments)


def _registrar_request(
    registry: ToolRegistry,
    session_id: str | None,
    path: str,
    *,
    method: str = "GET",
    fields: list[tuple[str, str]] | None = None,
):
    arguments = {
        "source": SOURCE,
        "registrar_url": REGISTRAR_URL,
        "session_id": session_id,
        "method": method,
        "path": path,
        "authentication": "required",
    }
    if fields is not None:
        arguments.update({
            "content_type": "application/x-www-form-urlencoded",
            "body": urlencode(fields),
        })
    return _invoke(registry, "domain.registrar_request", arguments)


def _wait_for_registrar(registry: ToolRegistry):
    """Wait for Loom's HTTPS, database bootstrap, and source auth endpoint."""
    last_error: Exception | None = None
    for _ in range(30):
        try:
            return _registrar_request(registry, None, "/")
        except RegistrarMetadataError as error:
            last_error = error
            time.sleep(2)
    raise AssertionError("Loom did not become ready within 60 seconds") from last_error


def _check_availability(
    registry: ToolRegistry, session_id: str, domain: str
) -> dict:
    """Use Loom's public EPP-backed availability endpoint through the Agent."""
    home = _registrar_request(registry, session_id, "/")
    assert home.http_status == 200, home.stderr
    response = _registrar_request(
        registry,
        session_id,
        "/spark/domain/check",
        method="POST",
        fields=list(_hidden_fields(home.body).items()) + [("domains[]", domain)],
    )
    assert response.http_status == 200, response.stderr
    payload = json.loads(response.body)
    assert payload.get("success") is True, payload
    assert payload.get("results") == 1, payload
    domains = payload.get("domains")
    assert isinstance(domains, list) and len(domains) == 1, payload
    assert domains[0].get("name") == domain, payload
    return domains[0]


def test_agent_configures_dns_buys_example_com_and_resolves_it() -> None:
    """Exercise availability, purchase, update, delegation, and resolution."""

    registry = ToolRegistry()
    backend = DockerRuntimeBackend()
    register_dns_tools(registry, backend)

    directory = _invoke(registry, "domain.registrar_find", {})
    loom = [item for item in directory.registrars if item.registrar_url == REGISTRAR_URL]
    assert len(loom) == 1, "B02a must expose exactly one Loom frontend"

    dns_directory = _invoke(registry, "dns.authoritative_find", {"source": SOURCE})
    assert dns_directory.source == SOURCE
    assert len(dns_directory.services) == 1, dns_directory
    dns_service = dns_directory.services[0]
    assert dns_service.service_id == DNS_SERVICE_ID
    assert [dns_service.primary, dns_service.secondary] == OWNER_DNS

    configured = _invoke(registry, "dns.configure", {
        "source": SOURCE,
        "dns_service_id": dns_service.service_id,
        "zone": ZONE,
        "changes": [{
            "name": NAME,
            "record_type": "A",
            "operation": "replace",
            "ttl": 300,
            "value": ANSWER,
        }],
    })
    assert configured.successful, configured.stderr
    assert configured.primary_authoritative and configured.secondary_authoritative
    assert configured.primary_soa == configured.secondary_soa

    session_id = None
    try:
        ready = _wait_for_registrar(registry)
        session_id = ready.session_id

        available = _check_availability(registry, session_id, AVAILABLE_ZONE)
        assert available.get("available") is True, available

        invalid_check_form = _registrar_request(registry, session_id, "/")
        assert invalid_check_form.http_status == 200, invalid_check_form.stderr
        invalid_check = _registrar_request(
            registry,
            session_id,
            "/spark/domain/check",
            method="POST",
            fields=list(_hidden_fields(invalid_check_form.body).items())
            + [("domains", "")],
        )
        assert invalid_check.http_status == 422, invalid_check.body
        invalid_payload = json.loads(invalid_check.body)
        assert invalid_payload.get("success") is False, invalid_payload
        assert invalid_payload.get("message") == "Exactly one domain is required."

        order_form = _registrar_request(
            registry, session_id, f"/orders/register/{ZONE}"
        )
        assert order_form.authenticated
        assert order_form.http_status == 200, order_form.stderr
        csrf = list(_hidden_fields(order_form.body).items())
        order = _registrar_request(
            registry,
            session_id,
            f"/orders/register/{ZONE}",
            method="POST",
            fields=csrf + [
                ("reg-years", "1"),
                ("authInfo", "B02a-Example-Auth-1"),
                ("nameserver[]", "ns1.example.com"),
                ("nameserver_ipv4[]", OWNER_DNS[0]),
                ("nameserver_ipv6[]", ""),
                ("nameserver[]", "ns2.example.com"),
                ("nameserver_ipv4[]", OWNER_DNS[1]),
                ("nameserver_ipv6[]", ""),
            ],
        )
        assert order.http_status == 302, order.body
        assert order.location and order.location.startswith("/invoice/")
        invoice_id = urlsplit(order.location).path.rstrip("/").rsplit("/", 1)[-1]

        payment_form = _registrar_request(
            registry, session_id, f"/invoice/{invoice_id}/pay"
        )
        assert payment_form.http_status == 200, payment_form.stderr
        assert 'value="balance"' in payment_form.body
        payment = _registrar_request(
            registry,
            session_id,
            "/balance-payment",
            method="POST",
            fields=list(_hidden_fields(payment_form.body).items())
            + [("paymentMethod", "balance")],
        )
        assert payment.http_status == 200, payment.stderr
        payment_result = json.loads(payment.body)
        assert payment_result.get("success") is True, payment_result

        services = _registrar_request(
            registry, session_id, "/api/records/services?order=id,desc&page=1,10"
        )
        assert services.http_status == 200
        service_records = json.loads(services.body).get("records", [])
        purchased = [
            record
            for record in service_records
            if json.loads(record.get("config") or "{}").get("domain") == ZONE
        ]
        assert len(purchased) == 1, service_records
        assert purchased[0].get("status") == "active", purchased[0]

        unavailable = _check_availability(registry, session_id, ZONE)
        assert unavailable.get("available") is False, unavailable
        assert unavailable.get("transferable") is not True, unavailable

        service_id = str(purchased[0]["id"])
        edit_form = _registrar_request(
            registry, session_id, f"/services/{service_id}/edit"
        )
        assert edit_form.http_status == 200, edit_form.stderr
        assert ZONE in edit_form.body
        update = _registrar_request(
            registry,
            session_id,
            f"/services/{service_id}/update",
            method="POST",
            fields=list(_hidden_fields(edit_form.body).items())
            + [("authInfo", UPDATED_AUTH_INFO)],
        )
        assert update.http_status == 302, update.body
        assert update.location == f"/services/{service_id}/edit"

        updated_services = _registrar_request(
            registry, session_id, "/api/records/services?order=id,desc&page=1,10"
        )
        assert updated_services.http_status == 200, updated_services.stderr
        updated_records = json.loads(updated_services.body).get("records", [])
        updated = [
            record for record in updated_records if str(record.get("id")) == service_id
        ]
        assert len(updated) == 1, updated_records
        updated_config = json.loads(updated[0].get("config") or "{}")
        assert updated_config.get("authcode") == UPDATED_AUTH_INFO, updated_config
    finally:
        if session_id is not None:
            _invoke(registry, "domain.registrar_request", {
                "source": SOURCE,
                "registrar_url": REGISTRAR_URL,
                "session_id": session_id,
                "path": "/",
                "close_session": True,
                "authentication": "required",
            })

    rdds_results = {}
    for _ in range(20):
        for authority in ("registrar", "registry"):
            for protocol in ("whois", "rdap"):
                rdds_results[(authority, protocol)] = _invoke(
                    registry,
                    "domain.rdds_lookup",
                    {
                        "source": SOURCE,
                        "authority": authority,
                        "protocol": protocol,
                        "domain": ZONE,
                    },
                )
        if all(result.successful and result.found for result in rdds_results.values()):
            break
        time.sleep(2)
    assert len(rdds_results) == 4
    for authority in ("registrar", "registry"):
        whois = rdds_results[(authority, "whois")]
        rdap = rdds_results[(authority, "rdap")]
        assert whois.successful and whois.found, whois.stderr or whois.body
        assert "Domain Name: EXAMPLE.COM" in whois.body, whois.body
        assert rdap.successful and rdap.found, rdap.stderr or rdap.body
        assert rdap.rdap is not None and rdap.rdap.get("ldhName") == ZONE, rdap.body

    pending_com_servers = set(COM_SERVERS)
    delegation_results = {}
    for _ in range(30):
        for com_server in tuple(pending_com_servers):
            delegation = _invoke(registry, "dns.check_delegation", {
                "source": SOURCE,
                "zone": ZONE,
                "parent_server": com_server,
                "child_servers": OWNER_DNS,
                "timeout_seconds": 3,
            })
            delegation_results[com_server] = delegation
            if delegation.consistent:
                pending_com_servers.remove(com_server)
        if not pending_com_servers:
            break
        time.sleep(3)
    assert not pending_com_servers, {
        com_server: delegation_results.get(com_server).issues
        if delegation_results.get(com_server) is not None
        else ["delegation was not checked"]
        for com_server in sorted(pending_com_servers)
    }
    for com_server in COM_SERVERS:
        delegation = delegation_results[com_server]
        assert delegation.parent_ns_names == ["ns1.example.com.", "ns2.example.com."]
        assert delegation.missing_glue_names == []

    updated_dns = _invoke(registry, "dns.configure", {
        "source": SOURCE,
        "dns_service_id": dns_service.service_id,
        "zone": ZONE,
        "changes": [{
            "name": NAME,
            "record_type": "A",
            "operation": "replace",
            "ttl": 300,
            "value": UPDATED_ANSWER,
        }],
    })
    assert updated_dns.successful, updated_dns.stderr
    assert updated_dns.primary_authoritative
    assert updated_dns.secondary_authoritative
    assert updated_dns.primary_soa == updated_dns.secondary_soa
    assert updated_dns.primary_soa != configured.primary_soa

    for owner_dns in OWNER_DNS:
        authoritative = backend.execute(
            SOURCE,
            ["dig", "+short", "+norecurse", f"@{owner_dns}", NAME, "A"],
        )
        assert authoritative.exit_code == 0, (owner_dns, authoritative)
        assert authoritative.stdout.strip() == UPDATED_ANSWER, (
            owner_dns,
            authoritative,
        )

    pending_resolvers = set(RECURSIVE_RESOLVERS)
    resolver_results = {}
    for _ in range(60):
        for resolver in tuple(pending_resolvers):
            lookup = _invoke(registry, "dns.lookup", {
                "source": SOURCE,
                "name": NAME,
                "record_type": "A",
                "server": resolver,
                "include_details": True,
            })
            resolver_results[resolver] = lookup
            if (
                lookup.command_successful
                and lookup.response_status == "NOERROR"
                and lookup.answers == [UPDATED_ANSWER]
            ):
                pending_resolvers.remove(resolver)
        if not pending_resolvers:
            break
        time.sleep(3)

    assert not pending_resolvers, {
        resolver: resolver_results.get(resolver)
        for resolver in sorted(pending_resolvers)
    }
    for resolver in RECURSIVE_RESOLVERS:
        lookup = resolver_results[resolver]
        assert lookup.command_successful, (resolver, lookup)
        assert lookup.response_status == "NOERROR", (resolver, lookup)
        assert lookup.answers == [UPDATED_ANSWER], (resolver, lookup)
