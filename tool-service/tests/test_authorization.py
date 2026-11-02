"""Security tests use the real registry and token path, never the unit-test bypass."""

import hashlib
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from seedemu_tool_service.api.dependencies import get_tool_registry
from seedemu_tool_service.auth.authentication import (
    AuthenticationError,
    PolicyUnavailable,
    TokenAuthenticator,
)
from seedemu_tool_service.auth.authorization import AccessDenied
from seedemu_tool_service.auth.models import AccessPolicy
from seedemu_tool_service.main import create_app
from seedemu_tool_service.mcp import create_mcp_server
from seedemu_tool_service.models.runtime import RuntimeCommandResult
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.dns import register_dns_tools
from seedemu_tool_service.tools.network import register_network_tools
from seedemu_tool_service.tools.network.models import InspectIPAddressArguments
from seedemu_tool_service.tools.pki import register_pki_tools

A_ID = "a" * 64
B_ID = "b" * 64


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def execute(self, container, command):
        self.calls.append((container, list(command)))
        return RuntimeCommandResult(exit_code=0, stdout="", stderr="")

    def execute_as_root(self, container, command):
        return self.execute(container, command)


@pytest.fixture
def security(tmp_path):
    def identity(name, role, node):
        return {
            "agent_id": name,
            "world_id": "world",
            "role": role,
            "nodes": [node],
            "token_sha256": hashlib.sha256(name.encode()).hexdigest(),
        }

    data = {
        "agents": [
            identity("alice", "member", "node-a"),
            identity("bob", "member", "node-b"),
            identity("reader", "observer", "node-a"),
            identity("pki", "pki_operator", "node-a"),
        ],
        "nodes": [
            {"node_id": "node-a", "world_id": "world", "container_id": A_ID},
            {"node_id": "node-b", "world_id": "world", "container_id": B_ID},
        ],
        "domains": [
            {"world_id": "world", "name": "alice.test", "zone": "alice.test", "owner_id": "alice"},
            {"world_id": "world", "name": "bob.test", "zone": "bob.test", "owner_id": "bob"},
        ],
        "profiles": [],
    }
    path = tmp_path / "policy.json"

    def save():
        replacement = path.with_suffix(".new")
        replacement.write_text(json.dumps(data))
        replacement.replace(path)

    save()
    auth = TokenAuthenticator(path)
    backend = RecordingBackend()
    registry = ToolRegistry()
    register_network_tools(registry, backend)
    register_dns_tools(registry, backend)
    register_pki_tools(registry, backend)
    return data, save, auth, registry, backend, path


def invoke(registry, auth, token, tool="dns.update", **arguments):
    return anyio.run(partial(registry.invoke, tool, arguments, access=auth.authenticate(token)))


def dns_args(**updates):
    return {
        "source": "node-a",
        "zone": "alice.test",
        "name": "www.alice.test",
        "value": "192.0.2.10",
        **updates,
    }


def test_missing_registry_identity_cannot_execute(security):
    _, _, _, registry, backend, _ = security
    with pytest.raises(TypeError):
        anyio.run(registry.invoke, "dns.update", dns_args())
    assert backend.calls == []


def test_roles_hide_tools_and_reject_direct_calls(security):
    _, _, auth, registry, backend, _ = security
    tools = registry.list_tools(access=auth.authenticate("reader"))
    assert "dns.update" not in {t.name for t in tools}
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "reader", **dns_args())
    assert backend.calls == []


@pytest.mark.parametrize(
    "updates",
    [
        {"source": "node-b"},
        {"source": B_ID},
        {"source": A_ID[:12]},
        {"source": "docker-container-alias"},
        {"zone": "bob.test", "name": "www.bob.test"},
        {"zone": "alice.test", "name": "evilalice.test"},
        {"zone": "test", "name": "www.alice.test"},
        {"zone": "alice.test", "name": "alice.test.attacker.test"},
    ],
)
def test_resource_denials_have_no_backend_effect(security, updates):
    _, _, auth, registry, backend, _ = security
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "alice", **dns_args(**updates))
    assert backend.calls == []


def test_allowed_update_pins_container_and_normalizes_dns(security):
    _, _, auth, registry, backend, _ = security
    result = invoke(
        registry,
        auth,
        "alice",
        **dns_args(
            zone="ALICE.TEST.",
            name="WWW.ALICE.TEST.",
        ),
    )
    assert result.successful
    assert backend.calls[0][0] == A_ID
    assert result.zone == "alice.test"
    assert result.name == "www.alice.test"


def test_same_token_observes_purchase_transfer_and_expiration(security):
    data, save, auth, registry, backend, _ = security
    args = dns_args(zone="new.test", name="new.test")
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "alice", **args)
    data["domains"].append(
        {"world_id": "world", "name": "new.test", "zone": "new.test", "owner_id": "alice"}
    )
    save()
    invoke(registry, auth, "alice", **args)
    data["domains"][-1]["owner_id"] = "bob"
    save()
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "alice", **args)
    invoke(registry, auth, "bob", **{**args, "source": "node-b"})
    data["domains"][-1]["expires_at"] = time.time() - 1
    save()
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "bob", **{**args, "source": "node-b"})
    assert len(backend.calls) == 2


def test_delegated_child_shadows_parent_even_when_expired(security):
    data, save, auth, registry, backend, _ = security
    data["domains"].append(
        {
            "world_id": "world",
            "name": "child.alice.test",
            "zone": "alice.test",
            "owner_id": "bob",
            "expires_at": 0,
        }
    )
    save()
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "alice", **dns_args(name="www.child.alice.test"))
    assert backend.calls == []


def test_profiles_bind_all_arguments_and_node(security):
    data, save, auth, registry, backend, _ = security
    data["agents"][3]["profiles"] = ["trust-refresh"]
    data["profiles"] = [
        {
            "profile_id": "trust-refresh",
            "world_id": "world",
            "tool": "pki.update_trust_store",
            "arguments": {"source": "node-a"},
        }
    ]
    save()
    invoke(registry, auth, "pki", "pki.update_trust_store", source="node-a")
    assert backend.calls == [(A_ID, ["update-ca-certificates"])]
    for args in ({"source": "node-b"}, {"source": "node-a", "command": ["sh", "-c", "id"]}):
        with pytest.raises(AccessDenied):
            invoke(registry, auth, "pki", "pki.update_trust_store", **args)
    assert len(backend.calls) == 1


def test_file_profile_rejects_path_replacement(security):
    data, save, auth, registry, backend, _ = security
    data["agents"][3]["profiles"] = ["certificate-read"]
    data["profiles"] = [
        {
            "profile_id": "certificate-read",
            "world_id": "world",
            "tool": "pki.inspect_certificate_file",
            "arguments": {"source": "node-a", "path": "/certs/service.pem"},
        }
    ]
    save()
    with pytest.raises(AccessDenied):
        invoke(
            registry,
            auth,
            "pki",
            "pki.inspect_certificate_file",
            source="node-a",
            path="/certs/../private/key.pem",
        )
    assert backend.calls == []


def test_unknown_registered_tool_is_denied(security):
    _, _, auth, registry, _, _ = security
    calls = []
    registry.register(
        ToolDefinition(name="future.danger", domain="future", description="test"),
        lambda **kw: calls.append(kw),
        InspectIPAddressArguments,
    )
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "alice", "future.danger", address="192.0.2.10")
    assert calls == []


def test_identity_cannot_be_supplied_as_tool_arguments(security):
    _, _, auth, registry, backend, _ = security
    with pytest.raises(ValueError, match="Unexpected"):
        invoke(registry, auth, "alice", **dns_args(role="ca_operator"))
    assert backend.calls == []


def test_revocation_and_broken_policy_fail_closed(security):
    data, save, auth, _, _, path = security
    auth.authenticate("alice")
    data["agents"][0]["enabled"] = False
    save()
    with pytest.raises(AuthenticationError):
        auth.authenticate("alice")
    path.write_text("{bad json")
    with pytest.raises(PolicyUnavailable):
        auth.authenticate("bob")
    path.unlink()
    with pytest.raises(PolicyUnavailable):
        auth.authenticate("bob")


@pytest.mark.parametrize("change", ["duplicate_token", "cross_world", "duplicate_container"])
def test_invalid_policy_rejected(security, change):
    data, _, _, _, _, _ = security
    if change == "duplicate_token":
        data["agents"][1]["token_sha256"] = data["agents"][0]["token_sha256"]
    elif change == "cross_world":
        data["nodes"][0]["world_id"] = "other-world"
    else:
        data["nodes"][1]["container_id"] = A_ID
    with pytest.raises(ValidationError):
        AccessPolicy.model_validate(data)


def test_rest_and_mcp_enforce_the_same_access(security, monkeypatch):
    _, _, auth, registry, backend, _ = security
    monkeypatch.setattr("seedemu_tool_service.main.get_tool_registry", lambda: registry)
    app = create_app(authenticator=auth)
    app.dependency_overrides[get_tool_registry] = lambda: registry
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/v1/tools").status_code == 401
        assert client.post("/mcp", json={}).status_code == 401
        assert client.get("/api/v1/runtime").status_code == 401
        headers = {"Authorization": "Bearer reader"}
        response = client.post("/api/v1/tools/dns.update/invoke", json=dns_args(), headers=headers)
        assert response.status_code == 403
        mcp_headers = {
            **headers,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }
        response = client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "dns.update", "arguments": dns_args()},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["isError"] is True
        assert "not authorized" in response.json()["result"]["content"][0]["text"]
        listed = client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert "dns.update" not in names
        assert "dns.lookup" in names
        ok = client.post(
            "/mcp",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "network.inspect_ip_address",
                    "arguments": {"address": "192.0.2.1"},
                },
            },
        )
        assert ok.json()["result"]["isError"] is False
        assert backend.calls == []
        # Reuse the same HTTP connection with different credentials; no identity sticks.
        for token, denied in (("alice", False), ("bob", True), ("reader", True)):
            response = client.post(
                "/mcp",
                headers={
                    **mcp_headers,
                    "Authorization": f"Bearer {token}",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "dns.update", "arguments": dns_args()},
                },
            )
            assert response.json()["result"]["isError"] is denied
    assert len(backend.calls) == 1
    assert backend.calls[0][0] == A_ID


def test_http_concurrent_identities_do_not_bleed(security):
    _, _, auth, registry, backend, _ = security
    app = create_app(authenticator=auth)
    app.dependency_overrides[get_tool_registry] = lambda: registry
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:

        def call(token):
            response = client.post(
                "/api/v1/tools/dns.update/invoke",
                json=dns_args(),
                headers={"Authorization": f"Bearer {token}"},
            )
            return token, response.status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, ["alice", "bob", "reader", "alice"] * 3))
    assert all(status == (200 if token == "alice" else 403) for token, status in results)
    assert len(backend.calls) == 6
    assert all(container == A_ID for container, _ in backend.calls)


def test_stdio_style_identity_provider_checks_revocation(security):
    data, save, auth, registry, backend, _ = security

    async def exercise():
        server = create_mcp_server(registry, access_provider=lambda: auth.authenticate("alice"))
        async with Client(server) as client:
            result = await client.call_tool("dns.update", dns_args())
            assert not result.is_error
            data["agents"][0]["enabled"] = False
            save()
            result = await client.call_tool("dns.update", dns_args())
            assert result.is_error

    anyio.run(exercise)
    assert len(backend.calls) == 1


def test_audit_contains_decision_not_credentials(security, caplog):
    _, _, auth, registry, _, _ = security
    with caplog.at_level(logging.INFO, logger="seedemu.auth.audit"):
        with pytest.raises(AccessDenied):
            invoke(registry, auth, "reader", **dns_args())
    record = next(record for record in caplog.records if record.name == "seedemu.auth.audit")
    assert record.agent_id == "reader"
    assert record.outcome == "denied"
    assert record.tool == "dns.update"
    assert "token" not in record.__dict__


@pytest.mark.parametrize("path", ["/mcp", "/api/v1/tools", "/api/v1/runtime"])
def test_http_rejects_invalid_and_duplicate_credentials(security, path):
    _, _, auth, _, _, _ = security
    with TestClient(create_app(authenticator=auth)) as client:
        for value in ("Basic alice", "Bearer wrong", "Bearer", "Bearer alice extra"):
            response = client.post(path, headers={"Authorization": value}, json={})
            assert response.status_code == 401
        response = client.post(
            path,
            headers=[
                ("Authorization", "Bearer alice"),
                ("Authorization", "Bearer bob"),
            ],
            json={},
        )
        assert response.status_code == 401


def test_http_reloads_policy_and_keeps_health_public(security):
    data, save, auth, _, _, path = security
    with TestClient(create_app(authenticator=auth)) as client:
        headers = {"Authorization": "Bearer alice"}
        assert client.get("/api/v1/tools", headers=headers).status_code == 200
        data["agents"][0]["enabled"] = False
        save()
        assert client.get("/api/v1/tools", headers=headers).status_code == 401
        path.write_text("broken")
        assert client.get("/api/v1/tools", headers=headers).status_code == 503
        assert client.get("/api/v1/health").status_code == 200


def test_unconfigured_service_fails_closed(monkeypatch):
    monkeypatch.delenv("SEEDEMU_AUTH_POLICY", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tools", headers={"Authorization": "Bearer anything"})
        assert response.status_code == 503


def test_mcp_without_bound_identity_cannot_invoke(security):
    _, _, _, registry, backend, _ = security

    async def exercise():
        async with Client(create_mcp_server(registry)) as client:
            result = await client.call_tool("dns.update", dns_args())
            assert result.is_error

    anyio.run(exercise)
    assert backend.calls == []


def test_role_and_profiles_both_required(security):
    data, save, auth, registry, backend, _ = security
    # Having the pki_operator role alone does not grant file/command access.
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "pki", "pki.update_trust_store", source="node-a")
    data["agents"][2]["profiles"] = ["refresh"]  # reader remains observer
    data["profiles"] = [
        {
            "profile_id": "refresh",
            "world_id": "world",
            "tool": "pki.update_trust_store",
            "arguments": {"source": "node-a"},
        }
    ]
    save()
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "reader", "pki.update_trust_store", source="node-a")
    assert backend.calls == []


def test_profile_cannot_enable_custom_command(security):
    data, save, auth, registry, backend, _ = security
    data["agents"][3]["profiles"] = ["custom-command"]
    arguments = {"source": "node-a", "command": ["sh", "-c", "id"]}
    data["profiles"] = [
        {
            "profile_id": "custom-command",
            "world_id": "world",
            "tool": "pki.update_trust_store",
            "arguments": arguments,
        }
    ]
    save()
    with pytest.raises(AccessDenied):
        invoke(registry, auth, "pki", "pki.update_trust_store", **arguments)
    assert backend.calls == []


def test_real_stdio_process_uses_fixed_token(security):
    data, save, _, _, _, policy_path = security

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "seedemu_tool_service.mcp"],
            env={"SEEDEMU_AUTH_POLICY": str(policy_path), "SEEDEMU_AGENT_TOKEN": "reader"},
        )
        with anyio.fail_after(15):
            async with Client(params) as client:
                tools = await client.list_tools()
                assert "dns.update" not in {tool.name for tool in tools.tools}
                result = await client.call_tool(
                    "network.inspect_ip_address",
                    {
                        "address": "192.0.2.1",
                    },
                )
                assert not result.is_error
                data["agents"][2]["enabled"] = False
                save()
                result = await client.call_tool(
                    "network.inspect_ip_address",
                    {
                        "address": "192.0.2.1",
                    },
                )
                assert result.is_error

    anyio.run(exercise)
