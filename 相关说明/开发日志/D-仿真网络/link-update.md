# network.link_update 开发日志

> 说明：本文档是 `link_update` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（D 类 仿真网络·写）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.link_update` |
| 功能 | 把接口置为 up/down——接口粒度模拟链路故障/恢复 |
| 底层 | `ip link set <iface> up/down`（iproute2） |
| 类型 | 命令型（**写操作**，非持久） |
| 分类 | D 仿真网络（写）★emulator 特有 |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"接口级链路故障注入"工具；
- **为什么**：排障实验最常用的操作是"把某条链路搞断，看上层怎么收敛"；官方 `seedemu_worker` 有脚本级 `net_up/net_down`，但那是整网粒度的——Agent 需要**单个接口**粒度的 down/up；
- **决定**：封装 `ip link set <iface> down/up`（iproute2 预装，零新增依赖）；
- **产出**：一句话功能描述——"把接口置为 up/down，接口粒度模拟链路故障（非持久）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `ip link set` 的行为；
- **观察到 3 个事实**：
  1. `ip link set <iface> down` 置管理态 down——内核立即停止收发，邻居表/路由对该接口的路由失效（`linkdown` 状态）；
  2. `ip link set <iface> up` 恢复——**故障可逆**，是排障实验的关键属性；
  3. 接口不存在时退出码非零、错误进 stderr（`Cannot find device`）；
- **为什么重要**：事实 2 决定工具必须同时支持 up/down 两个方向（故障注入 + 恢复）；
- **产出**：行为观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `LinkUpdateArguments` / `LinkUpdateResult`；
- **关键决策**：
  - 入参 `source` + `interface` + `state`（up/down，Literal 枚举）；
  - **`interface` 用 `_IFNAME_PATTERN` 格式校验**（字母/数字开头、≤15 字符）——写操作入参比只读更严格（P4）；
  - 结果保留 `successful`/`exit_code`/`stderr`（P2/P3）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `link_update` 方法；
- **关键决策**：
  - 命令用参数向量 `["ip", "link", "set", interface, state]`，不拼 shell（P1）；
  - `successful = result.exit_code == 0`；stderr 原样保留（接口不存在等错误对 Agent 有排障价值）；
  - 极简：无解析、无额外字段——命令本身就是语义；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.link_update`（插在 `link_properties_update` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 15 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 2 个用例 + 注册断言 11→15；
- **覆盖场景**：down 命令向量 + 结果字段；非法接口名校验；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M2 其他 3 个工具合计 4 条）；`test_api.py` count 18→22；`network-tools-index.md` 补总览/详述/排障速查/通用约定；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：真实容器 `ip link set net0 down` 后 ping/route_lookup 的行为变化（链路故障是否按预期生效），回填到本日志。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 LinkUpdateArguments / LinkUpdateResult（含接口名校验） |
| `tools/network/tools.py` | 新增 `link_update` 方法 |
| `tools/network/registration.py` | 新增 `network.link_update` 注册块 |
| `tests/test_network_tools.py` | 注册断言 11→15（索引顺移）；新增 2 个用例 |
| `tests/test_api.py` | count 18→22；工具列表补 4 个名字 |
| `tool-service/README.md` | network 域补 4 条 + 写操作非持久说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/link-update.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
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
```

### tools.py 新增

```python
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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.link_update",
        domain="network",
        description="Set an interface administratively up or down to simulate a link failure.",
    ),
    handler=tools.link_update,
    arguments_model=LinkUpdateArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（B00/A01 已启动）和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令 + 故障注入效果

```bash
docker ps | grep -E "as[0-9]+"
docker exec as150brd-router0-10.150.0.254 ip link set net0 down
docker exec as150brd-router0-10.150.0.254 ip link show net0      # 应看到 state DOWN / LOWER_UP 消失
net0@if82: <BROADCAST,MULTICAST> mtu 1500 qdisc tbf state DOWN mode DEFAULT group default qlen 1000
    link/ether b2:25:9b:ea:fd:fb brd ff:ff:ff:ff:ff:ff link-netnsid 0

docker exec  as150h-host_0-10.150.0.71 ping -c 2 as150brd-router0-10.150.0.254  # 应丢包（链路已断）
PING as150brd-router0-10.150.0.254 (10.150.0.254) 56(84) bytes of data.
From 59badb90c978 (10.150.0.71) icmp_seq=1 Destination Host Unreachable
From 59badb90c978 (10.150.0.71) icmp_seq=2 Destination Host Unreachable

--- as150brd-router0-10.150.0.254 ping statistics ---
2 packets transmitted, 0 received, +2 errors, 100% packet loss, time 1050ms
pipe 2

docker exec as150brd-router0-10.150.0.254 ip link set net0 up    # 恢复
docker exec  as150h-host_0-10.150.0.71 ping -c 2 as150brd-router0-10.150.0.254  # 应恢复
PING as150brd-router0-10.150.0.254 (10.150.0.254) 56(84) bytes of data.
64 bytes from as150brd-router0-10.150.0.254.output_net_150_net0 (10.150.0.254): icmp_seq=1 ttl=64 time=0.137 ms
64 bytes from as150brd-router0-10.150.0.254.output_net_150_net0 (10.150.0.254): icmp_seq=2 ttl=64 time=0.085 ms

--- as150brd-router0-10.150.0.254 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1006ms
rtt min/avg/max/mdev = 0.085/0.111/0.137/0.026 ms

```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.link_update("as150brd-router0-10.150.0.254", "net0", "down").model_dump_json(indent=2))
EOF
```
```
"source": "as150brd-router0-10.150.0.254",
  "interface": "net0",
  "state": "down",
  "successful": true,
  "exit_code": 0,
  "stderr": ""

docker exec  as150h-host_0-10.150.0.71 ping -c 2 as150brd-router0-10.150.0.254 
PING as150brd-router0-10.150.0.254 (10.150.0.254) 56(84) bytes of data.

--- as150brd-router0-10.150.0.254 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss, time 1056ms

```
```bash
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.link_update("as150brd-router0-10.150.0.254", "net0", "up").model_dump_json(indent=2))
EOF
```
```
"source": "as150brd-router0-10.150.0.254",
  "interface": "net0",
  "state": "up",
  "successful": true,
  "exit_code": 0,
  "stderr": "

PING as150brd-router0-10.150.0.254 (10.150.0.254) 56(84) bytes of data.
64 bytes from as150brd-router0-10.150.0.254.output_net_150_net0 (10.150.0.254): icmp_seq=1 ttl=64 time=0.149 ms
64 bytes from as150brd-router0-10.150.0.254.output_net_150_net0 (10.150.0.254): icmp_seq=2 ttl=64 time=0.101 ms

--- as150brd-router0-10.150.0.254 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1015ms
rtt min/avg/max/mdev = 0.101/0.125/0.149/0.024 ms

```

### 5.3 回填条件

- 确认 down 后接口状态、ping 丢包、路由行为符合预期；up 后恢复；
- 确认工具输出（successful/exit_code/stderr）与原始命令一致。
