"""HTTP API smoke tests."""

from fastapi.testclient import TestClient

from seedemu_tool_service.api.dependencies import get_runtime_backend, get_tool_registry
from seedemu_tool_service.backends import RuntimeBackendError, RuntimeTargetNotFoundError
from seedemu_tool_service.main import app
from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from seedemu_tool_service.registry.registry import ToolRegistry
from seedemu_tool_service.tools.network import register_network_tools

client = TestClient(app)


class _FailingBackend:
    """Backend that raises a configured error when executing commands."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: list[str]) -> RuntimeCommandResult:
        raise self._error


def test_service_info() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "SEEDemu Agent Tool Service",
        "version": "0.1.0",
        "docs_url": "/docs",
    }


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_tool_registry_lists_network_tools() -> None:
    response = client.get("/api/v1/tools")

    assert response.status_code == 200
    body = response.json()
    names = [tool["name"] for tool in body["tools"]]
    expected_existing_tools = {
        "bgp.summary",
        "dns.compare",
        "dns.authoritative_find",
        "dns.lookup",
        "dns.reverse_lookup",
        "dns.trace",
        "dns.configure",
        "network.inspect_ip_address",
        "network.ping",
        "pki.check_certificate_expiration",
        "pki.get_certificate_fingerprint",
        "pki.inspect_certificate_extensions",
        "pki.inspect_certificate_file",
        "pki.inspect_certificate_names",
        "pki.inspect_certificate_public_key",
        "pki.inspect_remote_tls_certificate",
        "pki.verify_certificate_chain",
    }
    expected_benchmark_tools = {
        "benchmark.runtime.projects",
        "benchmark.runtime.describe",
        "benchmark.runtime.service_capabilities",
        "benchmark.topology.discover_python",
        "benchmark.topology.lifecycle",
        "operation.container.inspect",
        "operation.container.start",
        "operation.container.stop",
        "operation.dns.inspect",
        "operation.dns.probe",
        "operation.dns.set_nameserver",
        "operation.firewall.inspect_drop",
        "operation.firewall.add_drop",
        "operation.firewall.delete_drop",
        "operation.netem.inspect",
        "operation.netem.apply",
        "operation.network.probe",
    }
    assert expected_existing_tools <= set(names)
    assert expected_benchmark_tools <= set(names)
    assert body["count"] == len(names)
    bgp_summary = next(tool for tool in body["tools"] if tool["name"] == "bgp.summary")
    assert bgp_summary["domain"] == "bgp"


def test_runtime_status() -> None:
    class AvailableBackend:
        def status(self) -> RuntimeStatus:
            return RuntimeStatus(
                backend="docker",
                available=True,
                daemon_version="test-version",
            )

    app.dependency_overrides[get_runtime_backend] = AvailableBackend
    try:
        response = client.get("/api/v1/runtime")
    finally:
        app.dependency_overrides.pop(get_runtime_backend, None)

    assert response.status_code == 200
    assert response.json() == {
        "backend": "docker",
        "available": True,
        "daemon_version": "test-version",
    }


def test_invoke_tool_returns_result() -> None:
    response = client.post(
        "/api/v1/tools/network.inspect_ip_address/invoke",
        json={"address": "10.0.0.1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "network.inspect_ip_address"
    assert body["result"]["address"] == "10.0.0.1"
    assert body["result"]["is_private"] is True
    assert body["result"]["is_loopback"] is False
    assert body["duration_ms"] >= 0


def test_invoke_unknown_tool_returns_404() -> None:
    response = client.post("/api/v1/tools/no.such.tool/invoke", json={})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tool_not_found"


def test_invoke_invalid_arguments_returns_422() -> None:
    response = client.post(
        "/api/v1/tools/network.inspect_ip_address/invoke",
        json={"address": 123},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_arguments"


def test_invoke_missing_required_arguments_returns_422() -> None:
    response = client.post("/api/v1/tools/network.ping/invoke", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_arguments"


def test_invoke_backend_failure_returns_502() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, _FailingBackend(RuntimeBackendError("backend is down")))
    app.dependency_overrides[get_tool_registry] = lambda: registry
    try:
        response = client.post(
            "/api/v1/tools/network.ping/invoke",
            json={"source": "host-1", "target": "10.0.0.1"},
        )
    finally:
        app.dependency_overrides.pop(get_tool_registry, None)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_error"


def test_invoke_missing_target_returns_404() -> None:
    registry = ToolRegistry()
    register_network_tools(
        registry, _FailingBackend(RuntimeTargetNotFoundError("node not found: host-1"))
    )
    app.dependency_overrides[get_tool_registry] = lambda: registry
    try:
        response = client.post(
            "/api/v1/tools/network.ping/invoke",
            json={"source": "host-1", "target": "10.0.0.1"},
        )
    finally:
        app.dependency_overrides.pop(get_tool_registry, None)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "target_not_found"


def test_discovery_schema_drives_invocation() -> None:
    tools = client.get("/api/v1/tools").json()["tools"]
    ip_tool = next(tool for tool in tools if tool["name"] == "network.inspect_ip_address")
    assert ip_tool["input_schema"]["required"] == ["address"]

    response = client.post(
        "/api/v1/tools/network.inspect_ip_address/invoke",
        json={"address": "8.8.8.8"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["version"] == 4
    assert body["result"]["is_private"] is False
    assert body["result"]["is_global"] is True


def test_openapi_includes_public_routes() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/runtime" in paths
    assert "/api/v1/tools" in paths
    assert "/api/v1/tools/{name}/invoke" in paths
