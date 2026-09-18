# network.interface_inspect 开发日志

> 说明：本文档是 `interface_inspect` 从"一条命令"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；姊妹日志：`learning/route-inspect.md`

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.interface_inspect` |
| 功能 | 查看仿真节点（容器）的所有网络接口——名称、运行状态、MTU、MAC 地址、绑定的 IPv4/IPv6 地址 |
| 模仿命令 | `ip -j addr show`（iproute2，JSON 输出） |
| 类型 | 命令型 + JSON 结构化解析 |
| 涉及文件 | 5 个源码 + 2 个测试 + README + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定要开发一个"查看节点网络接口"的 network 工具；
- **为什么**：排障第一步是"我在哪"——接口/地址/状态是 Agent 最常查的信息；
  `route_inspect` 只覆盖 L3 路由，接口信息（L2/L3 身份）缺失；
- **决定**：封装 `ip -j addr show`——seedemu-base 镜像预装 iproute2，零新增依赖；
  且 `-j` 输出 JSON，比文本解析更稳；
- **产出**：一句话功能描述——"查看仿真节点所有网络接口及其地址"（命令型）。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `ip -j addr show` 的输出结构（黄金样本）；
- **观察到 5 个事实**：
  1. 顶层是 JSON **数组**，每个元素是一个接口；
  2. 接口字段：`ifname` / `flags` / `mtu` / `operstate` / `link_type` / `address` / `addr_info`；
  3. `flags` 是字符串数组，含 `UP`（管理启用）与 `LOWER_UP`（链路就绪）；`operstate` 是语义化状态；
  4. `address`（MAC）只对以太网链路存在（`link_type == "ether"`）；
  5. `addr_info` 是地址数组，`family` 为 `inet` / `inet6`，含 `local` / `prefixlen` / `scope`；
- **为什么重要**：这 5 个事实直接决定模型字段（`up` 布尔推导、`mac_address` 可选）
  和解析策略（JSON + family 过滤）；
- **产出**：黄金样本 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）——本次实际先做契约

- **做了什么**：在 `models.py` 写 `InterfaceInspectArguments` / `InterfaceAddress` / `InterfaceInfo` / `InterfaceInspectResult`；
- **关键决策**：
  - 入参：`source` + `include_raw_output`（可选，诊断用，对齐 DNS 域模式）；
  - 结果拆三层：`InterfaceInspectResult`（整体）→ `InterfaceInfo`（单接口）→ `InterfaceAddress`（单地址），可复用；
  - `up` 是布尔语义字段（由 flags 推导）；`operstate` / `mtu` / `mac_address` 用 `None` 表达缺失（P6）；
  - `parse_failed` 显式表达"命令成功但 JSON 无法解析"——JSON 解析是全有或全无，
    不同于 `route_inspect` 的逐行丢弃策略；
  - `extra="forbid"` + `Field(description)`（P4 安全边界 + Agent 说明书）；
- **遇到的问题**：中文注释 + JS 模板字符串的转义陷阱（route-inspect 日志条目 8 的同款问题）
  → 改用行数组拼接，不碰模板字符串；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：在 `tools.py` 写 `_parse_interface_json`（静态方法）+ `interface_inspect`；
- **关键决策**：
  - 命令用参数向量 `["ip", "-j", "addr", "show"]`，不拼 shell（P1）；
  - 解析 gate 在 `exit_code == 0` 上：命令失败时不解析 stdout（内容可能是报错文本）；
  - `json.loads` 包 try/except：解析失败返回 `([], False)` 而非抛异常（P6 容错）；
  - `family` 只认 `inet` / `inet6`，其余条目跳过；
  - `successful = result.exit_code == 0`（P2 语义映射）；`parse_failed` 独立表达解析状态；
  - `raw_output` 按 `include_raw_output` 决定是否返回（P3 证据保留）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：在 `registration.py` 注册 `network.interface_inspect`；
- **为什么**：注册后工具才可被发现；`input_schema` 由 `InterfaceInspectArguments` 自动推导（P10），无需手写；
- **产出**：`/api/v1/tools` 可见该工具（network 域达到 4 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 5 个用例 + 更新注册断言（3→4 个工具，索引顺移）；
- **黄金样本的构造**：用 dict + `json.dumps` 生成 stdout（避免在测试文件内嵌 JSON 字符串的转义问题）；
- **覆盖场景**：正常解析（含 IPv6 链路本地地址）、命令失败、JSON 解析失败、
  `raw_output` 透传、入参校验（`extra="forbid"` 拒绝未知参数）；
- **遇到的问题**：
  - 本机无 pytest/fastapi/pydantic 环境且沙箱禁止全局安装 → 用 `py_compile` 做语法检查，
    并用独立脚本（纯 stdlib）模拟解析逻辑验证 JSON 结构假设；真实 pytest + docker 端到端由虚拟机验证；
  - `test_api.py` 的 `count == 10` 需要同步改为 11（route-inspect 日志踩过的同款过期断言坑）；
- **产出**：测试用例 + 断言修复。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：`tool-service/README.md` 补 `interface_inspect` 条目 + `ip -j` JSON 解析说明；
- **小修正**："The initial network tools are" → "The network tools are"（不再是 initial）；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **说明**：由开发者（你）在 VM 中完成第 5 节验证；
- **回填条件**：若真实容器的 `ip -j addr show` 输出与测试黄金样本有差异（如字段缺失、
  IPv6 地址格式不同），按真实输出更新测试 fixture 后重跑 pytest。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 4 个类：InterfaceInspectArguments / InterfaceAddress / InterfaceInfo / InterfaceInspectResult |
| `tools/network/tools.py` | 新增 `import json` + `_parse_interface_json`（静态方法）+ `interface_inspect` 方法 |
| `tools/network/registration.py` | 新增 `network.interface_inspect` 注册块 |
| `tests/test_network_tools.py` | 注册断言 3→4（索引顺移）；新增 5 个用例 + `GOLDEN_INTERFACES` |
| `tests/test_api.py` | count 10→11；工具列表补 `network.interface_inspect` |
| `tool-service/README.md` | network 域补条目 + `ip -j` 解析说明 |
| `learning/interface-inspect.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
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
    """仿真节点上的一个网络接口。"""

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
    """查看节点网络接口的结果。"""

    source: str
    successful: bool
    exit_code: int
    parse_failed: bool = False
    interfaces: list[InterfaceInfo] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None
```

### tools.py 新增

```python
@staticmethod
# 接收字符串output输出InterfaceInfo列表
def _parse_interface_json(output: str) -> tuple[list[InterfaceInfo], bool]:
    """把 ``ip -j addr show`` 的 JSON 输出解析成结构化接口列表。"""
    # 尝试把字符串转为 Python 对象（列表/字典）
    # 确保后续代码操作的 raw_interfaces 一定是一个列表
    try:
        raw_interfaces = json.loads(output)
    except json.JSONDecodeError:
        return [], False
    if not isinstance(raw_interfaces, list):
        return [], False

    interfaces: list[InterfaceInfo] = []
    # 遍历列表所有的对象(网卡)
    for raw in raw_interfaces:
        # 若不是网卡类型，则直接跳过
        if not isinstance(raw, dict):
            continue
        flags = raw.get("flags") or []
        addresses: list[InterfaceAddress] = []
        # 提取标志位 & 开始解析 IP 地址
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
        # 组装完整的网卡对象
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
    # 拼命令并执行（-j 让 iproute2 输出 JSON，解析最稳）
    result = self._backend.execute(source, ["ip", "-j", "addr", "show"])

    # 解析结果字段初始化
    interfaces: list[InterfaceInfo] = []
    parse_failed = False
    # 命令失败时不解析 stdout（内容可能是报错文本）
    if result.exit_code == 0:
        # 解析器返回 (列表, parse_ok)，parse_failed 取其反
        interfaces, parse_ok = self._parse_interface_json(result.stdout)
        parse_failed = not parse_ok

    # 组装最终的结果，并返回
    return InterfaceInspectResult(
        source=source,
        successful=result.exit_code == 0,
        exit_code=result.exit_code,
        parse_failed=parse_failed,
        interfaces=interfaces,
        stderr=result.stderr,
        raw_output=result.stdout if include_raw_output else None,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.interface_inspect",
        domain="network",
        description="Inspect the network interfaces and their addresses on an emulated node.",
    ),
    handler=tools.interface_inspect,
    arguments_model=InterfaceInspectArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（A01 已启动）和 agent-tools（tool-service 已就绪，.venv 已建好）。

### 5.1 确认 emulator 在运行

```bash
docker ps | grep as151
# 应看到类似 as151h-host0-10.151.0.71 的容器（名字以实际为准）
```

### 5.2 跑单元测试

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python -m pytest
```

### 5.3 启动工具服务（终端 1）

```bash
python -m uvicorn seedemu_tool_service.main:app --reload
# 验证：
#   curl http://127.0.0.1:8000/api/v1/tools      → 应看到 network.interface_inspect
#   curl http://127.0.0.1:8000/api/v1/runtime    → 应返回 "available": true（连上了 VM 的 Docker）
```

### 5.4 端到端：让工具真实执行（终端 2）

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python - <<EOF
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools

tools = NetworkTools(DockerRuntimeBackend())
result = tools.interface_inspect("as151h-host0-10.151.0.71")
print(result.model_dump_json(indent=2))
EOF
```

### 5.5 对照原始命令（两边输出应一致）

原命令：
```bash
docker exec as151h-host0-10.151.0.71 ip -j addr show

[{  "ifindex":1,
    "ifname":"lo",
    "flags":["LOOPBACK","UP","LOWER_UP"],
    "mtu":65536,
    "qdisc":"noqueue",
    "operstate":"UNKNOWN",
    "group":"default",
    "txqlen":1000,
    "link_type":"loopback",
    "address":"00:00:00:00:00:00",
    "broadcast":"00:00:00:00:00:00",
    "addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8,"scope":"host","label":"lo","valid_life_time":4294967295,"preferred_life_time":4294967295},{"family":"inet6","local":"::1","prefixlen":128,"scope":"host","valid_life_time":4294967295,"preferred_life_time":4294967295}]},{"ifindex":2,"link_index":25,
    
    "ifname":"net0",
    "flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],
    "mtu":1500,
    "qdisc":"tbf",
    "operstate":"UP",
    "group":"default",
    "txqlen":1000,
    "link_type":"ether",
    "address":"fa:a9:3d:5a:a5:7c",
    "broadcast":"ff:ff:ff:ff:ff:ff",
    "link_netnsid":0,
    "addr_info":[{"family":"inet","local":"10.151.0.71","prefixlen":24,"broadcast":"10.151.0.255","scope":"global","label":"net0","valid_life_time":4294967
```
tools命令：
```
"source": "as151h-host0-10.151.0.71",
"successful": true,
"exit_code": 0,
"parse_failed": false,
  "interfaces": [
    {
      "name": "lo",
      "up": true,
      "operstate": "UNKNOWN",
      "mtu": 65536,
      "mac_address": null,
      "addresses": [
        {
          "family": "inet",
          "local": "127.0.0.1",
          "prefixlen": 8,
          "scope": "host"
        },
        {
          "family": "inet6",
          "local": "::1",
          "prefixlen": 128,
          "scope": "host"
        }
      ]
    },
    {
      "name": "net0",
      "up": true,
      "operstate": "UP",
      "mtu": 1500,
      "mac_address": "fa:a9:3d:5a:a5:7c",
      "addresses": [
        {
          "family": "inet",
          "local": "10.151.0.71",
          "prefixlen": 24,
          "scope": "global"
        }
      ]
    }
  ],
  "stderr": "",
  "raw_output": null

```
> 对照要点：接口数量、`up` 语义（flags 含 UP）、MAC 地址（ether 链路）、
> IPv4/IPv6 地址及 scope；如有差异，按第 1 节条目 8 回填测试 fixture。