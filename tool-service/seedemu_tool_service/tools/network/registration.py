"""Registration entry point for network-domain tools."""

from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.models.tool import ToolDefinition
from seedemu_tool_service.registry import ToolRegistry
from seedemu_tool_service.tools.network.models import (
    CidrInspectArguments,
    FirewallInspectArguments,
    FirewallUpdateArguments,
    InspectIPAddressArguments,
    InterfaceInspectArguments,
    LinkPropertiesArguments,
    LinkPropertiesUpdateArguments,
    LinkUpdateArguments,
    ListenSocketsArguments,
    NeighborInspectArguments,
    NeighborUpdateArguments,
    NodeNetworksArguments,
    PacketCaptureArguments,
    PathTraceArguments,
    PingArguments,
    ReachabilityMapArguments,
    RouteInspectArguments,
    RouteLookupArguments,
    RouteUpdateArguments,
    SysctlUpdateArguments,
)
from seedemu_tool_service.tools.network.tools import NetworkTools


def register_network_tools(registry: ToolRegistry, backend: RuntimeBackend) -> None:
    """Create the network tool set and register its handlers."""

    tools = NetworkTools(backend)
    registry.register(
        definition=ToolDefinition(
            name="network.cidr_inspect",
            domain="network",
            description="Inspect a CIDR network: normalized address, netmask, broadcast, host range, and membership.",
        ),
        handler=tools.cidr_inspect,
        arguments_model=CidrInspectArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.firewall_inspect",
            domain="network",
            description="Inspect iptables firewall rules (conditional: iptables is not in the base image).",
        ),
        handler=tools.firewall_inspect,
        arguments_model=FirewallInspectArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.firewall_update",
            domain="network",
            description="Append or delete an iptables rule at runtime (conditional and non-persistent).",
        ),
        handler=tools.firewall_update,
        arguments_model=FirewallUpdateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.inspect_ip_address",
            domain="network",
            description="Normalize an IPv4 or IPv6 address and inspect its properties.",
        ),
        handler=tools.inspect_ip_address,
        arguments_model=InspectIPAddressArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.interface_inspect",
            domain="network",
            description="Inspect the network interfaces and their addresses on an emulated node.",
        ),
        handler=tools.interface_inspect,
        arguments_model=InterfaceInspectArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.link_properties_inspect",
            domain="network",
            description="Inspect the effective link properties (tbf/netem qdiscs) on a node's interfaces.",
        ),
        handler=tools.link_properties_inspect,
        arguments_model=LinkPropertiesArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.link_properties_update",
            domain="network",
            description="Change the effective link properties (latency/bandwidth/drop) on an interface at runtime.",
        ),
        handler=tools.link_properties_update,
        arguments_model=LinkPropertiesUpdateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.link_update",
            domain="network",
            description="Set an interface administratively up or down to simulate a link failure.",
        ),
        handler=tools.link_update,
        arguments_model=LinkUpdateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.listen_sockets",
            domain="network",
            description="Inspect the TCP and UDP listening sockets of an emulated node.",
        ),
        handler=tools.listen_sockets,
        arguments_model=ListenSocketsArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.neighbor_inspect",
            domain="network",
            description="Inspect the kernel neighbor table (ARP/ND) of an emulated node.",
        ),
        handler=tools.neighbor_inspect,
        arguments_model=NeighborInspectArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.neighbor_update",
            domain="network",
            description="Add or delete a kernel neighbor (ARP) entry at runtime (non-persistent).",
        ),
        handler=tools.neighbor_update,
        arguments_model=NeighborUpdateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.node_networks",
            domain="network",
            description="Inspect the emulated networks a node connects to and their configured link properties.",
        ),
        handler=tools.node_networks,
        arguments_model=NodeNetworksArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.packet_capture",
            domain="network",
            description="Capture raw packets on an interface with tcpdump (bounded by count and timeout).",
        ),
        handler=tools.packet_capture,
        arguments_model=PacketCaptureArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.path_trace",
            domain="network",
            description="Trace the route to a target with per-hop loss and latency statistics.",
        ),
        handler=tools.path_trace,
        arguments_model=PathTraceArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.route_lookup",
            domain="network",
            description="Query how the kernel routes traffic to a specific destination.",
        ),
        handler=tools.route_lookup,
        arguments_model=RouteLookupArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.route_update",
            domain="network",
            description="Add or delete a kernel route at runtime (non-persistent).",
        ),
        handler=tools.route_update,
        arguments_model=RouteUpdateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.sysctl_update",
            domain="network",
            description="Set a kernel net.* parameter at runtime (non-persistent).",
        ),
        handler=tools.sysctl_update,
        arguments_model=SysctlUpdateArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.ping",
            domain="network",
            description="Test whether a target host is reachable from an emulated node using ICMP.",
        ),
        handler=tools.ping,
        arguments_model=PingArguments,
    )
    registry.register(
        definition=ToolDefinition(
            name="network.reachability_map",
            domain="network",
            description="Probe reachability from multiple sources to multiple targets (connectivity matrix).",
        ),
        handler=tools.reachability_map,
        arguments_model=ReachabilityMapArguments,
    )

    registry.register(
        definition=ToolDefinition(
            name="network.route_inspect",
            domain="network",
            description="Inspect the kernel routing table of an emulated node.",
        ),
        handler=tools.route_inspect,
        arguments_model=RouteInspectArguments,
    )
