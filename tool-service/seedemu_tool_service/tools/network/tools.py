"""Network-domain tool implementations."""
# 标准库
import json
import re
from ipaddress import ip_address, ip_network
# 本项目库
from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.network.models import (
    CidrInfo,
    EffectiveLinkProperties,
    FirewallChain,
    FirewallInspectResult,
    FirewallUpdateResult,
    IPAddressInfo,
    InterfaceAddress,
    InterfaceInfo,
    InterfaceInspectResult,
    InterfaceLinkState,
    LinkPropertiesResult,
    LinkPropertiesUpdateResult,
    LinkUpdateResult,
    ListenSocket,
    ListenSocketsResult,
    NeighborEntry,
    NeighborInspectResult,
    NeighborUpdateResult,
    NetworkInfo,
    NodeNetworksResult,
    PacketCaptureResult,
    PathTraceResult,
    QdiscInfo,
    ReachabilityEntry,
    ReachabilityMapResult,
    ReachabilityResult,
    RouteEntry,
    RouteInspectResult,
    RouteLookupResult,
    RouteUpdateResult,
    SysctlUpdateResult,
    TraceHop,
    UpdateCommand,
)


# ip route get 的首 token 可能是这些路由类型关键字
_ROUTE_GET_TYPE_KEYWORDS = {
    "unreachable",
    "local",
    "blackhole",
    "prohibit",
    "throw",
    "broadcast",
    "multicast",
    "nat",
    "anycast",
}
# 属于这些类型时，目的地可视为可达
_REACHABLE_ROUTE_TYPES = {"unicast", "local", "broadcast", "multicast"}
# ss -tulnp 的 Process 列形如 users:(("named",pid=123,fd=20))，提取第一个进程名和 pid
_PROCESS_PATTERN = re.compile(r'\("([^"]+)",pid=(\d+)')


def _as_float(token: str) -> float | None:
    """把 mtr report 的数值 token 转成 float，失败返回 None。"""
    try:
        return float(token)
    except ValueError:
        return None


def _as_int(token: str) -> int | None:
    """把 mtr report 的整数 token 转成 int，失败返回 None。"""
    try:
        return int(token)
    except ValueError:
        return None

def _parse_ping_rtt(stdout: str) -> float | None:
    """从 ping 输出提取最后一个 time= / time< 的 RTT 值（毫秒）。

    GNU ping 形如 ``time=1.23 ms`` 或 ``time<1 ms``；解析失败返回 None。
    """
    matches = re.findall(r"time[=<]\s*(\d+(?:\.\d+)?)", stdout)
    if not matches:
        return None
    return float(matches[-1])


def _split_addr_port(token: str) -> tuple[str, str]:
    """把 ``ss`` 的 ``地址:端口`` 拆成 (地址, 端口)。

    支持 IPv4（``0.0.0.0:53``）、IPv6（``[::]:53``）和通配（``*:*``）。
    """
    if token.startswith("["):
        # IPv6 形如 [::]:80，去掉方括号后拆端口
        end = token.rfind("]")
        return token[1:end], token[end + 2:]
    if ":" in token:
        # IPv4 或通配形如 0.0.0.0:53 / *:*，按最后一个冒号拆
        address, port = token.rsplit(":", 1)
        return address, port
    return token, ""


def _parse_process(token: str) -> tuple[str | None, int | None]:
    """从 ``users:(("named",pid=123,fd=20))`` 提取第一个进程名和 pid。"""
    match = _PROCESS_PATTERN.search(token)
    if match:
        return match.group(1), int(match.group(2))
    return None, None


class NetworkTools:
    """Bound-method tools for network inspection and operations."""

    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def inspect_ip_address(self, address: str) -> IPAddressInfo:
        """Normalize an IP address and report its standard properties."""
        # 将字符串解析为IPv4/IPv6对象，可以进行归一化以及校验
        parsed_address = ip_address(address)
        # 把解析结果翻译成结果模型
        return IPAddressInfo(
            # 拿到规范化字符串
            address=str(parsed_address),
            version=parsed_address.version,
            is_private=parsed_address.is_private,
            is_loopback=parsed_address.is_loopback,
            is_multicast=parsed_address.is_multicast,
            is_global=parsed_address.is_global,
        )

    # 方法签名
    def cidr_inspect(self, network: str, contains: str | None = None) -> CidrInfo:
        """纯计算：归一化一个 CIDR 子网并报告其属性（不碰容器）。"""
        parsed_network = ip_network(network, strict=False)

        # IPv4：广播/主机范围有明确定义；/31、/32 是点对点/单地址前缀，语义特殊
        if parsed_network.version == 4:
            broadcast = str(parsed_network.broadcast_address)
            if parsed_network.prefixlen == 31:
                num_hosts = 2
                first_host = str(parsed_network.network_address)
                last_host = str(parsed_network.network_address + 1)
            elif parsed_network.prefixlen == 32:
                num_hosts = 1
                first_host = str(parsed_network.network_address)
                last_host = str(parsed_network.network_address)
            else:
                num_hosts = parsed_network.num_addresses - 2
                first_host = str(parsed_network.network_address + 1)
                last_host = str(parsed_network.broadcast_address - 1)
        else:
            # IPv6 无广播概念；主机数无实用语义（避免 2^64 级计算），报告子网首/末地址
            broadcast = None
            num_hosts = None
            first_host = str(parsed_network.network_address)
            last_host = str(parsed_network.network_address + (parsed_network.num_addresses - 1))

        # 可选的包含关系测试：contains 可能是 IP 地址（成员测试）或 CIDR（子网包含）
        contains_type: str | None = None
        contains_result: bool | None = None
        if contains is not None:
            try:
                contains_address = ip_address(contains)
                contains_type = "address"
                contains_result = (
                    contains_address.version == parsed_network.version
                    and contains_address in parsed_network
                )
            except ValueError:
                contains_network = ip_network(contains, strict=False)
                contains_type = "network"
                contains_result = (
                    contains_network.version == parsed_network.version
                    and contains_network.subnet_of(parsed_network)
                )

        return CidrInfo(
            network=str(parsed_network),
            version=parsed_network.version,
            prefixlen=parsed_network.prefixlen,
            netmask=str(parsed_network.netmask),
            broadcast=broadcast,
            num_addresses=parsed_network.num_addresses,
            num_hosts=num_hosts,
            first_host=first_host,
            last_host=last_host,
            is_private=parsed_network.is_private,
            is_global=parsed_network.is_global,
            is_loopback=parsed_network.is_loopback,
            is_link_local=parsed_network.is_link_local,
            contains=contains,
            contains_type=contains_type,
            contains_result=contains_result,
        )
    # 方法签名
    def ping(
        self,
        source: str,
        target: str,
        count: int = 3,
        timeout_seconds: int = 2,
    ) -> ReachabilityResult:
        """Test whether a target is reachable from an emulated source node."""
        # 由参数向量组成了命令的主体结构
        command = [
            "ping",
            "-c",
            str(count),
            "-W",
            str(timeout_seconds),
            target,
        ]
        # 后端执行命令
        result = self._backend.execute(source, command)
        # 返回结构化结果
        return ReachabilityResult(
            source=source,
            target=target,
            reachable=result.exit_code == 0,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    @staticmethod
    def _parse_route_line(line: str) -> RouteEntry | None:
        """把 ``ip route show`` 输出的一行解析成一条路由条目。
        采用「关键字扫描」：只识别 ``via`` / ``dev`` / ``src`` 三个关键字，并取紧随其后的一个 token 作为值；
        """
        # 将一行结果，以空格拆分成一块一块得到list
        fields = line.split()
        if not fields:
            # 空行不包含任何路由信息，返回 None 表示"没有可解析的内容"。
            return None

        # 第一个 token 永远是目的地,所以摘出来
        destination = fields[0]

        # 并不是所有路由都存在gateway,interface和source
        # 若是存在，则是str,先默认为none
        gateway: str | None = None
        interface: str | None = None
        source: str | None = None

        index = 1
        # 扫描所有的fields，在其中寻找关键词via,dev,src，其后面的token就是想要找的内容
        while index < len(fields):
            token = fields[index]
            if token in {"via", "dev", "src"} and index + 1 < len(fields):
                # 按寻找到的特殊值将其分类
                value = fields[index + 1]
                # via是指的下一跳路由
                if token == "via":
                    gateway = value
                # dev是指去哪个接口
                elif token == "dev":
                    interface = value
                # src是指源路由
                else:
                    source = value
                index += 2
            else:
                index += 1

        return RouteEntry(
            destination=destination,
            gateway=gateway,
            interface=interface,
            source=source,
        )
    # 方法签名
    def route_inspect(self, source: str) -> RouteInspectResult:
        """查看仿真节点内核的路由表。"""
        # 拼命令
        command = [
            "ip",
            "route",
            "show"
        ]
        # 命令执行
        result = self._backend.execute(source, command)

        # 逐行解析，为每条路由生成一个结构化条目；无法映射的行（空行、或解析器不认识的输出）直接丢弃。
        routes: list[RouteEntry] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            # 使用route_line解析，返回解析成果
            entry = self._parse_route_line(line)
            if entry is not None:
                routes.append(entry)

        # 在解析结果之外保留原始的退出码和 stderr，使调用方能区分
        # "没有任何路由" 与 "命令执行失败" 两种情况。
        return RouteInspectResult(
            source=source,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            routes=routes,
            stderr=result.stderr,
        )

    @staticmethod
    def _parse_interface_json(output: str) -> tuple[list[InterfaceInfo], bool]:
        """把 ``ip -j addr show`` 的 JSON 输出解析成结构化接口列表。

        返回 ``(interfaces, parse_ok)``：``parse_ok=False`` 表示输出不是合法
        JSON 或结构不符合预期（此时 ``interfaces`` 为空列表）。
        """
        try:
            raw_interfaces = json.loads(output)
        except json.JSONDecodeError:
            return [], False
        if not isinstance(raw_interfaces, list):
            return [], False

        interfaces: list[InterfaceInfo] = []
        for raw in raw_interfaces:
            if not isinstance(raw, dict):
                continue
            flags = raw.get("flags") or []
            addresses: list[InterfaceAddress] = []
            for item in raw.get("addr_info") or []:
                # 只认 inet/inet6 地址，其余（如链路层条目）跳过
                if not isinstance(item, dict) or item.get("family") not in {"inet", "inet6"}:
                    continue
                addresses.append(
                    InterfaceAddress(
                        family=item["family"],
                        local=item.get("local", ""),
                        prefixlen=item.get("prefixlen", 0),
                        scope=item.get("scope"),
                    )
                )
            interfaces.append(
                InterfaceInfo(
                    name=raw.get("ifname", ""),
                    up="UP" in flags,
                    operstate=raw.get("operstate"),
                    mtu=raw.get("mtu"),
                    mac_address=raw.get("address") if raw.get("link_type") == "ether" else None,
                    addresses=addresses,
                )
            )
        return interfaces, True

    # 方法签名
    def interface_inspect(
        self,
        source: str,
        include_raw_output: bool = False,
    ) -> InterfaceInspectResult:
        """查看仿真节点上所有网络接口及其绑定的 IP 地址。"""
        # 拼命令：-j 让 iproute2 输出 JSON，解析最稳
        result = self._backend.execute(source, ["ip", "-j", "addr", "show"])

        interfaces: list[InterfaceInfo] = []
        parse_failed = False
        # 命令失败时不解析 stdout（内容可能是报错文本）
        if result.exit_code == 0:
            # 解析器返回 (列表, parse_ok)，parse_failed 取其反
            interfaces, parse_ok = self._parse_interface_json(result.stdout)
            parse_failed = not parse_ok

        return InterfaceInspectResult(
            source=source,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            parse_failed=parse_failed,
            interfaces=interfaces,
            stderr=result.stderr,
            raw_output=result.stdout if include_raw_output else None,
        )

    @staticmethod
    def _parse_neighbor_json(output: str) -> tuple[list[NeighborEntry], bool]:
        """把 ``ip -j neigh show`` 的 JSON 输出解析成结构化邻居条目列表。"""
        try:
            raw_entries = json.loads(output)
        except json.JSONDecodeError:
            return [], False
        if not isinstance(raw_entries, list):
            return [], False

        entries: list[NeighborEntry] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            # state / flags 在标准 iproute2 里是数组，旧版本可能给字符串，做一次兜底
            state = raw.get("state") or []
            if isinstance(state, str):
                state = [state]
            flags = raw.get("flags") or []
            if isinstance(flags, str):
                flags = [flags]
            entries.append(
                NeighborEntry(
                    destination=raw.get("dst", ""),
                    lladdr=raw.get("lladdr"),
                    interface=raw.get("dev"),
                    state=state,
                    is_router="router" in flags,
                )
            )
        return entries, True

    # 方法签名
    def neighbor_inspect(
        self,
        source: str,
        include_raw_output: bool = False,
    ) -> NeighborInspectResult:
        """查看仿真节点内核的邻居表（ARP / IPv6 ND）。"""
        result = self._backend.execute(source, ["ip", "-j", "neigh", "show"])

        entries: list[NeighborEntry] = []
        parse_failed = False
        if result.exit_code == 0:
            # 解析器返回 (列表, parse_ok)，parse_failed 取其反
            entries, parse_ok = self._parse_neighbor_json(result.stdout)
            parse_failed = not parse_ok

        return NeighborInspectResult(
            source=source,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            parse_failed=parse_failed,
            entries=entries,
            stderr=result.stderr,
            raw_output=result.stdout if include_raw_output else None,
        )

    @staticmethod
    def _parse_route_get_line(
        line: str,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """把 ``ip route get`` 输出的第一行解析成 (route_type, gateway, interface, source)。

        首 token 可能是目的地（普通 unicast），也可能是路由类型关键字
        （unreachable / local / blackhole 等）；via / dev / src 用关键字扫描提取。
        """
        fields = line.split()
        if not fields:
            return None, None, None, None

        if fields[0] in _ROUTE_GET_TYPE_KEYWORDS:
            route_type = fields[0]
            start = 2
        else:
            route_type = "unicast"
            start = 1

        gateway: str | None = None
        interface: str | None = None
        source: str | None = None
        index = start
        while index < len(fields):
            token = fields[index]
            if token in {"via", "dev", "src"} and index + 1 < len(fields):
                value = fields[index + 1]
                if token == "via":
                    gateway = value
                elif token == "dev":
                    interface = value
                else:
                    source = value
                index += 2
            else:
                index += 1

        return route_type, gateway, interface, source

    # 方法签名
    def route_lookup(self, source: str, destination: str) -> RouteLookupResult:
        """查询内核"到某个目标实际走哪条路由"（含策略路由规则）。"""
        result = self._backend.execute(source, ["ip", "route", "get", destination])

        route_type: str | None = None
        gateway: str | None = None
        interface: str | None = None
        source_address: str | None = None
        # 注意：unreachable 时退出码非零，但部分 iproute2 版本把错误写到 stderr（stdout 为空），
        # 因此无论退出码如何都要尝试解析 stdout 第一行，并做 stderr 兜底。
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            route_type, gateway, interface, source_address = self._parse_route_get_line(line)
            break

        # 兜底：部分 iproute2 版本对不可达目标把错误写到 stderr（stdout 为空），
        # 仅靠 stdout 会漏掉 unreachable 语义，这里从 stderr 识别。
        if route_type is None and result.exit_code != 0 and "unreachable" in result.stderr.lower():
            route_type = "unreachable"

        return RouteLookupResult(
            source=source,
            destination=destination,
            successful=result.exit_code == 0,
            reachable=route_type in _REACHABLE_ROUTE_TYPES,
            route_type=route_type,
            gateway=gateway,
            interface=interface,
            source_address=source_address,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    @staticmethod
    def _parse_trace_report(output: str) -> list[TraceHop]:
        """把 ``mtr --report`` 输出解析成逐跳统计列表。

        数据行以 ``|--`` 标记，字段顺序固定：跳号 |-- 对端 Loss% Snt Last Avg Best Wrst StDev。
        """
        hops: list[TraceHop] = []
        for line in output.splitlines():
            if "|--" not in line:
                continue
            fields = line.split()
            if len(fields) < 8:
                continue
            try:
                hop = int(fields[0].split(".")[0])
            except ValueError:
                continue
            host_token = fields[1]
            hops.append(
                TraceHop(
                    hop=hop,
                    host=None if host_token == "???" else host_token,
                    loss_percent=_as_float(fields[2].rstrip("%")),
                    sent=_as_int(fields[3]),
                    last_ms=_as_float(fields[4]),
                    avg_ms=_as_float(fields[5]),
                    best_ms=_as_float(fields[6]),
                    worst_ms=_as_float(fields[7]),
                    stdev_ms=_as_float(fields[8]) if len(fields) > 8 else None,
                )
            )
        return hops

    # 方法签名
    def path_trace(
        self,
        source: str,
        target: str,
        count: int = 5,
    ) -> PathTraceResult:
        """用 mtr report 模式追踪到目标的逐跳路径与每跳质量。"""
        result = self._backend.execute(
            source,
            # 注意：用短选项 -c（等价 --report-cycles）；部分 mtr 版本不认 --count
            ["mtr", "--report", "-c", str(count), "--no-dns", target],
        )

        hops = self._parse_trace_report(result.stdout)
        # 目标可达的语义：最后一跳有响应（host 不是 ???）。
        # 注意 mtr 即使目标不可达也常以退出码 0 结束，因此不能只看退出码。
        target_reached = bool(hops) and hops[-1].host is not None

        return PathTraceResult(
            source=source,
            target=target,
            successful=result.exit_code == 0,
            target_reached=target_reached,
            hops=hops,
            exit_code=result.exit_code,
            stderr=result.stderr,
            raw_output=result.stdout,
        )

    @staticmethod
    def _parse_ss_line(line: str) -> ListenSocket | None:
        """把 ``ss -tulnp`` 输出的一行解析成一条监听套接字。

        字段顺序固定：Netid State Recv-Q Send-Q Local Peer Process；
        表头行（Netid 开头）直接跳过。
        """
        # 按空白切分；表头行首 token 是 Netid，跳过
        fields = line.split()
        if not fields or fields[0] == "Netid":
            return None
        if len(fields) < 6:
            return None

        # 拆本地/对端地址与端口
        local_address, local_port = _split_addr_port(fields[4])
        peer_address, peer_port = _split_addr_port(fields[5])
        # 进程信息可选：-p 失败或无权限时可能缺失
        process_name: str | None = None
        pid: int | None = None
        if len(fields) > 6:
            process_name, pid = _parse_process(fields[6])

        return ListenSocket(
            netid=fields[0],
            state=fields[1],
            local_address=local_address,
            local_port=local_port,
            peer_address=peer_address,
            peer_port=peer_port,
            process_name=process_name,
            pid=pid,
        )

    # 方法签名
    def listen_sockets(
        self,
        source: str,
        include_raw_output: bool = False,
    ) -> ListenSocketsResult:
        """查看仿真节点上监听中的 TCP/UDP 套接字及其进程。"""
        # 拼命令并执行：-t/-u 只看 TCP/UDP，-l 只看监听态，-n 数字端口，-p 显示进程
        result = self._backend.execute(source, ["ss", "-tulnp"])

        sockets: list[ListenSocket] = []
        # 逐行解析，表头行或无法映射的行直接丢弃
        for line in result.stdout.splitlines():
            socket = self._parse_ss_line(line)
            if socket is not None:
                sockets.append(socket)

        # 组装最终的结果，并返回
        return ListenSocketsResult(
            source=source,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            sockets=sockets,
            stderr=result.stderr,
            raw_output=result.stdout if include_raw_output else None,
        )
    @staticmethod
    def _parse_ifinfo_line(line: str) -> NetworkInfo | None:
        """把 /ifinfo.txt 的一行解析成一条仿真网络信息。

        行格式（seed-emulator Base.py 写入）：``网络名:前缀:延迟:带宽:丢包``；
        字段可能缺失（emulator 版本差异），缺失部分用 None 表达。
        """
        fields = line.split(":")
        if not fields or not fields[0].strip():
            # 空行或网络名为空的行无法归属，直接丢弃
            return None
        return NetworkInfo(
            name=fields[0].strip(),
            prefix=fields[1].strip() if len(fields) > 1 and fields[1].strip() else None,
            latency=fields[2].strip() if len(fields) > 2 and fields[2].strip() else None,
            bandwidth=fields[3].strip() if len(fields) > 3 and fields[3].strip() else None,
            drop=fields[4].strip() if len(fields) > 4 and fields[4].strip() else None,
        )

    # 方法签名
    def node_networks(
        self,
        source: str,
        include_raw_output: bool = False,
    ) -> NodeNetworksResult:
        """查看仿真节点连接的仿真网络及其链路属性配置（读 /ifinfo.txt）。"""
        result = self._backend.execute(source, ["cat", "/ifinfo.txt"])

        networks: list[NetworkInfo] = []
        # parse_failed：命令成功但 stdout 非空且一行都没解析出来——
        # 区分"文件为空（合法状态）"与"格式不识别（emulator 版本差异）"
        parse_failed = False
        if result.exit_code == 0:
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            for line in lines:
                info = self._parse_ifinfo_line(line)
                if info is not None:
                    networks.append(info)
            parse_failed = bool(lines) and not networks

        return NodeNetworksResult(
            source=source,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            parse_failed=parse_failed,
            networks=networks,
            stderr=result.stderr,
            raw_output=result.stdout if include_raw_output else None,
        )

    @staticmethod
    def _parse_qdisc_line(line: str) -> tuple[str, QdiscInfo] | None:
        """把 ``tc qdisc show`` 的一行解析成 (接口名, 排队规则)。

        行结构：``qdisc <kind> <handle>: dev <iface> [root|parent <x>] [参数...]``；
        只提取 emulator 链路属性相关的参数（rate/delay/loss/limit/burst），
        其余（lat/mtu/overhead 等）保留在 raw_output 中；无法归属到接口的行返回 None。
        """
        fields = line.split()
        if not fields or fields[0] != "qdisc" or len(fields) < 3:
            return None

        kind = fields[1]
        handle = fields[2].rstrip(":")
        interface: str | None = None
        parent: str | None = None
        rate: str | None = None
        delay: str | None = None
        loss: str | None = None
        limit: str | None = None
        burst: str | None = None

        index = 3
        while index < len(fields):
            token = fields[index]
            if token == "dev" and index + 1 < len(fields):
                interface = fields[index + 1]
                index += 2
            elif token == "root":
                parent = "root"
                index += 1
            elif token == "parent" and index + 1 < len(fields):
                parent = fields[index + 1]
                index += 2
            elif token in {"rate", "delay", "loss", "limit", "burst"} and index + 1 < len(fields):
                value = fields[index + 1]
                if token == "rate":
                    rate = value
                elif token == "delay":
                    delay = value
                elif token == "loss":
                    loss = value
                elif token == "limit":
                    limit = value
                else:
                    burst = value
                index += 2
            else:
                index += 1

        if interface is None:
            return None
        return interface, QdiscInfo(
            kind=kind,
            handle=handle,
            parent=parent,
            rate=rate,
            delay=delay,
            loss=loss,
            limit=limit,
            burst=burst,
        )

    # 方法签名
    def link_properties_inspect(
        self,
        source: str,
        include_raw_output: bool = False,
    ) -> LinkPropertiesResult:
        """查看仿真节点接口上实际生效的链路属性（tc qdisc：tbf 限速 + netem 延迟/丢包）。"""
        result = self._backend.execute(source, ["tc", "qdisc", "show"])

        # 按接口分组，保持首次出现顺序
        by_interface: dict[str, list[QdiscInfo]] = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parsed = self._parse_qdisc_line(line)
            if parsed is not None:
                interface, qdisc = parsed
                by_interface.setdefault(interface, []).append(qdisc)

        interfaces = [
            InterfaceLinkState(interface=name, qdiscs=qdiscs)
            for name, qdiscs in by_interface.items()
        ]

        return LinkPropertiesResult(
            source=source,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            interfaces=interfaces,
            stderr=result.stderr,
            raw_output=result.stdout if include_raw_output else None,
        )
    # 方法签名
    def route_update(
        self,
        source: str,
        operation: str,
        destination: str,
        gateway: str | None = None,
        interface: str | None = None,
        route_type: str = "unicast",
    ) -> RouteUpdateResult:
        """运行时增删内核路由表条目（ip route add/del，非持久）。

        注意：写操作不保证持久（重启容器即还原），只适合实验/假设验证；
        在 hnode（host）上最安全——rnode 上 bird 可能把路由抢回。
        """
        if operation == "add":
            command = ["ip", "route", "add"]
            if route_type == "blackhole":
                command.append("blackhole")
            command.append(destination)
        else:
            command = ["ip", "route", "del", destination]
        if gateway is not None:
            command += ["via", gateway]
        if interface is not None:
            command += ["dev", interface]

        result = self._backend.execute(source, command)

        return RouteUpdateResult(
            source=source,
            operation=operation,
            destination=destination,
            gateway=gateway,
            interface=interface,
            route_type=route_type,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    # 方法签名
    def link_update(self, source: str, interface: str, state: str) -> LinkUpdateResult:
        """运行时将接口置为 up/down（ip link set，模拟链路故障，非持久）。

        官方 ``seedemu_worker`` 的 ``net_up/net_down`` 是脚本级操作；
        本工具是接口粒度版。语义：实验/假设验证，重启即还原。
        """
        result = self._backend.execute(source, ["ip", "link", "set", interface, state])

        return LinkUpdateResult(
            source=source,
            interface=interface,
            state=state,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    # 方法签名
    def link_properties_update(
        self,
        source: str,
        interface: str,
        latency: str | None = None,
        bandwidth: str | None = None,
        drop: str | None = None,
    ) -> LinkPropertiesUpdateResult:
        """运行时改链路属性（tc qdisc 读-合并-替换，非持久）。

        未指定的属性读取当前生效值并保持；接口尚无 tbf/netem 时按文档化默认
        （rate=100Mbit、burst=2000b、latency=400.0ms、limit=1000）补充。
        """
        # 1) 读当前生效值（复用 inspect 逻辑），未指定的属性保持现状
        current = self.link_properties_inspect(source)
        iface_state = next(
            (state for state in current.interfaces if state.interface == interface),
            None,
        )
        tbf = next(
            (q for q in iface_state.qdiscs if q.kind == "tbf"), None
        ) if iface_state is not None else None
        netem = next(
            (q for q in iface_state.qdiscs if q.kind == "netem"), None
        ) if iface_state is not None else None

        commands: list[list[str]] = []
        # 合并结果的预置值：只填充本次触及的参数，其余保持 None（供 effective 汇报）
        rate: str | None = None
        burst: str | None = None
        latency_bound: str | None = None
        delay: str | None = None
        loss: str | None = None
        limit: str | None = None
        if bandwidth is not None:
            # 合并：rate 用新值；burst 沿用当前值，查不到用文档化默认
            rate = bandwidth
            burst = tbf.burst if tbf is not None and tbf.burst else "2000b"
            latency_bound = "400.0ms"  # tbf 的时延上界默认值（QdiscInfo 不建模 lat）
            qdisc = "replace" if tbf is not None else "add"
            commands.append(
                ["tc", "qdisc", qdisc, "dev", interface, "root", "handle", "1:",
                 "tbf", "rate", rate, "burst", burst, "latency", latency_bound]
            )
        if latency is not None or drop is not None:
            # 合并：delay/loss 用新值；未指定的沿用当前值（查不到归零）
            delay = latency if latency is not None else (
                netem.delay if netem is not None and netem.delay else "0ms"
            )
            loss = drop if drop is not None else (
                netem.loss if netem is not None and netem.loss else "0%"
            )
            limit = netem.limit if netem is not None and netem.limit else "1000"
            if tbf is None:
                # netem 需要 parent 1:1（tbf 的子队列）：接口还没有 tbf 时先补一个（默认速率）
                commands.append(
                    ["tc", "qdisc", "add", "dev", interface, "root", "handle", "1:",
                     "tbf", "rate", "100Mbit", "burst", "2000b", "latency", "400.0ms"]
                )
            qdisc = "replace" if netem is not None else "add"
            commands.append(
                ["tc", "qdisc", qdisc, "dev", interface, "parent", "1:1", "handle", "8002:",
                 "netem", "limit", limit, "delay", delay, "loss", loss]
            )

        # 2) 逐条执行并记录退出码
        executed: list[UpdateCommand] = []
        all_ok = True
        for command in commands:
            result = self._backend.execute(source, command)
            executed.append(
                UpdateCommand(command=command, exit_code=result.exit_code, stderr=result.stderr)
            )
            all_ok = all_ok and result.exit_code == 0

        # 3) 汇报实际写入值（读-合并-替换的最终结果，含从当前值保持的部分）
        effective = EffectiveLinkProperties(
            rate=rate if bandwidth is not None else None,
            burst=burst if bandwidth is not None else None,
            latency_bound=latency_bound if bandwidth is not None else None,
            delay=delay if (latency is not None or drop is not None) else None,
            loss=loss if (latency is not None or drop is not None) else None,
            limit=limit if (latency is not None or drop is not None) else None,
        )

        return LinkPropertiesUpdateResult(
            source=source,
            interface=interface,
            latency=latency,
            bandwidth=bandwidth,
            drop=drop,
            successful=all_ok,
            executed=executed,
            effective=effective,
        )

    # 方法签名
    def reachability_map(
        self,
        sources: list[str],
        targets: list[str],
        count: int = 1,
        timeout_seconds: int = 2,
    ) -> ReachabilityMapResult:
        """批量 ICMP 连通矩阵：多源 × 多目标，逐对 ping（C 类批量只读）。

        注意：N×M 次 docker exec 是串行执行，列表过大时耗时会显著；
        count 默认 1（每对只探测一次）以控制开销。
        """
        entries: list[ReachabilityEntry] = []
        for source in sources:
            for target in targets:
                result = self._backend.execute(
                    source,
                    ["ping", "-c", str(count), "-W", str(timeout_seconds), target],
                )
                entries.append(
                    ReachabilityEntry(
                        source=source,
                        target=target,
                        reachable=result.exit_code == 0,
                        exit_code=result.exit_code,
                        round_trip_ms=_parse_ping_rtt(result.stdout),
                    )
                )

        return ReachabilityMapResult(
            sources=sources,
            targets=targets,
            count=count,
            timeout_seconds=timeout_seconds,
            successful=True,
            reachable_count=sum(1 for entry in entries if entry.reachable),
            total_pairs=len(entries),
            entries=entries,
        )
    @staticmethod
    def _parse_iptables_rules(output: str) -> list[FirewallChain]:
        """把 ``iptables -S -t <table>`` 输出解析成链列表。

        行格式：``-P <链> <策略>``（默认策略）或 ``-A <链> <规则体>``（规则）；
        链按首次出现顺序排列；无法识别的行直接跳过（P6 容错）。
        """
        chain_order: list[str] = []
        chains: dict[str, FirewallChain] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^(-P|-A|-I|-D|-R) (\S+)(?: (.+))?$", line)
            if match is None:
                continue
            action, name, spec = match.group(1), match.group(2), match.group(3)
            if name not in chains:
                chains[name] = FirewallChain(name=name, policy=None, rules=[])
                chain_order.append(name)
            if action == "-P":
                chains[name].policy = spec
            else:
                chains[name].rules.append(f"{action} {spec}" if spec else action)
        return [chains[name] for name in chain_order]

    # 方法签名
    def packet_capture(
        self,
        source: str,
        interface: str = "any",
        count: int = 10,
        timeout_seconds: int = 5,
        filter_expression: str | None = None,
    ) -> PacketCaptureResult:
        """用 tcpdump 抓包（F 类兜底：原始证据，不做翻译）。

        ``timeout(1)`` 做墙钟上限——tcpdump 的 -c 只按包数退出，静默链路上会挂住；
        退出码 124 表示超时截断（timed_out=True），不是命令失败。
        """
        # timeout(1) 是 coreutils 基础命令，seedemu-base 必然预装
        command = [
            "timeout",
            str(timeout_seconds),
            "tcpdump",
            "-i",
            interface,
            "-c",
            str(count),
            "-nn",
        ]
        if filter_expression is not None:
            # tcpdump 会把所有非选项参数拼接为 BPF 表达式，传一个 token 即可
            command.append(filter_expression)

        result = self._backend.execute(source, command)
        packets = [line for line in result.stdout.splitlines() if line.strip()]

        return PacketCaptureResult(
            source=source,
            interface=interface,
            count=count,
            timeout_seconds=timeout_seconds,
            filter_expression=filter_expression,
            successful=result.exit_code == 0,
            timed_out=result.exit_code == 124,  # timeout(1) 约定：124 = 超时被杀
            packets=packets,
            exit_code=result.exit_code,
            stderr=result.stderr,
            raw_output=result.stdout,
        )

    # 方法签名
    def firewall_inspect(
        self,
        source: str,
        table: str = "filter",
        include_raw_output: bool = False,
    ) -> FirewallInspectResult:
        """查看节点防火墙规则（iptables -S，条件可用：基础镜像无 iptables）。

        iptables 在**内核里悄悄丢包**，A/B/C 类工具都看不见；
        命令不存在时 successful=False 且 stderr 为 "iptables: not found"。
        """
        result = self._backend.execute(source, ["iptables", "-S", "-t", table])

        chains: list[FirewallChain] = []
        if result.exit_code == 0:
            chains = self._parse_iptables_rules(result.stdout)

        return FirewallInspectResult(
            source=source,
            table=table,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            chains=chains,
            stderr=result.stderr,
            raw_output=result.stdout if include_raw_output else None,
        )

    # 方法签名
    def firewall_update(
        self,
        source: str,
        action: str,
        chain: str,
        rule: str,
    ) -> FirewallUpdateResult:
        """运行时增删防火墙规则（iptables -A/-D，条件可用 + 非持久）。

        注意：错误的规则（如 DROP INPUT 全部流量）可能把节点锁死；
        rule 按空白拆成 argv token（无 shell，安全），带引号参数暂不支持。
        """
        flag = "-A" if action == "append" else "-D"
        command = ["iptables", flag, chain] + rule.split()

        result = self._backend.execute(source, command)

        return FirewallUpdateResult(
            source=source,
            action=action,
            chain=chain,
            rule=rule,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    # 方法签名
    def neighbor_update(
        self,
        source: str,
        operation: str,
        destination: str,
        interface: str,
        lladdr: str | None = None,
    ) -> NeighborUpdateResult:
        """运行时增删内核邻居表条目（ip neigh add/del，ARP 实验，非持久）。

        ``add`` 必须带 MAC（lladdr，入参层已校验）；``del`` 按 (destination, interface) 匹配。
        """
        command = ["ip", "neigh", operation, destination]
        if operation == "add":
            command += ["lladdr", lladdr]
        command += ["dev", interface]

        result = self._backend.execute(source, command)

        return NeighborUpdateResult(
            source=source,
            operation=operation,
            destination=destination,
            interface=interface,
            lladdr=lladdr,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stderr=result.stderr,
        )

    # 方法签名
    def sysctl_update(self, source: str, key: str, value: str) -> SysctlUpdateResult:
        """运行时改内核 net.* 参数（sysctl -w，非持久）。

        键只允许 net.* 命名空间（入参层已校验）；stdout 保留 sysctl 确认行作为证据。
        """
        result = self._backend.execute(source, ["sysctl", "-w", f"{key}={value}"])

        return SysctlUpdateResult(
            source=source,
            key=key,
            value=value,
            successful=result.exit_code == 0,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )


