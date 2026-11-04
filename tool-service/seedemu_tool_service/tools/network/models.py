"""Input and output models for network-domain tools."""

import re
from ipaddress import ip_address, ip_network
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator



# 写操作入参的格式校验（P4：写操作比只读更严格）
# Linux 接口名：字母/数字开头，最长 15 字符
_IFNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,14}$")
# netem 延迟：形如 "10ms" / "0.5s"
_LATENCY_PATTERN = re.compile(r"^\d+(\.\d+)?(ms|s)$")
# netem 丢包：形如 "0%" / "0.1%"，纯数字按百分比归一化
_DROP_PATTERN = re.compile(r"^\d+(\.\d+)?%?$")
# tbf 带宽：tc 速率单位形如 "100Mbit" / "10mbit" / "1gbit"（宽松校验，语法错误由 tc 报错）
_BANDWIDTH_PATTERN = re.compile(r"^\d+(\.\d+)?[a-zA-Z]+$")
# MAC 地址：形如 00:11:22:33:44:55
_MAC_PATTERN = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
# sysctl 键：只允许 net.* 命名空间（防止误写内核其他区域）
_SYSCTL_KEY_PATTERN = re.compile(r"^net\.[a-z0-9_.-]+$")
# sysctl 值：字母数字与少数符号（无空格，参数向量下防注入）
_SYSCTL_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:+-]+$")
# iptables 链名：字母数字下划线（含自定义链，如 DOCKER）
_IPTABLES_CHAIN_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

class ToolArguments(BaseModel):
    """Base model for strict tool argument validation."""

    model_config = ConfigDict(extra="forbid")


class InspectIPAddressArguments(ToolArguments):
    """Arguments accepted by the IP-address inspection tool."""

    address: str = Field(description="IPv4 or IPv6 address to inspect")


class IPAddressInfo(BaseModel):
    """Normalized properties of an IP address."""

    address: str
    version: Literal[4, 6]
    is_private: bool
    is_loopback: bool
    is_multicast: bool
    is_global: bool


class PingArguments(ToolArguments):
    """Arguments accepted by the host-reachability tool."""

    source: str = Field(description="Name or ID of the emulated source container")
    target: str = Field(description="Destination IPv4 address, IPv6 address, or hostname")
    count: int = Field(default=3, ge=1, le=10, description="Number of ICMP echo requests")
    timeout_seconds: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Per-request timeout in seconds",
    )


class ReachabilityResult(BaseModel):
    """Result of an ICMP reachability test."""

    source: str
    target: str
    reachable: bool
    exit_code: int
    stdout: str
    stderr: str


class RouteInspectArguments(ToolArguments):
    """Arguments accepted by the routing-table inspection tool."""

    source: str = Field(description="Name or ID of the emulated source container")


class RouteEntry(BaseModel):
    """内核路由表中的一条路由条目。

    ``gateway``、``interface`` 和 ``source`` 是可选字段，因为 ``ip route``
    只在它们实际存在时才输出（例如默认路由就没有 ``src``）。
    """

    destination: str = Field(description="Destination prefix, or 'default'")
    gateway: str | None = Field(default=None, description="Next-hop gateway address")
    interface: str | None = Field(default=None, description="Egress interface")
    source: str | None = Field(default=None, description="Preferred source address")


class RouteInspectResult(BaseModel):
    """查看节点路由表的结果。

    ``successful`` 反映命令的退出码，``routes`` 保存解析出的路由条目；
    ``exit_code`` 和 ``stderr`` 保留用于诊断。
    """

    source: str
    successful: bool
    exit_code: int
    routes: list[RouteEntry] = Field(default_factory=list)
    stderr: str


class InterfaceInspectArguments(ToolArguments):
    """接口检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete ip addr show output for diagnostics",
    )


class InterfaceAddress(BaseModel):
    """绑定到某个网络接口的一条 IP 地址。"""

    family: Literal["inet", "inet6"]
    local: str
    prefixlen: int
    scope: str | None = Field(
        default=None,
        description="Address scope, e.g. host/link/global",
    )


class InterfaceInfo(BaseModel):
    """仿真节点上的一个网络接口。

    ``up`` 是语义化字段（由内核 flags 推导）；``operstate``、``mtu``、
    ``mac_address`` 为可选信息；``addresses`` 列出该接口绑定的所有地址。
    """

    name: str = Field(description="Interface name, e.g. lo/net0/eth0")
    up: bool = Field(description="Whether the interface is administratively up")
    operstate: str | None = Field(default=None, description="Kernel operational state")
    mtu: int | None = Field(default=None, description="Interface MTU in bytes")
    mac_address: str | None = Field(
        default=None,
        description="MAC address for ethernet links",
    )
    addresses: list[InterfaceAddress] = Field(default_factory=list)


class InterfaceInspectResult(BaseModel):
    """查看节点网络接口的结果。

    ``successful`` 反映命令的退出码；``parse_failed`` 表示命令成功但输出
    无法解析为 JSON；``exit_code``/``stderr``/``raw_output`` 保留用于诊断。
    """

    source: str
    successful: bool
    exit_code: int
    parse_failed: bool = False
    interfaces: list[InterfaceInfo] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None


class NeighborInspectArguments(ToolArguments):
    """邻居表检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete ip neigh show output for diagnostics",
    )


class NeighborEntry(BaseModel):
    """邻居表（ARP / IPv6 ND）中的一条条目。

    ``lladdr`` 在条目未解析时为 ``None``；``is_router`` 由 flags 推导，
    表示该邻居是否被标记为 IPv6 路由器。
    """

    destination: str = Field(description="Neighbor IP address")
    lladdr: str | None = Field(
        default=None,
        description="Resolved MAC address, or null if unresolved",
    )
    interface: str | None = Field(
        default=None,
        description="Interface the neighbor was learned on",
    )
    state: list[str] = Field(default_factory=list)
    is_router: bool = False


class NeighborInspectResult(BaseModel):
    """查看节点邻居表的结果。

    ``successful`` 反映命令的退出码；``parse_failed`` 表示命令成功但输出
    无法解析为 JSON；``exit_code``/``stderr``/``raw_output`` 保留用于诊断。
    """

    source: str
    successful: bool
    exit_code: int
    parse_failed: bool = False
    entries: list[NeighborEntry] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None


class RouteLookupArguments(ToolArguments):
    """路由查找工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    destination: str = Field(description="Destination IPv4 or IPv6 address to look up")

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        """拒绝非 IP 输入，并归一化合法的 IPv4/IPv6 地址。"""
        return str(ip_address(value))


class RouteLookupResult(BaseModel):
    """针对单个目的地查询内核选路的结果。

    ``successful`` 反映命令退出码；``reachable`` 是语义字段——仅当路由类型
    属于 ``unicast``/``local``/``broadcast``/``multicast`` 之一时才为真。
    """

    source: str
    destination: str
    successful: bool
    reachable: bool = False
    route_type: str | None = Field(
        default=None,
        description="unicast/unreachable/local/blackhole/...",
    )
    gateway: str | None = Field(default=None, description="Next-hop gateway address")
    interface: str | None = Field(default=None, description="Egress interface")
    source_address: str | None = Field(
        default=None,
        description="Preferred source address",
    )
    exit_code: int
    stderr: str


class PathTraceArguments(ToolArguments):
    """路径追踪工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    target: str = Field(min_length=1, description="Destination IP address or hostname")
    count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of probes sent to each hop",
    )


class TraceHop(BaseModel):
    """路径中一跳的逐跳统计。"""

    hop: int
    host: str | None = Field(
        default=None,
        description="Hop IP address, or null for a non-responding hop",
    )
    loss_percent: float | None = None
    sent: int | None = None
    last_ms: float | None = None
    avg_ms: float | None = None
    best_ms: float | None = None
    worst_ms: float | None = None
    stdev_ms: float | None = None


class PathTraceResult(BaseModel):
    """路径追踪的结果。

    ``successful`` 反映命令退出码；``target_reached`` 表示最后一跳有响应
    （host 不为 null）。``raw_output`` 保留完整 mtr report 作为诊断证据。
    """

    source: str
    target: str
    successful: bool
    target_reached: bool = False
    hops: list[TraceHop] = Field(default_factory=list)
    exit_code: int
    stderr: str
    raw_output: str = ""


class ListenSocketsArguments(ToolArguments):
    """监听套接字检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete ss output for diagnostics",
    )


class ListenSocket(BaseModel):
    """一个处于监听状态的套接字。"""

    netid: str = Field(description="Protocol and address family, e.g. tcp/udp/tcp6/udp6")
    state: str = Field(description="Socket state, e.g. LISTEN/UNCONN")
    local_address: str
    local_port: str
    peer_address: str
    peer_port: str
    process_name: str | None = Field(
        default=None,
        description="Process name listening on the socket",
    )
    pid: int | None = Field(default=None, description="Process ID listening on the socket")


class ListenSocketsResult(BaseModel):
    """查看节点监听套接字的结果。

    ``successful`` 反映命令退出码；``sockets`` 保存解析出的监听条目；
    ``exit_code``/``stderr``/``raw_output`` 保留用于诊断。
    """

    source: str
    successful: bool
    exit_code: int
    sockets: list[ListenSocket] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None


class CidrInspectArguments(ToolArguments):
    """CIDR 子网检查工具的入参模型（纯计算，不碰容器）。"""

    network: str = Field(
        description="IPv4 or IPv6 network in CIDR notation, e.g. 10.0.0.0/24",
    )
    contains: str | None = Field(
        default=None,
        description="Optional IP address or CIDR network to test for membership in `network`",
    )

    @field_validator("network")
    @classmethod
    def validate_network(cls, value: str) -> str:
        """解析并归一化 CIDR；strict=False 容忍主机位（10.0.0.5/24 → 10.0.0.0/24）。"""
        return str(ip_network(value, strict=False))

    @field_validator("contains")
    @classmethod
    def validate_contains(cls, value: str | None) -> str | None:
        """把 contains 归一化为 IP 地址或 CIDR 网络的字符串形式。"""
        if value is None:
            return None
        try:
            return str(ip_address(value))
        except ValueError:
            pass
        try:
            return str(ip_network(value, strict=False))
        except ValueError:
            raise ValueError(f"contains must be an IP address or CIDR network, got {value!r}")


class CidrInfo(BaseModel):
    """一个 CIDR 子网的计算结果。

    ``broadcast`` 仅 IPv4 有（IPv6 无广播概念，恒为 None）；``num_hosts`` 仅 IPv4
    给出（IPv6 无实用主机数语义，用 ``num_addresses`` 表达规模）；
    ``first_host``/``last_host`` 在 IPv4 指可用主机范围（含 /31、/32 特殊语义），
    在 IPv6 指子网首/末地址。
    """

    network: str = Field(description="Normalized network in CIDR notation, e.g. 10.0.0.0/24")
    version: Literal[4, 6]
    prefixlen: int
    netmask: str
    broadcast: str | None = Field(
        default=None,
        description="Broadcast address (IPv4 only; IPv6 has no broadcast concept)",
    )
    num_addresses: int = Field(description="Total number of addresses in the network")
    num_hosts: int | None = Field(
        default=None,
        description="Usable host count (IPv4; IPv6 has no practical host-count semantics)",
    )
    first_host: str | None = Field(
        default=None,
        description="IPv4: first usable host; IPv6: first address of the network",
    )
    last_host: str | None = Field(
        default=None,
        description="IPv4: last usable host; IPv6: last address of the network",
    )
    is_private: bool
    is_global: bool
    is_loopback: bool
    is_link_local: bool
    contains: str | None = Field(default=None, description="Normalized membership-test input")
    contains_type: Literal["address", "network"] | None = Field(
        default=None,
        description="Whether `contains` is an IP address or a CIDR network",
    )
    contains_result: bool | None = Field(default=None, description="Membership test outcome")


class NodeNetworksArguments(ToolArguments):
    """节点仿真网络检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete /ifinfo.txt content for diagnostics",
    )


class NetworkInfo(BaseModel):
    """仿真网络配置清单（/ifinfo.txt）中的一条：节点连接的一个仿真网络。"""

    name: str = Field(description="Emulated network name, e.g. net0")
    prefix: str | None = Field(default=None, description="Network prefix, e.g. 10.151.0.0/24")
    latency: str | None = Field(default=None, description="Configured latency, e.g. 10ms")
    bandwidth: str | None = Field(default=None, description="Configured bandwidth, e.g. 100mbit")
    drop: str | None = Field(default=None, description="Configured drop ratio, e.g. 0%")


class NodeNetworksResult(BaseModel):
    """查看节点连接的仿真网络的结果。

    ``parse_failed`` 表示命令成功但 stdout 非空且一行都没解析出来——
    用于区分"文件为空（合法状态）"与"格式不识别（emulator 版本差异）"。
    """

    source: str
    successful: bool
    exit_code: int
    parse_failed: bool = False
    networks: list[NetworkInfo] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None


class LinkPropertiesArguments(ToolArguments):
    """链路属性检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete tc qdisc show output for diagnostics",
    )


class QdiscInfo(BaseModel):
    """接口上的一个排队规则（qdisc）。

    ``rate`` 来自 tbf（限速）、``delay``/``loss`` 来自 netem（延迟/丢包）；
    其余参数（lat/mtu/overhead 等）不建模，保留在 raw_output。
    """

    kind: str = Field(description="Qdisc kind, e.g. tbf/netem/noqueue")
    handle: str | None = Field(default=None, description="Qdisc handle, e.g. 1")
    parent: str | None = Field(default=None, description="Parent handle, or 'root'")
    rate: str | None = Field(default=None, description="tbf rate limit, e.g. 100Mbit")
    delay: str | None = Field(default=None, description="netem delay, e.g. 10.0ms")
    loss: str | None = Field(default=None, description="netem loss ratio, e.g. 0.1%")
    limit: str | None = Field(default=None, description="Queue limit, e.g. 1000")
    burst: str | None = Field(default=None, description="tbf burst size, e.g. 2000b")


class InterfaceLinkState(BaseModel):
    """一个接口上生效的全部排队规则（链路属性的实际实现）。"""

    interface: str
    qdiscs: list[QdiscInfo] = Field(default_factory=list)


class LinkPropertiesResult(BaseModel):
    """查看节点链路属性（tc qdisc）的结果。"""

    source: str
    successful: bool
    exit_code: int
    interfaces: list[InterfaceLinkState] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None
class RouteUpdateArguments(ToolArguments):
    """路由表写操作（add/del）的入参模型。

    写操作语义：**运行时变更、非持久**（重启容器即还原）；只适合实验/假设验证。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    operation: Literal["add", "del"] = Field(description="Whether to add or delete the route")
    destination: str = Field(description="Destination prefix (CIDR) or 'default'")
    gateway: str | None = Field(
        default=None,
        description="Next-hop gateway address (required for most unicast adds)",
    )
    interface: str | None = Field(
        default=None,
        description="Egress interface, e.g. net0",
    )
    route_type: Literal["unicast", "blackhole"] = Field(
        default="unicast",
        description="unicast adds a normal route; blackhole drops matching traffic",
    )

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        """支持 "default" 与 CIDR；CIDR 用 strict=False 归一化。"""
        if value == "default":
            return value
        return str(ip_network(value, strict=False))

    @field_validator("gateway")
    @classmethod
    def validate_gateway(cls, value: str | None) -> str | None:
        """网关必须是合法 IP。"""
        if value is None:
            return None
        return str(ip_address(value))

    @model_validator(mode="after")
    def check_route(self):
        """跨字段约束：黑洞路由不能带 via/dev；普通 add 必须有 via 或 dev。"""
        if self.route_type == "blackhole" and (self.gateway or self.interface):
            raise ValueError("blackhole route must not specify gateway or interface")
        if self.operation == "add" and self.route_type == "unicast" and not (self.gateway or self.interface):
            raise ValueError("adding a unicast route requires gateway or interface")
        return self

class RouteUpdateResult(BaseModel):
    """路由写操作的结果。

    ``successful`` 反映命令退出码；``stderr`` 保留 ip route 的原始错误（如
    "RTNETLINK answers: File exists"）。写操作不保证持久，重启即还原。
    """

    source: str
    operation: Literal["add", "del"]
    destination: str
    gateway: str | None = None
    interface: str | None = None
    route_type: Literal["unicast", "blackhole"] = "unicast"
    successful: bool
    exit_code: int
    stderr: str


class LinkUpdateArguments(ToolArguments):
    """链路状态写操作（up/down）的入参模型——接口粒度模拟链路故障。

    官方 ``seedemu_worker`` 的 ``net_up/net_down`` 是脚本级操作；本工具是
    接口粒度版（``ip link set <iface> down/up``）。语义：运行时变更、非持久。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    interface: str = Field(description="Interface name, e.g. net0")
    state: Literal["up", "down"] = Field(description="Target administrative state")

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        """接口名格式校验（写操作入参比只读更严格）。"""
        if not _IFNAME_PATTERN.fullmatch(value):
            raise ValueError(f"invalid interface name: {value!r}")
        return value


class LinkUpdateResult(BaseModel):
    """链路状态写操作的结果。``successful`` 反映退出码；失败时 stderr 保留 ip 的原始错误。"""

    source: str
    interface: str
    state: Literal["up", "down"]
    successful: bool
    exit_code: int
    stderr: str
class LinkPropertiesUpdateArguments(ToolArguments):
    """链路属性写操作（tbf/netem 替换）的入参模型。

    至少提供 latency / bandwidth / drop 之一；未指定的属性**读取当前生效值并保持**
    （读-合并-替换：内部先查 tc qdisc show，再只改指定的部分）。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    interface: str = Field(description="Interface name, e.g. net0")
    latency: str | None = Field(
        default=None,
        description="Target netem delay, e.g. 20ms or 0.5s",
    )
    bandwidth: str | None = Field(
        default=None,
        description="Target tbf rate, e.g. 50Mbit or 10mbit",
    )
    drop: str | None = Field(
        default=None,
        description="Target netem loss ratio, e.g. 5% or 0.1%",
    )

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        if not _IFNAME_PATTERN.fullmatch(value):
            raise ValueError(f"invalid interface name: {value!r}")
        return value

    @field_validator("latency")
    @classmethod
    def validate_latency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _LATENCY_PATTERN.fullmatch(value):
            raise ValueError(f"latency must look like '10ms' or '0.5s', got {value!r}")
        return value

    @field_validator("bandwidth")
    @classmethod
    def validate_bandwidth(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _BANDWIDTH_PATTERN.fullmatch(value):
            raise ValueError(f"bandwidth must look like '100Mbit', got {value!r}")
        return value

    @field_validator("drop")
    @classmethod
    def validate_drop(cls, value: str | None) -> str | None:
        """纯数字按百分比归一化（"5" → "5%"）。"""
        if value is None:
            return None
        if not _DROP_PATTERN.fullmatch(value):
            raise ValueError(f"drop must look like '5%' or '0.1%', got {value!r}")
        return value if value.endswith("%") else value + "%"

    @model_validator(mode="after")
    def require_at_least_one(self):
        """至少指定 latency / bandwidth / drop 之一，否则无操作可做。"""
        if self.latency is None and self.bandwidth is None and self.drop is None:
            raise ValueError("at least one of latency, bandwidth, drop must be provided")
        return self

class UpdateCommand(BaseModel):
    """链路属性写操作中已执行的一条 tc 命令。"""

    command: list[str] = Field(description="Executed command as an argument vector")
    exit_code: int
    stderr: str


class EffectiveLinkProperties(BaseModel):
    """读-合并-替换后**实际写入**的链路属性值。

    只包含本次触及的参数（其余为 None）：改 bandwidth 时填 rate/burst/latency_bound；
    改 latency/drop 时填 delay/loss/limit。与入参（requested）的区别：这里是
    合并了"当前生效值"之后的最终值（如只改延迟时 loss 沿用当前值）。
    """

    rate: str | None = Field(default=None, description="tbf rate actually applied (from bandwidth)")
    burst: str | None = Field(default=None, description="tbf burst used in the replace/add")
    latency_bound: str | None = Field(default=None, description="tbf latency bound used")
    delay: str | None = Field(default=None, description="netem delay actually applied (from latency)")
    loss: str | None = Field(default=None, description="netem loss actually applied (from drop)")
    limit: str | None = Field(default=None, description="netem queue limit used")

class LinkPropertiesUpdateResult(BaseModel):
    """链路属性写操作的结果。

    ``successful`` = 所有已执行命令退出码均为 0；``executed`` 逐条记录
    命令向量与退出码（读-合并-替换可能执行 1~2 条 tc 命令）。
    """

    source: str
    interface: str
    latency: str | None = None
    bandwidth: str | None = None
    drop: str | None = None
    successful: bool
    executed: list[UpdateCommand] = Field(default_factory=list)
    effective: EffectiveLinkProperties = Field(
        default_factory=EffectiveLinkProperties,
        description="Effective link properties actually written (merged requested + kept values)",
    )


class ReachabilityMapArguments(ToolArguments):
    """多源 × 多目标连通矩阵（批量只读）的入参模型。

    对每个 (source, target) 组合执行一次 ICMP ping；探测数 count 默认 1
    （N×M 次 docker exec，列表过大时耗时会显著）。
    """

    sources: list[str] = Field(
        min_length=1,
        max_length=20,
        description="Source container names (1-20)",
    )
    targets: list[str] = Field(
        min_length=1,
        max_length=20,
        description="Destination IPs or hostnames (1-20)",
    )
    count: int = Field(
        default=1,
        ge=1,
        le=5,
        description="ICMP probes per pair (default 1 to keep N*M fast)",
    )
    timeout_seconds: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Per-request timeout in seconds",
    )


class ReachabilityEntry(BaseModel):
    """连通矩阵中一个 (source, target) 组合的探测结果。"""

    source: str
    target: str
    reachable: bool = False
    exit_code: int
    round_trip_ms: float | None = Field(
        default=None,
        description="Last measured RTT in ms, or null when unreachable/unparseable",
    )


class ReachabilityMapResult(BaseModel):
    """连通矩阵的整体结果。

    ``successful`` 表示探测全部执行完成（**不是**全部可达）；
    每条 (source, target) 的可达性看 ``entries`` 的 reachable 字段。
    """

    sources: list[str]
    targets: list[str]
    count: int
    timeout_seconds: int
    successful: bool
    reachable_count: int
    total_pairs: int
    entries: list[ReachabilityEntry] = Field(default_factory=list)
class PacketCaptureArguments(ToolArguments):
    """抓包工具的入参模型（F 类兜底诊断·只读）。

    抓包是"无假设看原始证据"：结果按行保留原始 tcpdump 输出，不做翻译。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    interface: str = Field(default="any", description="Interface to capture on, or 'any'")
    count: int = Field(default=10, ge=1, le=100, description="Maximum packets to capture")
    timeout_seconds: int = Field(default=5, ge=1, le=30, description="Wall-clock cap before the capture stops")
    filter_expression: str | None = Field(
        default=None,
        max_length=200,
        description="tcpdump BPF filter, e.g. 'tcp port 80' or 'icmp'",
    )

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        """'any' 或合法接口名。"""
        if value != "any" and not _IFNAME_PATTERN.fullmatch(value):
            raise ValueError(f"invalid interface name: {value!r}")
        return value


class PacketCaptureResult(BaseModel):
    """抓包结果：原始包行 + 元信息（F 类 = 未翻译的证据）。

    ``timed_out`` 表示 timeout(1) 包装器杀掉了抓包（退出码 124）——
    抓包被"墙钟上限"截断，不是命令失败。
    """

    source: str
    interface: str
    count: int
    timeout_seconds: int
    filter_expression: str | None = None
    successful: bool
    timed_out: bool = Field(
        default=False,
        description="True when the timeout(1) wrapper killed the capture (exit 124)",
    )
    packets: list[str] = Field(default_factory=list, description="One raw tcpdump line per captured packet")
    exit_code: int
    stderr: str
    raw_output: str = ""
class FirewallInspectArguments(ToolArguments):
    """防火墙检查工具的入参模型（F 类兜底诊断·只读）。

    **条件可用**：iptables 不在 seedemu-base 基础镜像里，仅特定实验镜像有；
    命令不存在时工具返回 successful=False 且 stderr 为 \"iptables: not found\"。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    table: str = Field(default="filter", description="iptables table: filter/nat/mangle/raw/security")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete iptables -S output for diagnostics",
    )


class FirewallChain(BaseModel):
    """iptables -S 输出中的一个链（策略 + 规则清单）。"""

    name: str = Field(description="Chain name, e.g. INPUT/OUTPUT/FORWARD")
    policy: str | None = Field(default=None, description="Default policy, e.g. ACCEPT/DROP")
    rules: list[str] = Field(default_factory=list, description="Rule specs, e.g. '-A -i lo -j ACCEPT'")


class FirewallInspectResult(BaseModel):
    """防火墙检查结果。

    ``successful`` 反映命令退出码；链与规则按 iptables -S 的出现顺序排列。
    """

    source: str
    table: str
    successful: bool
    exit_code: int
    chains: list[FirewallChain] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None
class FirewallUpdateArguments(ToolArguments):
    """防火墙写操作（iptables -A/-D）的入参模型。

    **条件可用**（同 firewall_inspect）+ **非持久**（容器重启即还原）。
    注意：错误的规则（如 DROP INPUT 全部流量）可能把节点锁死，慎用。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    action: Literal["append", "delete"] = Field(description="append (-A) or delete (-D) a rule")
    chain: str = Field(description="Chain name, e.g. INPUT/OUTPUT/FORWARD or a custom chain")
    rule: str = Field(min_length=1, max_length=500, description="Rule spec as whitespace-separated tokens, e.g. '-p tcp --dport 22 -j DROP'")

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, value: str) -> str:
        if not _IPTABLES_CHAIN_PATTERN.fullmatch(value):
            raise ValueError(f"invalid chain name: {value!r}")
        return value


class FirewallUpdateResult(BaseModel):
    """防火墙写操作的结果。``successful`` 反映退出码；stderr 保留 iptables 原始错误。"""

    source: str
    action: Literal["append", "delete"]
    chain: str
    rule: str
    successful: bool
    exit_code: int
    stderr: str
class NeighborUpdateArguments(ToolArguments):
    """邻居表写操作（ip neigh add/del）的入参模型——ARP 实验，非持久。

    ``add`` 必须提供 MAC（lladdr）；``del`` 按 (destination, interface) 匹配删除。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    operation: Literal["add", "del"] = Field(description="Whether to add or delete the neighbor entry")
    destination: str = Field(description="Neighbor IP address")
    interface: str = Field(description="Interface the neighbor is on, e.g. net0")
    lladdr: str | None = Field(
        default=None,
        description="Neighbor MAC address (required for add)",
    )

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        """必须是合法 IP。"""
        return str(ip_address(value))

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        if not _IFNAME_PATTERN.fullmatch(value):
            raise ValueError(f"invalid interface name: {value!r}")
        return value

    @field_validator("lladdr")
    @classmethod
    def validate_lladdr(cls, value: str | None) -> str | None:
        """MAC 地址格式校验。"""
        if value is None:
            return None
        if not _MAC_PATTERN.fullmatch(value):
            raise ValueError(f"invalid MAC address: {value!r}")
        return value

    @model_validator(mode="after")
    def require_lladdr_for_add(self):
        """add 必须提供 MAC。"""
        if self.operation == "add" and self.lladdr is None:
            raise ValueError("adding a neighbor entry requires lladdr (MAC address)")
        return self


class NeighborUpdateResult(BaseModel):
    """邻居表写操作的结果。``successful`` 反映退出码；stderr 保留 ip 原始错误。"""

    source: str
    operation: Literal["add", "del"]
    destination: str
    interface: str
    lladdr: str | None = None
    successful: bool
    exit_code: int
    stderr: str
class SysctlUpdateArguments(ToolArguments):
    """内核参数写操作（sysctl -w）的入参模型（A 类节点状态·写）。

    键**只允许 net.* 命名空间**（如 net.ipv4.ip_forward、net.ipv4.icmp_echo_ignore_all），
    防止误写内核其他区域；非持久（容器重启即还原）。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    key: str = Field(description="sysctl key under net.*, e.g. net.ipv4.ip_forward")
    value: str = Field(description="Value, e.g. 1 or 0")

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        """只允许 net.* 命名空间。"""
        if not _SYSCTL_KEY_PATTERN.fullmatch(value):
            raise ValueError(f"sysctl key must be under net.*, got {value!r}")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        """无空格的值（参数向量下防注入）。"""
        if not _SYSCTL_VALUE_PATTERN.fullmatch(value):
            raise ValueError(f"invalid sysctl value: {value!r}")
        return value


class SysctlUpdateResult(BaseModel):
    """内核参数写操作的结果。``stdout`` 保留 sysctl -w 的确认行（如 \"net.ipv4.ip_forward = 1\"）。"""

    source: str
    key: str
    value: str
    successful: bool
    exit_code: int
    stdout: str
    stderr: str


