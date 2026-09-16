"""Docker integration tests for source-owned authoritative DNS configuration."""

import pytest

from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.dns.tools import DNSTools

SOURCE = "as150h-host_1-10.150.0.72"
UNAUTHORIZED_SOURCE = "as150h-host_0-10.150.0.71"
SERVICE_ID = "b02a.source-owned-dns"


@pytest.fixture(scope="module")
def tools() -> DNSTools:
    return DNSTools(DockerRuntimeBackend())


def test_configure_provisions_updates_and_converges(tools: DNSTools) -> None:
    result = tools.configure(
        source=SOURCE,
        dns_service_id=SERVICE_ID,
        zone="example.com",
        changes=[{
            "name": "www.example.com",
            "record_type": "A",
            "operation": "replace",
            "ttl": 300,
            "value": "192.0.2.80",
        }],
    )
    assert result.successful is True, result.stderr
    assert result.primary_authoritative is True
    assert result.secondary_authoritative is True
    assert result.primary_soa == result.secondary_soa
    assert result.primary_ns == ["ns1.example.com.", "ns2.example.com."]
    assert result.secondary_ns == result.primary_ns


def test_configure_rejects_a_source_without_the_private_identity(tools: DNSTools) -> None:
    result = tools.configure(
        source=UNAUTHORIZED_SOURCE,
        dns_service_id=SERVICE_ID,
        zone="example.com",
        changes=[],
    )
    assert result.successful is False
