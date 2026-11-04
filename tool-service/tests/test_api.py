"""HTTP API smoke tests."""

from fastapi.testclient import TestClient

from seedemu_tool_service.api.dependencies import get_runtime_backend
from seedemu_tool_service.main import app
from seedemu_tool_service.models.runtime import RuntimeStatus

client = TestClient(app)


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
    assert body["count"] == 27
    assert [tool["name"] for tool in body["tools"]] == [
        "bgp.summary",
        "dns.compare",
        "dns.lookup",
        "dns.reverse_lookup",
        "dns.trace",
        "dns.update",
        "network.cidr_inspect",
        "network.firewall_inspect",
        "network.firewall_update",
        "network.inspect_ip_address",
        "network.interface_inspect",
        "network.link_properties_inspect",
        "network.link_properties_update",
        "network.link_update",
        "network.listen_sockets",
        "network.neighbor_inspect",
        "network.neighbor_update",
        "network.node_networks",
        "network.packet_capture",
        "network.path_trace",
        "network.ping",
        "network.reachability_map",
        "network.route_inspect",
        "network.route_lookup",
        "network.route_update",
        "network.sysctl_update",
        "pki.inspect_certificate_file",
    ]
    assert body["tools"][0]["domain"] == "bgp"


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


def test_openapi_includes_public_routes() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
    assert "/api/v1/runtime" in response.json()["paths"]
    assert "/api/v1/tools" in response.json()["paths"]
