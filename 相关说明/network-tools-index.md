# network 域工具索引

> network 域当前 8 个工具的一览索引：功能、底层命令、入参、输出要点、调用示例。
> 开发过程细节见 `learning/开发日志/`（按 A–F 分类归档，每类一个子目录，含目录 README 与分类↔工具↔日志对照表）。
> 开发方法论见 `learning/framework.md`；开发反思与踩坑汇总见 `learning/network-dev-reflections.md`；
> 工具分类与完整性框架见 `learning/network-domain-framework.md`（分类坐标系 + 完整性矩阵 + 缺口分析）。

---

## 工具总览

| 工具 | 类型 | 底层命令 | 一句话功能 |
|---|---|---|---|
| `network.cidr_inspect` | 纯计算 | ipaddress 模块 | 归一化 CIDR 并报告网段/掩码/主机范围/包含关系 |
| `network.firewall_inspect` | 命令型 + 文本 | `iptables -S` | 防火墙链/策略/规则（条件可用：基础镜像无 iptables） |
| `network.firewall_update` | 命令型（写） | `iptables -A/-D` | 运行时增删防火墙规则（条件可用 + 非持久） |
| `network.inspect_ip_address` | 纯计算 | ipaddress 模块 | 归一化 IP 并报告属性 |
| `network.interface_inspect` | 命令型 + JSON | `ip -j addr show` | 查看接口/地址/状态/MTU/MAC |
| `network.link_properties_inspect` | 命令型 + 文本 | `tc qdisc show` | 链路属性实际生效值（tbf/netem） |
| `network.link_properties_update` | 命令型（写） | `tc qdisc replace` | 运行时改延迟/带宽/丢包（读-合并-替换，非持久） |
| `network.link_update` | 命令型（写） | `ip link set up/down` | 接口粒度模拟链路故障（非持久） |
| `network.listen_sockets` | 命令型 + 文本 | `ss -tulnp` | 查看 TCP/UDP 监听端口及进程 |
| `network.neighbor_inspect` | 命令型 + JSON | `ip -j neigh show` | 查看 ARP/ND 邻居表 |
| `network.neighbor_update` | 命令型（写） | `ip neigh add/del` | 运行时增删邻居表条目（ARP 实验，非持久） |
| `network.node_networks` | 命令型 + 文本 | `cat /ifinfo.txt` | 节点连接的仿真网络及链路属性配置 |
| `network.packet_capture` | 命令型 + 文本 | `tcpdump -c -nn` | 抓原始包（按包数/墙钟上限截断，F 类兜底） |
| `network.path_trace` | 命令型 + 文本 | `mtr --report -c N --no-dns <target>` | 逐跳路径 + 每跳丢包/RTT |
| `network.ping` | 命令型 | `ping` | ICMP 可达性测试 |
| `network.reachability_map` | 命令型（批量） | `ping` × N×M | 多源×多目标连通矩阵 |
| `network.route_inspect` | 命令型 + 文本 | `ip route show` | 查看内核路由表 |
| `network.route_lookup` | 命令型 + 文本 | `ip route get <dest>` | 查询到某目标的真实选路 |
| `network.route_update` | 命令型（写） | `ip route add/del` | 运行时增删内核路由（含黑洞路由，非持久） |
| `network.sysctl_update` | 命令型（写） | `sysctl -w` | 运行时改内核 net.* 参数（限 net.* 命名空间，非持久） |

---

## 各工具详述

### network.cidr_inspect

- **功能**：归一化 IPv4/IPv6 CIDR 子网并报告网段/掩码/广播/主机范围/地址数/属性，可选测试某 IP 或子网的包含关系；
- **底层**：纯 Python `ipaddress` 模块（**不碰容器**，纯计算型）；
- **入参**：`network`（CIDR，strict=False 容忍主机位）、`contains`（可选，IP 或 CIDR）；
- **输出**：`CidrInfo{network, version, prefixlen, netmask, broadcast, num_addresses, num_hosts, first_host, last_host, is_private, is_global, is_loopback, is_link_local, contains, contains_type, contains_result}`；
- **注意**：IPv4 的 `num_hosts` 手工计算（不依赖已废弃的 `num_hosts` 属性，跨 Python 版本稳定）；/31 可用 2 个、/32 可用 1 个地址；IPv6 无广播概念（broadcast=None）、主机数无实用语义（num_hosts=None）。

### network.firewall_inspect

- **功能**：查看节点防火墙——链、默认策略、规则清单（iptables 在内核悄悄丢包，A/B/C 类都看不见，这是唯一能看它的工具）；
- **底层**：`iptables -S -t <table>`（默认 filter 表；**条件可用**：基础镜像无 iptables，命令缺失时 successful=False + stderr 报 not found）；
- **入参**：`source`、`table`（filter/nat/mangle/raw/security，默认 filter）、`include_raw_output`（可选）；
- **输出**：`FirewallInspectResult{source, table, successful, exit_code, chains[], stderr, raw_output}`；
  - `FirewallChain{name, policy, rules[]}`（rules 为 `-A <规则体>` 原始串）
- **注意**：解析器只认 `-P`/`-A`/`-I`/`-D`/`-R` 行，无法识别的行跳过（容错）；链按出现顺序排列。


### network.firewall_update

- **功能**：运行时增删防火墙规则（`iptables -A/-D`，条件可用 + 非持久）；
- **底层**：`iptables -A/-D <链> <规则体>`（rule 按空白拆 argv，无 shell）；
- **入参**：`source`、`action`（append/delete）、`chain`（链名校验）、`rule`（空白分隔的规则体，如 `-p tcp --dport 22 -j DROP`）；
- **输出**：`FirewallUpdateResult{source, action, chain, rule, successful, exit_code, stderr}`；
- **注意**：⚠️ 错误的规则（如 DROP INPUT 全部流量）可能把节点锁死；带引号的规则参数（如 `-m string --string "x y"`）暂不支持。

### network.inspect_ip_address

- **功能**：归一化 IPv4/IPv6 地址并报告标准属性；
- **底层**：纯 Python `ipaddress` 模块（**不碰容器**，纯计算型）；
- **入参**：`address`；
- **输出**：`IPAddressInfo{address, version, is_private, is_loopback, is_multicast, is_global}`；
- **示例**：`inspect_ip_address("2001:0db8::1")` → `address: "2001:db8::1", version: 6`。

### network.interface_inspect

- **功能**：查看节点所有网络接口——名称、up 状态、operstate、MTU、MAC、绑定地址；
- **底层**：`ip -j addr show`（iproute2 JSON 输出）；
- **入参**：`source`、`include_raw_output`（可选，诊断用）；
- **输出**：`InterfaceInspectResult{successful, exit_code, parse_failed, interfaces[], stderr, raw_output}`；
  - `InterfaceInfo{name, up, operstate, mtu, mac_address, addresses[]}`
  - `InterfaceAddress{family, local, prefixlen, scope}`
- **注意**：`mac_address` 仅 ether 链路返回（lo 为 null）；`parse_failed` 区分"空/成功"与"解析失败"。

### network.neighbor_inspect

- **功能**：查看内核邻居表（ARP + IPv6 ND）——对端 IP、MAC、接口、解析状态；
- **底层**：`ip -j neigh show`（JSON 输出）；
- **入参**：`source`、`include_raw_output`（可选）；
- **输出**：`NeighborInspectResult{successful, parse_failed, entries[], stderr}`；
  - `NeighborEntry{destination, lladdr, interface, state[], is_router}`
- **注意**：`lladdr` 未解析时为 null；`is_router` 由 flags 推导；**空表是合法状态**（successful=true, entries=[]）。

### network.neighbor_update

- **功能**：运行时增删内核邻居表条目（ARP 实验，非持久）；
- **底层**：`ip neigh add/del`；
- **入参**：`source`、`operation`（add/del）、`destination`（IP 强校验）、`interface`（格式校验）、`lladdr`（MAC 格式校验，**add 必填**）；
- **输出**：`NeighborUpdateResult{source, operation, destination, interface, lladdr, successful, exit_code, stderr}`；
- **注意**：add 必须带 MAC（入参层 model_validator 兜底）；del 按 (destination, interface) 匹配；手工邻居条目是实验语义，重启还原。

### network.link_properties_inspect

- **功能**：查看节点各接口上**实际生效**的链路属性——tbf 限速（rate/burst）+ netem 延迟/丢包（delay/loss），按接口分组；
- **底层**：`tc qdisc show`（iproute2 文本，关键字扫描）；
- **入参**：`source`、`include_raw_output`（可选）；
- **输出**：`LinkPropertiesResult{successful, exit_code, interfaces[], stderr, raw_output}`；
  - `InterfaceLinkState{interface, qdiscs[]}` → `QdiscInfo{kind, handle, parent, rate, delay, loss, limit, burst}`
- **注意**：只提取 emulator 链路属性相关参数（rate/delay/loss/limit/burst），其余（lat/mtu/overhead 等）保留在 raw_output；tbf 的 `lat` 是时延上界、不是 netem 延迟，不建模以免 Agent 混淆。

### network.link_properties_update

- **功能**：运行时改接口的链路属性——延迟（netem delay）、带宽（tbf rate）、丢包（netem loss），**读-合并-替换**（未指定的属性读取当前生效值并保持）；
- **底层**：`tc qdisc show`（读当前）+ `tc qdisc replace/add`（改，非持久）；
- **入参**：`source`、`interface`（格式校验）、`latency` / `bandwidth` / `drop`（至少给一个；值格式校验，drop 纯数字自动补 `%`）；
- **输出**：`LinkPropertiesUpdateResult{source, interface, latency, bandwidth, drop, successful, executed[], effective}`；
  - `UpdateCommand{command, exit_code, stderr}`（逐条记录已执行的 tc 命令）
  - `effective{rate, burst, latency_bound, delay, loss, limit}`（读-合并-替换后**实际写入**的值，未触及的为 null）
- **注意**：`successful`=所有命令退出码为 0；接口尚无 tbf/netem 时按默认（rate=100Mbit、burst=2000b、latency=400.0ms、limit=1000）**补建**；写操作非持久，重启即还原。


### network.link_update

- **功能**：把接口置为 up/down，接口粒度模拟链路故障（官方 `net_up/net_down` 的细化版）；
- **底层**：`ip link set <iface> up/down`（非持久）；
- **入参**：`source`、`interface`（格式校验）、`state`（up/down）；
- **输出**：`LinkUpdateResult{source, interface, state, successful, exit_code, stderr}`；
- **注意**：故障注入后可用 `link_update up` 恢复；`ip link set` 不需要 root 权限即可操作仿真容器内接口（取决于容器运行时）。

### network.listen_sockets

- **功能**：查看节点监听中的 TCP/UDP 套接字——协议、状态、本地/对端地址端口、进程名与 PID；
- **底层**：`ss -tulnp`（iproute2，文本解析）；
- **入参**：`source`、`include_raw_output`（可选）；
- **输出**：`ListenSocketsResult{successful, exit_code, sockets[], stderr, raw_output}`；
  - `ListenSocket{netid, state, local_address, local_port, peer_address, peer_port, process_name, pid}`
- **注意**：`-p` 无权限时进程信息缺失（process_name/pid 为 null）；IPv6 地址解析为不带方括号的形式。

### network.route_inspect

- **功能**：查看内核路由表，返回结构化路由条目；
- **底层**：`ip route show`（文本，关键字扫描 via/dev/src）；
- **入参**：`source`；
- **输出**：`RouteInspectResult{successful, exit_code, routes[], stderr}`；
  - `RouteEntry{destination, gateway, interface, source}`（可选字段为 null）

### network.route_lookup

- **功能**：查询内核"到某个具体目标实际走哪条路由"（含策略路由规则）；
- **底层**：`ip route get <dest>`（文本关键字扫描 + stderr 兜底）；
- **入参**：`source`、`destination`（**ipaddress 强校验**，必须是 IP）；
- **输出**：`RouteLookupResult{successful, reachable, route_type, gateway, interface, source_address, exit_code, stderr}`；
- **语义**：`successful`=退出码；`reachable`=路由类型属于 unicast/local/broadcast/multicast；
  `route_type` 可为 unicast/local/unreachable/blackhole 等；unreachable 时 exit_code=2 且错误在 stderr。

### network.route_update

- **功能**：运行时增删内核路由条目——普通路由（via/dev）与黑洞路由（blackhole）；
- **底层**：`ip route add/del`（非持久）；
- **入参**：`source`、`operation`（add/del）、`destination`（CIDR 或 `default`）、`gateway`（可选，IP 校验）、`interface`（可选）、`route_type`（unicast/blackhole，默认 unicast）；
- **输出**：`RouteUpdateResult{source, operation, destination, gateway, interface, route_type, successful, exit_code, stderr}`；
- **注意**：跨字段校验——黑洞路由不能带 via/dev，普通 add 必须有 via 或 dev；**在 hnode 上最安全**（host 无 bird，rnode 上 bird 可能把路由抢回）；失败时 stderr 保留 RTNETLINK 原始错误。

### network.sysctl_update

- **功能**：运行时改内核 net.* 参数（A 类节点状态·写，非持久）；
- **底层**：`sysctl -w <key>=<value>`；
- **入参**：`source`、`key`（**只允许 net.* 命名空间**，防误写内核其他区域）、`value`（无空格值，参数向量防注入）；
- **输出**：`SysctlUpdateResult{source, key, value, successful, exit_code, stdout, stderr}`（stdout 保留确认行如 `net.ipv4.ip_forward = 1`）；
- **注意**：典型用法 `net.ipv4.ip_forward=1`（开转发）、`net.ipv4.icmp_echo_ignore_all=1`（关 ICMP 响应）；改完即生效，重启还原。

### network.node_networks

- **功能**：查看节点连接的**仿真网络**清单及每个网络配置的链路属性（网络名/前缀/延迟/带宽/丢包）；
- **底层**：`cat /ifinfo.txt`（seed-emulator Base.py 写入的配置清单）；
- **入参**：`source`、`include_raw_output`（可选）；
- **输出**：`NodeNetworksResult{successful, exit_code, parse_failed, networks[], stderr, raw_output}`；
  - `NetworkInfo{name, prefix, latency, bandwidth, drop}`（缺失字段为 null）
- **注意**：行格式 `网络名:前缀:延迟:带宽:丢包`，字段缺失容忍（None）；`parse_failed` 区分"文件为空（合法）"与"格式不识别（emulator 版本差异）"。

### network.packet_capture

- **功能**：用 tcpdump 抓原始包（F 类兜底：**无假设、看原始证据**，不做翻译）；
- **底层**：`timeout <秒> tcpdump -i <iface> -c <包数> -nn [BPF 过滤]`（tcpdump 预装；`timeout(1)` 做墙钟上限，防静默链路挂住）；
- **入参**：`source`、`interface`（默认 any）、`count`（默认 10，1-100）、`timeout_seconds`（默认 5，1-30）、`filter_expression`（可选 BPF，如 `tcp port 80`，≤200 字符）；
- **输出**：`PacketCaptureResult{source, interface, count, timeout_seconds, filter_expression, successful, timed_out, packets[], exit_code, stderr, raw_output}`；
  - `packets` 为原始 tcpdump 行（一行一包）；`timed_out` 表示 timeout 截断（退出码 124，**不是失败**）
- **注意**：需要 root/CAP_NET_RAW（仿真容器默认满足）；`-nn` 关闭主机名/端口解析保证可解析性；过滤表达式整体作为一个 argv token（tcpdump 会拼接）。

### network.path_trace

- **功能**：用 mtr report 模式追踪到目标的逐跳路径，含每跳丢包率与 RTT 统计；
- **底层**：`mtr --report -c N --no-dns <target>`（固定列解析）；
- **入参**：`source`、`target`（IP 或 hostname）、`count`（默认 5，1-20）；
- **输出**：`PathTraceResult{successful, target_reached, hops[], exit_code, stderr, raw_output}`；
  - `TraceHop{hop, host, loss_percent, sent, last_ms, avg_ms, best_ms, worst_ms, stdev_ms}`
- **注意**：`target_reached` 由最后一跳推导（mtr 目标不可达也退出码 0）；`???` 跳 host 为 null；
  探测数用 `-c`（部分版本不认 `--count`）。

### network.ping

- **功能**：ICMP 可达性测试；
- **底层**：`ping -c N -W T <target>`；
- **入参**：`source`、`target`、`count`（默认 3，1-10）、`timeout_seconds`（默认 2，1-30）；
- **输出**：`ReachabilityResult{source, target, reachable, exit_code, stdout, stderr}`。

### network.reachability_map

- **功能**：批量 ICMP 连通矩阵——多源 × 多目标逐对 ping，回答"这些节点两两之间通不通"；
- **底层**：`ping -c N -W T <target>` × (N×M)（批量只读）；
- **入参**：`sources`（1-20）、`targets`（1-20）、`count`（默认 1，1-5）、`timeout_seconds`（默认 2，1-10）；
- **输出**：`ReachabilityMapResult{sources, targets, count, timeout_seconds, successful, reachable_count, total_pairs, entries[]}`；
  - `ReachabilityEntry{source, target, reachable, exit_code, round_trip_ms}`
- **注意**：N×M 次 docker exec **串行**执行，列表过大耗时显著（count 默认 1 控制开销）；`successful`=探测全部完成（**不是**全部可达），逐对可达性看 entries。

---

## 排障场景速查

| 想回答的问题 | 用哪个工具 |
|---|---|
| 节点有哪些网卡/地址/状态 | `network.interface_inspect` |
| 节点在监听哪些端口/哪个进程 | `network.listen_sockets` |
| 二层通不通、对端 MAC 是什么 | `network.neighbor_inspect` |
| 路由表长什么样 | `network.route_inspect` |
| 到 X 的流量实际走哪 | `network.route_lookup` |
| 路径经过哪些跳、哪一跳丢包 | `network.path_trace` |
| 终点通不通（ICMP） | `network.ping` |
| IP 是公网/私网/回环/组播 | `network.inspect_ip_address` |
| 子网规划/网段范围/包含关系 | `network.cidr_inspect` |
| 节点连了哪些仿真网络、配了啥链路属性 | `network.node_networks` |
| 链路属性实际生效值（tbf/netem） | `network.link_properties_inspect` |
| 运行时改链路属性（延迟/带宽/丢包） | `network.link_properties_update` |
| 模拟链路故障（接口 down/up） | `network.link_update` |
| 多源×多目标连通矩阵 | `network.reachability_map` |
| 加/删静态或黑洞路由 | `network.route_update` |
| 抓原始包看协议行为 | `network.packet_capture` |
| 防火墙链/规则（条件可用） | `network.firewall_inspect` / `network.firewall_update` |
| ARP 邻居实验（加/删条目） | `network.neighbor_update` |
| 开转发/关 ICMP 响应等内核参数 | `network.sysctl_update` |

## 通用约定

- 所有命令型工具入参均有 `source`（容器名）；入参模型 `extra="forbid"` 严格校验（P4）；
- 结果统一保留 `successful` / `exit_code` / `stderr` 作为诊断证据（P2/P3）；
- 只读工具命名 `inspect` / `lookup` / `trace`；写操作命名 `update`（P8）；
- 写操作（route_update / link_update / link_properties_update / neighbor_update / sysctl_update / firewall_update）均为**运行时变更、非持久**（重启容器即还原），语义是实验/假设验证；
- **条件可用**：firewall_inspect / firewall_update 依赖 iptables（基础镜像无；**VM 实测当前 seed-emulator 版本所有容器均无**，需自行 apt-get install iptables 或定制镜像后方可用）；packet_capture 依赖 tcpdump（预装）；命令缺失时工具优雅降级（successful=False + stderr）；
- 底层依赖：iproute2（`ip` / `ss`）、`mtr`（seedemu-base 镜像预装）、`ping`；
- 命令一律用参数向量（argv list），不拼 shell 字符串（P1）。