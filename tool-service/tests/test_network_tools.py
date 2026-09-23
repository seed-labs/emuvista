"""Network-domain tool tests."""

import json
from collections.abc import Sequence

import anyio
import pytest
from pydantic import ValidationError

from seedemu_tool_service.models.runtime import RuntimeCommandResult, RuntimeStatus
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.network import register_network_tools


class FakeRuntimeBackend:
    def __init__(
        self,
        exit_code: int = 0,
        stdout: str = "ping output",
        stderr: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.container: str | None = None
        self.command: list[str] | None = None

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.command = list(command)
        return RuntimeCommandResult(
            exit_code=self.exit_code,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def test_network_domain_registers_its_tools() -> None:
    registry = ToolRegistry()

    register_network_tools(registry, FakeRuntimeBackend())

    definitions = registry.list_tools()
    assert [tool.name for tool in definitions] == [
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
    ]
    assert definitions[0].domain == "network"
    assert "network" in definitions[0].input_schema["properties"]
    assert "contains" in definitions[0].input_schema["properties"]
    assert "source" in definitions[1].input_schema["properties"]
    assert "table" in definitions[1].input_schema["properties"]
    assert "include_raw_output" in definitions[1].input_schema["properties"]
    assert "source" in definitions[2].input_schema["properties"]
    assert "action" in definitions[2].input_schema["properties"]
    assert "chain" in definitions[2].input_schema["properties"]
    assert "rule" in definitions[2].input_schema["properties"]
    assert "address" in definitions[3].input_schema["properties"]
    assert "source" in definitions[4].input_schema["properties"]
    assert "include_raw_output" in definitions[4].input_schema["properties"]
    assert "source" in definitions[5].input_schema["properties"]
    assert "include_raw_output" in definitions[5].input_schema["properties"]
    assert "source" in definitions[6].input_schema["properties"]
    assert "interface" in definitions[6].input_schema["properties"]
    assert "latency" in definitions[6].input_schema["properties"]
    assert "bandwidth" in definitions[6].input_schema["properties"]
    assert "drop" in definitions[6].input_schema["properties"]
    assert "source" in definitions[7].input_schema["properties"]
    assert "interface" in definitions[7].input_schema["properties"]
    assert "state" in definitions[7].input_schema["properties"]
    assert "source" in definitions[8].input_schema["properties"]
    assert "include_raw_output" in definitions[8].input_schema["properties"]
    assert "source" in definitions[9].input_schema["properties"]
    assert "include_raw_output" in definitions[9].input_schema["properties"]
    assert "source" in definitions[10].input_schema["properties"]
    assert "operation" in definitions[10].input_schema["properties"]
    assert "destination" in definitions[10].input_schema["properties"]
    assert "lladdr" in definitions[10].input_schema["properties"]
    assert "source" in definitions[11].input_schema["properties"]
    assert "include_raw_output" in definitions[11].input_schema["properties"]
    assert "source" in definitions[12].input_schema["properties"]
    assert "interface" in definitions[12].input_schema["properties"]
    assert "filter_expression" in definitions[12].input_schema["properties"]
    assert "source" in definitions[13].input_schema["properties"]
    assert "target" in definitions[13].input_schema["properties"]
    assert definitions[13].input_schema["properties"]["count"]["maximum"] == 20
    assert definitions[13].input_schema["properties"]["count"]["default"] == 5
    assert "source" in definitions[14].input_schema["properties"]
    assert "target" in definitions[14].input_schema["properties"]
    assert definitions[14].input_schema["properties"]["count"]["maximum"] == 10
    assert definitions[14].input_schema["properties"]["count"]["default"] == 3
    assert "sources" in definitions[15].input_schema["properties"]
    assert "targets" in definitions[15].input_schema["properties"]
    assert "source" in definitions[16].input_schema["properties"]
    assert "source" in definitions[17].input_schema["properties"]
    assert "destination" in definitions[17].input_schema["properties"]
    assert "source" in definitions[18].input_schema["properties"]
    assert "operation" in definitions[18].input_schema["properties"]
    assert "destination" in definitions[18].input_schema["properties"]
    assert "source" in definitions[19].input_schema["properties"]
    assert "key" in definitions[19].input_schema["properties"]
    assert "value" in definitions[19].input_schema["properties"]


def test_inspect_ip_address_bound_method() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    result = anyio.run(
        registry.invoke,
        "network.inspect_ip_address",
        {"address": "2001:0db8::1"},
    )

    assert result.address == "2001:db8::1"
    assert result.version == 6


def test_ping_reports_reachable_host() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.ping",
        {
            "source": "as150-host-0",
            "target": "10.150.0.71",
            "count": 2,
            "timeout_seconds": 4,
        },
    )

    assert result.reachable is True
    assert backend.container == "as150-host-0"
    assert backend.command == ["ping", "-c", "2", "-W", "4", "10.150.0.71"]


def test_ping_reports_unreachable_host() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend(exit_code=1))

    result = anyio.run(
        registry.invoke,
        "network.ping",
        {"source": "source", "target": "192.0.2.1"},
    )

    assert result.reachable is False
    assert result.exit_code == 1


def test_ping_arguments_are_validated_before_execution() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.ping",
            {"source": "source", "target": "target", "count": 0},
        )


def test_route_inspect_parses_routing_table() -> None:
    backend = FakeRuntimeBackend(
        exit_code=0,
        stdout=(
            "default via 10.150.0.1 dev eth0\n"
            "10.150.0.0/24 dev eth0 proto kernel scope link src 10.150.0.71\n"
            "192.168.1.0/24 via 10.150.0.1 dev eth0\n"
        ),
    )
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_inspect",
        {"source": "as150-host-0"},
    )

    assert backend.command == ["ip", "route", "show"]
    assert result.successful is True
    assert result.exit_code == 0
    assert len(result.routes) == 3
    assert result.routes[0].destination == "default"
    assert result.routes[0].gateway == "10.150.0.1"
    assert result.routes[0].interface == "eth0"
    assert result.routes[1].interface == "eth0"
    assert result.routes[1].source == "10.150.0.71"
    assert result.routes[2].destination == "192.168.1.0/24"
    assert result.routes[2].gateway == "10.150.0.1"


def test_route_inspect_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_inspect",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.exit_code == 1
    assert result.routes == []


GOLDEN_INTERFACES = [
    {
        "ifname": "lo",
        "flags": ["LOOPBACK", "UP"],
        "mtu": 65536,
        "addr_info": [
            {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"},
        ],
    },
    {
        "ifname": "net0",
        "flags": ["BROADCAST", "UP", "LOWER_UP"],
        "mtu": 1500,
        "link_type": "ether",
        "address": "02:42:0a:97:00:47",
        "addr_info": [
            {
                "family": "inet",
                "local": "10.151.0.71",
                "prefixlen": 24,
                "broadcast": "10.151.0.255",
                "scope": "global",
            },
            {
                "family": "inet6",
                "local": "fe80::42:aff:fe97:47",
                "prefixlen": 64,
                "scope": "link",
            },
        ],
    },
]


def test_interface_inspect_parses_interfaces() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=json.dumps(GOLDEN_INTERFACES))
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.interface_inspect",
        {"source": "as150-host-0"},
    )

    assert backend.command == ["ip", "-j", "addr", "show"]
    assert result.successful is True
    assert result.parse_failed is False
    assert len(result.interfaces) == 2

    loopback = result.interfaces[0]
    assert loopback.name == "lo"
    assert loopback.up is True
    assert loopback.mac_address is None
    assert len(loopback.addresses) == 1
    assert loopback.addresses[0].local == "127.0.0.1"
    assert loopback.addresses[0].scope == "host"

    ethernet = result.interfaces[1]
    assert ethernet.name == "net0"
    assert ethernet.up is True
    assert ethernet.mtu == 1500
    assert ethernet.mac_address == "02:42:0a:97:00:47"
    assert len(ethernet.addresses) == 2
    assert ethernet.addresses[0].family == "inet"
    assert ethernet.addresses[0].local == "10.151.0.71"
    assert ethernet.addresses[0].prefixlen == 24
    assert ethernet.addresses[0].scope == "global"
    assert ethernet.addresses[1].family == "inet6"


def test_interface_inspect_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.interface_inspect",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.exit_code == 1
    assert result.parse_failed is False
    assert result.interfaces == []


def test_interface_inspect_reports_parse_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="not valid json")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.interface_inspect",
        {"source": "source"},
    )

    assert result.successful is True
    assert result.parse_failed is True
    assert result.interfaces == []


def test_interface_inspect_includes_raw_output_on_request() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=json.dumps(GOLDEN_INTERFACES))
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.interface_inspect",
        {"source": "source", "include_raw_output": True},
    )

    assert result.raw_output == json.dumps(GOLDEN_INTERFACES)


def test_interface_inspect_arguments_are_validated_before_execution() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.interface_inspect",
            {"source": "source", "bogus": True},
        )


GOLDEN_NEIGHBORS = [
    {
        "dst": "10.151.0.254",
        "lladdr": "02:42:0a:97:00:fe",
        "dev": "net0",
        "state": ["REACHABLE"],
        "flags": [],
    },
    {
        "dst": "10.151.0.71",
        "lladdr": "02:42:0a:97:00:47",
        "dev": "net0",
        "state": ["PERMANENT"],
        "flags": [],
    },
    {
        "dst": "fe80::1",
        "dev": "net0",
        "state": ["FAILED"],
        "flags": ["router"],
    },
]


def test_neighbor_inspect_parses_entries() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=json.dumps(GOLDEN_NEIGHBORS))
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.neighbor_inspect",
        {"source": "as150-host-0"},
    )

    assert backend.command == ["ip", "-j", "neigh", "show"]
    assert result.successful is True
    assert result.parse_failed is False
    assert len(result.entries) == 3
    assert result.entries[0].destination == "10.151.0.254"
    assert result.entries[0].lladdr == "02:42:0a:97:00:fe"
    assert result.entries[0].state == ["REACHABLE"]
    assert result.entries[0].is_router is False
    assert result.entries[2].lladdr is None
    assert result.entries[2].state == ["FAILED"]
    assert result.entries[2].is_router is True


def test_neighbor_inspect_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.neighbor_inspect",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.exit_code == 1
    assert result.entries == []


def test_neighbor_inspect_reports_parse_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="not json")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.neighbor_inspect",
        {"source": "source"},
    )

    assert result.successful is True
    assert result.parse_failed is True
    assert result.entries == []


def test_neighbor_inspect_reports_empty_table() -> None:
    """An idle host has no neighbors: empty but successful, not a failure."""
    backend = FakeRuntimeBackend(exit_code=0, stdout="[]")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.neighbor_inspect",
        {"source": "source"},
    )

    assert result.successful is True
    assert result.parse_failed is False
    assert result.entries == []


def test_neighbor_inspect_arguments_are_validated_before_execution() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.neighbor_inspect",
            {"source": "source", "bogus": True},
        )


def test_route_lookup_resolves_unicast_route() -> None:
    backend = FakeRuntimeBackend(
        exit_code=0,
        stdout="8.8.8.8 via 10.151.0.254 dev net0 src 10.151.0.71 uid 0\n    cache\n",
    )
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_lookup",
        {"source": "as150-host-0", "destination": "8.8.8.8"},
    )

    assert backend.command == ["ip", "route", "get", "8.8.8.8"]
    assert result.successful is True
    assert result.reachable is True
    assert result.route_type == "unicast"
    assert result.gateway == "10.151.0.254"
    assert result.interface == "net0"
    assert result.source_address == "10.151.0.71"


def test_route_lookup_reports_unreachable_destination() -> None:
    backend = FakeRuntimeBackend(exit_code=2, stdout="unreachable 192.0.2.1\n")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_lookup",
        {"source": "source", "destination": "192.0.2.1"},
    )

    assert result.successful is False
    assert result.exit_code == 2
    assert result.reachable is False
    assert result.route_type == "unreachable"


def test_route_lookup_reports_unreachable_via_stderr() -> None:
    """Some iproute2 versions report an unreachable destination on stderr only."""
    backend = FakeRuntimeBackend(
        exit_code=2,
        stdout="",
        stderr="RTNETLINK answers: Network is unreachable\n",
    )
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_lookup",
        {"source": "source", "destination": "192.0.2.1"},
    )

    assert result.successful is False
    assert result.exit_code == 2
    assert result.reachable is False
    assert result.route_type == "unreachable"


def test_route_lookup_reports_local_address() -> None:
    backend = FakeRuntimeBackend(
        exit_code=0,
        stdout="local 10.151.0.71 dev lo src 10.151.0.71 uid 0\n    cache\n",
    )
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_lookup",
        {"source": "source", "destination": "10.151.0.71"},
    )

    assert result.route_type == "local"
    assert result.reachable is True
    assert result.interface == "lo"


def test_route_lookup_validates_destination() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.route_lookup",
            {"source": "source", "destination": "not-an-ip"},
        )


def test_route_lookup_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_lookup",
        {"source": "source", "destination": "192.0.2.1"},
    )

    assert result.successful is False
    assert result.reachable is False
    assert result.route_type is None


GOLDEN_TRACE_REPORT = (
    "Start: 2024-05-20T03:02:14+0000\n"
    "HOST: as150-host-0                   Loss%   Snt   Last   Avg  Best  Wrst StDev\n"
    "  1.|-- 10.150.0.254                  0.0%     5    1.1   1.2   0.9   2.0   0.3\n"
    "  2.|-- 10.150.1.1                    0.0%     5    2.2   2.0   1.8   2.6   0.2\n"
)


def test_path_trace_parses_report() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_TRACE_REPORT)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.path_trace",
        {"source": "as150-host-0", "target": "10.150.1.1", "count": 5},
    )

    assert backend.command == ["mtr", "--report", "-c", "5", "--no-dns", "10.150.1.1"]
    assert result.successful is True
    assert result.target_reached is True
    assert len(result.hops) == 2
    assert result.hops[0].hop == 1
    assert result.hops[0].host == "10.150.0.254"
    assert result.hops[0].loss_percent == 0.0
    assert result.hops[0].sent == 5
    assert result.hops[0].avg_ms == 1.2
    assert result.hops[1].hop == 2
    assert result.hops[1].host == "10.150.1.1"
    assert result.raw_output == GOLDEN_TRACE_REPORT


def test_path_trace_reports_unreached_target() -> None:
    report = (
        "Start: 2024-05-20T03:02:14+0000\n"
        "HOST: as150-host-0                   Loss%   Snt   Last   Avg  Best  Wrst StDev\n"
        "  1.|-- 10.150.0.254                  0.0%     5    1.1   1.2   0.9   2.0   0.3\n"
        "  2.|-- ???                          100.0%     5    0.0   0.0   0.0   0.0   0.0\n"
    )
    backend = FakeRuntimeBackend(exit_code=0, stdout=report)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.path_trace",
        {"source": "source", "target": "10.150.1.1"},
    )

    assert result.successful is True
    assert result.target_reached is False
    assert len(result.hops) == 2
    assert result.hops[1].host is None
    assert result.hops[1].loss_percent == 100.0


def test_path_trace_validates_count() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.path_trace",
            {"source": "source", "target": "10.150.1.1", "count": 0},
        )


def test_path_trace_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.path_trace",
        {"source": "source", "target": "10.150.1.1"},
    )

    assert result.successful is False
    assert result.target_reached is False
    assert result.hops == []


GOLDEN_SS_OUTPUT = """Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
tcp LISTEN 0 4096 0.0.0.0:53 0.0.0.0:* users:(("named",pid=123,fd=20))
tcp LISTEN 0 128 127.0.0.1:53 0.0.0.0:* users:(("named",pid=123,fd=21))
udp UNCONN 0 0 0.0.0.0:53 0.0.0.0:* users:(("named",pid=123,fd=512))
tcp LISTEN 0 128 [::]:80 [::]:* users:(("nginx",pid=456,fd=6))
"""


def test_listen_sockets_parses_output() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_SS_OUTPUT)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.listen_sockets",
        {"source": "as150-host-0"},
    )

    assert backend.command == ["ss", "-tulnp"]
    assert result.successful is True
    assert len(result.sockets) == 4

    first = result.sockets[0]
    assert first.netid == "tcp"
    assert first.state == "LISTEN"
    assert first.local_address == "0.0.0.0"
    assert first.local_port == "53"
    assert first.process_name == "named"
    assert first.pid == 123

    ipv6 = result.sockets[3]
    assert ipv6.local_address == "::"
    assert ipv6.local_port == "80"
    assert ipv6.process_name == "nginx"
    assert ipv6.pid == 456


def test_listen_sockets_without_process_info() -> None:
    output = (
        "Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
        "tcp LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*\n"
    )
    backend = FakeRuntimeBackend(exit_code=0, stdout=output)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.listen_sockets",
        {"source": "source"},
    )

    assert len(result.sockets) == 1
    assert result.sockets[0].local_port == "8080"
    assert result.sockets[0].process_name is None
    assert result.sockets[0].pid is None


def test_listen_sockets_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.listen_sockets",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.exit_code == 1
    assert result.sockets == []


def test_listen_sockets_arguments_are_validated_before_execution() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.listen_sockets",
            {"source": "source", "bogus": True},
        )

def test_cidr_inspect_reports_ipv4_network() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    result = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.151.0.0/24"},
    )

    assert result.network == "10.151.0.0/24"
    assert result.version == 4
    assert result.prefixlen == 24
    assert result.netmask == "255.255.255.0"
    assert result.broadcast == "10.151.0.255"
    assert result.num_addresses == 256
    assert result.num_hosts == 254
    assert result.first_host == "10.151.0.1"
    assert result.last_host == "10.151.0.254"
    assert result.is_private is True
    assert result.is_global is False
    assert result.contains_result is None


def test_cidr_inspect_masks_host_bits() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    result = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.151.0.77/24"},
    )

    assert result.network == "10.151.0.0/24"


def test_cidr_inspect_reports_ipv6_network() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    result = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "2001:db8::/64"},
    )

    assert result.version == 6
    assert result.netmask == "ffff:ffff:ffff:ffff::"
    assert result.broadcast is None
    assert result.num_hosts is None
    assert result.first_host == "2001:db8::"
    assert result.last_host == "2001:db8::ffff:ffff:ffff:ffff"
    assert result.is_private is True
    assert result.is_global is False


def test_cidr_inspect_handles_point_to_point_prefixes() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    p2p = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.0.0.0/31"},
    )
    assert p2p.num_hosts == 2
    assert p2p.first_host == "10.0.0.0"
    assert p2p.last_host == "10.0.0.1"

    single = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.0.0.1/32"},
    )
    assert single.num_hosts == 1
    assert single.first_host == "10.0.0.1"
    assert single.last_host == "10.0.0.1"


def test_cidr_inspect_checks_address_membership() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    inside = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.0.0.0/24", "contains": "10.0.0.7"},
    )
    assert inside.contains_type == "address"
    assert inside.contains_result is True

    outside = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.0.0.0/24", "contains": "10.0.1.7"},
    )
    assert outside.contains_type == "address"
    assert outside.contains_result is False


def test_cidr_inspect_checks_subnet_membership() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    subnet = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.0.0.0/24", "contains": "10.0.0.0/25"},
    )
    assert subnet.contains_type == "network"
    assert subnet.contains_result is True

    outside = anyio.run(
        registry.invoke,
        "network.cidr_inspect",
        {"network": "10.0.0.0/24", "contains": "10.0.1.0/25"},
    )
    assert outside.contains_type == "network"
    assert outside.contains_result is False


def test_cidr_inspect_validates_network_argument() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.cidr_inspect",
            {"network": "not-a-cidr"},
        )


def test_cidr_inspect_validates_contains_argument() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.cidr_inspect",
            {"network": "10.0.0.0/24", "contains": "bogus"},
        )


GOLDEN_IFINFO = "net0:10.151.0.0/24:10ms:100mbit:0%\nnet1:10.152.0.0/24:5ms:10mbit:0.1%\n"


def test_node_networks_parses_ifinfo() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_IFINFO)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.node_networks",
        {"source": "as151-host-0"},
    )

    assert backend.command == ["cat", "/ifinfo.txt"]
    assert result.successful is True
    assert result.parse_failed is False
    assert len(result.networks) == 2

    first = result.networks[0]
    assert first.name == "net0"
    assert first.prefix == "10.151.0.0/24"
    assert first.latency == "10ms"
    assert first.bandwidth == "100mbit"
    assert first.drop == "0%"

    second = result.networks[1]
    assert second.name == "net1"
    assert second.drop == "0.1%"


def test_node_networks_tolerates_missing_fields() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="net0:10.151.0.0/24\nnet1\n\n")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.node_networks",
        {"source": "source"},
    )

    assert len(result.networks) == 2
    assert result.networks[0].prefix == "10.151.0.0/24"
    assert result.networks[0].latency is None
    assert result.networks[0].bandwidth is None
    assert result.networks[0].drop is None
    assert result.networks[1].name == "net1"
    assert result.networks[1].prefix is None
    assert result.parse_failed is False


def test_node_networks_reports_parse_failed() -> None:
    # 一行都解析不出来（网络名称为空）→ 格式不识别
    backend = FakeRuntimeBackend(exit_code=0, stdout=":")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.node_networks",
        {"source": "source"},
    )

    assert result.parse_failed is True
    assert result.networks == []


def test_node_networks_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(
        exit_code=1,
        stderr="cat: /ifinfo.txt: No such file or directory",
    )
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.node_networks",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.exit_code == 1
    assert result.parse_failed is False
    assert result.networks == []


def test_node_networks_includes_raw_output() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_IFINFO)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.node_networks",
        {"source": "source", "include_raw_output": True},
    )

    assert result.raw_output == GOLDEN_IFINFO


GOLDEN_QDISC = (
    "qdisc noqueue 0: dev lo root refcnt 2 \n"
    "qdisc tbf 1: dev net0 root refcnt 2 rate 100Mbit burst 2000b lat 400.0ms \n"
    "qdisc netem 8002: dev net0 parent 1:1 limit 1000 delay 10.0ms loss 0.1% \n"
)


def test_link_properties_inspect_parses_qdiscs() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_QDISC)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_inspect",
        {"source": "as151-host-0"},
    )

    assert backend.command == ["tc", "qdisc", "show"]
    assert result.successful is True
    assert len(result.interfaces) == 2

    lo = result.interfaces[0]
    assert lo.interface == "lo"
    assert len(lo.qdiscs) == 1
    assert lo.qdiscs[0].kind == "noqueue"

    net0 = result.interfaces[1]
    assert net0.interface == "net0"
    assert len(net0.qdiscs) == 2

    tbf = net0.qdiscs[0]
    assert tbf.kind == "tbf"
    assert tbf.handle == "1"
    assert tbf.parent == "root"
    assert tbf.rate == "100Mbit"
    assert tbf.burst == "2000b"
    assert tbf.delay is None
    assert tbf.loss is None

    netem = net0.qdiscs[1]
    assert netem.kind == "netem"
    assert netem.handle == "8002"
    assert netem.parent == "1:1"
    assert netem.limit == "1000"
    assert netem.delay == "10.0ms"
    assert netem.loss == "0.1%"
    assert netem.rate is None


def test_link_properties_inspect_ignores_unknown_params() -> None:
    output = (
        "qdisc fq_codel 0: dev eth0 root refcnt 2 limit 10240p flows 1024 "
        "quantum 1514 target 5ms interval 100ms memory_limit 32Mb ecn "
        "drop_batch 64\n"
    )
    backend = FakeRuntimeBackend(exit_code=0, stdout=output)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_inspect",
        {"source": "source"},
    )

    assert len(result.interfaces) == 1
    qdisc = result.interfaces[0].qdiscs[0]
    assert qdisc.kind == "fq_codel"
    assert qdisc.limit == "10240p"
    assert qdisc.delay is None
    assert qdisc.loss is None


def test_link_properties_inspect_reports_command_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=1, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_inspect",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.exit_code == 1
    assert result.interfaces == []


def test_link_properties_inspect_empty_output() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_inspect",
        {"source": "source"},
    )

    assert result.successful is True
    assert result.interfaces == []


def test_link_properties_inspect_includes_raw_output() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_QDISC)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_inspect",
        {"source": "source", "include_raw_output": True},
    )

    assert result.raw_output == GOLDEN_QDISC

class QueueRuntimeBackend:
    """按调用顺序吐出预设响应的后端（写操作先读后写、批量探测等场景用）。"""

    def __init__(self, responses: list[tuple[int, str, str]]) -> None:
        self.responses = list(responses)
        self.container: str | None = None
        self.commands: list[list[str]] = []

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(backend="fake", available=True)

    def execute(self, container: str, command: Sequence[str]) -> RuntimeCommandResult:
        self.container = container
        self.commands.append(list(command))
        exit_code, stdout, stderr = self.responses.pop(0)
        return RuntimeCommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)


def test_route_update_adds_unicast_route() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_update",
        {
            "source": "as151h-host0-10.151.0.71",
            "operation": "add",
            "destination": "10.99.0.0/24",
            "gateway": "10.151.0.254",
            "interface": "net0",
        },
    )

    assert backend.command == [
        "ip", "route", "add", "10.99.0.0/24",
        "via", "10.151.0.254", "dev", "net0",
    ]
    assert result.successful is True
    assert result.route_type == "unicast"


def test_route_update_adds_blackhole_route() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_update",
        {"source": "source", "operation": "add", "destination": "10.99.0.0/24", "route_type": "blackhole"},
    )

    assert backend.command == ["ip", "route", "add", "blackhole", "10.99.0.0/24"]
    assert result.successful is True


def test_route_update_deletes_route() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_update",
        {"source": "source", "operation": "del", "destination": "10.99.0.0/24"},
    )

    assert backend.command == ["ip", "route", "del", "10.99.0.0/24"]
    assert result.successful is True


def test_route_update_supports_default_route() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_update",
        {"source": "source", "operation": "add", "destination": "default", "gateway": "10.0.0.1"},
    )

    assert backend.command == ["ip", "route", "add", "default", "via", "10.0.0.1"]


def test_route_update_reports_failure() -> None:
    backend = FakeRuntimeBackend(exit_code=2, stderr="RTNETLINK answers: File exists")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.route_update",
        {"source": "source", "operation": "add", "destination": "10.99.0.0/24", "gateway": "10.0.0.1"},
    )

    assert result.successful is False
    assert result.exit_code == 2
    assert "File exists" in result.stderr


def test_route_update_validates_unicast_add_needs_nexthop() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.route_update",
            {"source": "source", "operation": "add", "destination": "10.99.0.0/24"},
        )


def test_route_update_validates_blackhole_without_gateway() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.route_update",
            {"source": "source", "operation": "add", "destination": "10.99.0.0/24", "route_type": "blackhole", "gateway": "10.0.0.1"},
        )


def test_route_update_validates_destination() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.route_update",
            {"source": "source", "operation": "add", "destination": "not-a-cidr", "gateway": "10.0.0.1"},
        )


def test_link_update_sets_interface_down() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_update",
        {"source": "source", "interface": "net0", "state": "down"},
    )

    assert backend.command == ["ip", "link", "set", "net0", "down"]
    assert result.successful is True
    assert result.state == "down"

def test_link_properties_update_replaces_tbf_bandwidth() -> None:
    # 读到的当前状态有 tbf（rate=100Mbit, burst=2000b）；只改 bandwidth → 1 条 replace
    backend = QueueRuntimeBackend([
        (0, GOLDEN_QDISC, ""),
        (0, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_update",
        {"source": "as151-host-0", "interface": "net0", "bandwidth": "50Mbit"},
    )

    assert backend.commands[0] == ["tc", "qdisc", "show"]
    assert result.successful is True
    assert len(result.executed) == 1
    assert result.executed[0].command == [
        "tc", "qdisc", "replace", "dev", "net0", "root", "handle", "1:",
        "tbf", "rate", "50Mbit", "burst", "2000b", "latency", "400.0ms",
    ]
    assert result.effective.rate == "50Mbit"
    assert result.effective.burst == "2000b"
    assert result.effective.latency_bound == "400.0ms"
    assert result.effective.delay is None
    assert result.effective.loss is None


def test_link_properties_update_keeps_unspecified_netem_values() -> None:
    # 只改延迟：丢包沿用当前值 0.1%，limit 沿用 1000
    backend = QueueRuntimeBackend([
        (0, GOLDEN_QDISC, ""),
        (0, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_update",
        {"source": "as151-host-0", "interface": "net0", "latency": "50ms"},
    )

    assert result.successful is True
    assert len(result.executed) == 1
    assert result.executed[0].command == [
        "tc", "qdisc", "replace", "dev", "net0", "parent", "1:1", "handle", "8002:",
        "netem", "limit", "1000", "delay", "50ms", "loss", "0.1%",
    ]
    assert result.effective.delay == "50ms"
    assert result.effective.loss == "0.1%"
    assert result.effective.limit == "1000"
    assert result.effective.rate is None


def test_link_properties_update_normalizes_drop_percent() -> None:
    backend = QueueRuntimeBackend([
        (0, GOLDEN_QDISC, ""),
        (0, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_update",
        {"source": "source", "interface": "net0", "drop": "5"},
    )

    assert result.drop == "5%"
    assert result.executed[0].command[-2:] == ["loss", "5%"]
    assert result.effective.loss == "5%"

def test_link_properties_update_reports_all_effective_values() -> None:
    # 同时改 bandwidth + latency + drop：effective 六字段全有值，executed 两条命令
    backend = QueueRuntimeBackend([
        (0, GOLDEN_QDISC, ""),
        (0, "", ""),
        (0, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_update",
        {"source": "src", "interface": "net0", "bandwidth": "10Mbit", "latency": "20ms", "drop": "1%"},
    )

    assert result.successful is True
    assert len(result.executed) == 2  # tbf replace + netem replace
    assert result.effective.rate == "10Mbit"
    assert result.effective.burst == "2000b"
    assert result.effective.latency_bound == "400.0ms"
    assert result.effective.delay == "20ms"
    assert result.effective.loss == "1%"
    assert result.effective.limit == "1000"



def test_link_properties_update_adds_qdiscs_when_missing() -> None:
    # 接口没有任何链路属性 qdisc：先补 tbf 再补 netem（2 条 add）
    backend = QueueRuntimeBackend([
        (0, "qdisc noqueue 0: dev lo root refcnt 2 \n", ""),
        (0, "", ""),
        (0, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_update",
        {"source": "source", "interface": "eth0", "latency": "10ms", "drop": "0%"},
    )

    assert result.successful is True
    assert len(result.executed) == 2
    assert result.executed[0].command[:7] == ["tc", "qdisc", "add", "dev", "eth0", "root", "handle"]
    assert result.executed[1].command[:8] == ["tc", "qdisc", "add", "dev", "eth0", "parent", "1:1", "handle"]


def test_link_properties_update_reports_failure() -> None:
    backend = QueueRuntimeBackend([
        (0, GOLDEN_QDISC, ""),
        (1, "", "Cannot find specified qdisc"),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.link_properties_update",
        {"source": "source", "interface": "net0", "bandwidth": "50Mbit"},
    )

    assert result.successful is False
    assert result.executed[0].exit_code == 1
    assert "Cannot find" in result.executed[0].stderr


def test_link_properties_update_validates_arguments() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.link_properties_update",
            {"source": "source", "interface": "net0"},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.link_properties_update",
            {"source": "source", "interface": "net0", "latency": "10ms", "bandwidth": "abc"},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.link_properties_update",
            {"source": "source", "interface": "bad name!", "latency": "10ms"},
        )


def test_reachability_map_probes_all_pairs() -> None:
    backend = QueueRuntimeBackend([
        (0, "64 bytes from 10.150.0.71: icmp_seq=0 ttl=64 time=1.234 ms\n", ""),
        (1, "", ""),
        (0, "64 bytes from 10.151.0.71: icmp_seq=0 ttl=64 time<1 ms\n", ""),
        (1, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.reachability_map",
        {
            "sources": ["as150-host-0", "as151-host-0"],
            "targets": ["10.150.0.71", "10.151.0.71"],
        },
    )

    assert result.successful is True
    assert result.total_pairs == 4
    assert result.reachable_count == 2
    assert len(result.entries) == 4
    # 行主序遍历：外层 source、内层 target
    assert backend.commands[0] == ["ping", "-c", "1", "-W", "2", "10.150.0.71"]  # (as150, t0)
    assert backend.commands[1] == ["ping", "-c", "1", "-W", "2", "10.151.0.71"]  # (as150, t1)
    assert backend.commands[2] == ["ping", "-c", "1", "-W", "2", "10.150.0.71"]  # (as151, t0)
    assert backend.commands[3] == ["ping", "-c", "1", "-W", "2", "10.151.0.71"]  # (as151, t1)
    assert result.entries[0].reachable is True
    assert result.entries[0].round_trip_ms == 1.234
    assert result.entries[1].reachable is False
    assert result.entries[1].round_trip_ms is None
    assert result.entries[2].round_trip_ms == 1.0


def test_reachability_map_passes_probe_settings() -> None:
    backend = QueueRuntimeBackend([
        (0, "", ""),
        (0, "", ""),
    ])
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.reachability_map",
        {"sources": ["s1"], "targets": ["10.0.0.1", "10.0.0.2"], "count": 3, "timeout_seconds": 5},
    )

    assert backend.commands[0] == ["ping", "-c", "3", "-W", "5", "10.0.0.1"]
    assert result.count == 3
    assert result.timeout_seconds == 5


def test_reachability_map_validates_list_sizes() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.reachability_map",
            {"sources": [], "targets": ["10.0.0.1"]},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.reachability_map",
            {"sources": [f"host-{index}" for index in range(21)], "targets": ["10.0.0.1"]},
        )

GOLDEN_TCPDUMP = (
    "12:34:56.789012 IP 10.0.0.1.1234 > 10.0.0.2.80: Flags [S], seq 1:1, win 64240, length 0\n"
    "12:34:56.789123 IP 10.0.0.2.80 > 10.0.0.1.1234: Flags [S.], seq 2:2, ack 1, win 64240, length 0\n"
)


def test_packet_capture_returns_raw_lines() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_TCPDUMP)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.packet_capture",
        {"source": "as151-host-0"},
    )

    assert backend.command == ["timeout", "5", "tcpdump", "-i", "any", "-c", "10", "-nn"]
    assert result.successful is True
    assert result.timed_out is False
    assert len(result.packets) == 2
    assert "Flags [S]" in result.packets[0]


def test_packet_capture_appends_filter_expression() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.packet_capture",
        {"source": "source", "interface": "net0", "count": 3, "filter_expression": "tcp port 80"},
    )

    assert backend.command == [
        "timeout", "5", "tcpdump", "-i", "net0", "-c", "3", "-nn", "tcp port 80",
    ]


def test_packet_capture_reports_timeout() -> None:
    backend = FakeRuntimeBackend(exit_code=124, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.packet_capture",
        {"source": "source"},
    )

    assert result.timed_out is True
    assert result.successful is False


def test_packet_capture_validates_arguments() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.packet_capture",
            {"source": "source", "count": 0},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.packet_capture",
            {"source": "source", "interface": "bad name!"},
        )


GOLDEN_IPTABLES = (
    "-P INPUT ACCEPT\n"
    "-P FORWARD DROP\n"
    "-P OUTPUT ACCEPT\n"
    "-A INPUT -i lo -j ACCEPT\n"
    "-A INPUT -p tcp --dport 22 -j ACCEPT\n"
    "-A FORWARD -p icmp -j ACCEPT\n"
)


def test_firewall_inspect_parses_chains() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout=GOLDEN_IPTABLES)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.firewall_inspect",
        {"source": "source"},
    )

    assert backend.command == ["iptables", "-S", "-t", "filter"]
    assert result.successful is True
    assert len(result.chains) == 3
    input_chain = result.chains[0]
    assert input_chain.name == "INPUT"
    assert input_chain.policy == "ACCEPT"
    assert input_chain.rules == [
        "-A -i lo -j ACCEPT",
        "-A -p tcp --dport 22 -j ACCEPT",
    ]
    assert result.chains[1].policy == "DROP"
    assert result.chains[1].rules == ["-A -p icmp -j ACCEPT"]


def test_firewall_inspect_reports_missing_iptables() -> None:
    backend = FakeRuntimeBackend(exit_code=127, stderr="sh: iptables: not found")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.firewall_inspect",
        {"source": "source"},
    )

    assert result.successful is False
    assert result.chains == []
    assert "not found" in result.stderr


def test_firewall_inspect_passes_table() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.firewall_inspect",
        {"source": "source", "table": "nat"},
    )

    assert backend.command == ["iptables", "-S", "-t", "nat"]
    assert result.table == "nat"


def test_firewall_update_appends_rule() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.firewall_update",
        {"source": "source", "action": "append", "chain": "INPUT", "rule": "-p tcp --dport 8080 -j DROP"},
    )

    assert backend.command == [
        "iptables", "-A", "INPUT", "-p", "tcp", "--dport", "8080", "-j", "DROP",
    ]
    assert result.successful is True


def test_firewall_update_deletes_rule() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.firewall_update",
        {"source": "source", "action": "delete", "chain": "INPUT", "rule": "-p tcp --dport 8080 -j DROP"},
    )

    assert backend.command == [
        "iptables", "-D", "INPUT", "-p", "tcp", "--dport", "8080", "-j", "DROP",
    ]


def test_firewall_update_validates_chain() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.firewall_update",
            {"source": "source", "action": "append", "chain": "bad chain!", "rule": "-j DROP"},
        )

def test_neighbor_update_adds_entry() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.neighbor_update",
        {
            "source": "source",
            "operation": "add",
            "destination": "10.151.0.1",
            "interface": "net0",
            "lladdr": "00:11:22:33:44:55",
        },
    )

    assert backend.command == [
        "ip", "neigh", "add", "10.151.0.1",
        "lladdr", "00:11:22:33:44:55", "dev", "net0",
    ]
    assert result.successful is True


def test_neighbor_update_deletes_entry() -> None:
    backend = FakeRuntimeBackend(exit_code=0)
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.neighbor_update",
        {"source": "source", "operation": "del", "destination": "10.151.0.1", "interface": "net0"},
    )

    assert backend.command == ["ip", "neigh", "del", "10.151.0.1", "dev", "net0"]


def test_neighbor_update_validates_arguments() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.neighbor_update",
            {"source": "source", "operation": "add", "destination": "10.151.0.1", "interface": "net0"},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.neighbor_update",
            {"source": "source", "operation": "add", "destination": "10.151.0.1", "interface": "net0", "lladdr": "not-a-mac"},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.neighbor_update",
            {"source": "source", "operation": "del", "destination": "not-an-ip", "interface": "net0"},
        )


def test_sysctl_update_sets_parameter() -> None:
    backend = FakeRuntimeBackend(exit_code=0, stdout="net.ipv4.ip_forward = 1")
    registry = ToolRegistry()
    register_network_tools(registry, backend)

    result = anyio.run(
        registry.invoke,
        "network.sysctl_update",
        {"source": "source", "key": "net.ipv4.ip_forward", "value": "1"},
    )

    assert backend.command == ["sysctl", "-w", "net.ipv4.ip_forward=1"]
    assert result.successful is True
    assert result.stdout == "net.ipv4.ip_forward = 1"


def test_sysctl_update_validates_key_namespace() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.sysctl_update",
            {"source": "source", "key": "kernel.hostname", "value": "x"},
        )
    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.sysctl_update",
            {"source": "source", "key": "net.ipv4.ip_forward", "value": "1 2"},
        )




def test_link_update_validates_interface_name() -> None:
    registry = ToolRegistry()
    register_network_tools(registry, FakeRuntimeBackend())

    with pytest.raises(ValidationError):
        anyio.run(
            registry.invoke,
            "network.link_update",
            {"source": "source", "interface": "bad name!", "state": "up"},
        )


