# network.route_update 开发日志

> 说明：本文档是 `route_update` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（B 类 路由转发·写）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.route_update` |
| 功能 | 运行时增删内核路由表条目——普通路由（via/dev）与黑洞路由（blackhole） |
| 底层 | `ip route add/del`（iproute2） |
| 类型 | 命令型（**写操作**，非持久） |
| 分类 | B 路由转发（写） |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"路由表写操作"工具；
- **为什么**：分类矩阵里 B 类只有只读（route_inspect/route_lookup），**写操作为 0**——Configuration 管理功能面全空；Agent 做"加一条静态路由验证转发""加黑洞路由做丢流量实验"时没有工具可用；
- **决定**：封装 `ip route add/del`，语义对齐官方 `seedemu_worker` 的运行时变更（**非持久**，重启即还原）；
- **安全考量（已落地）**：文档注明**在 hnode（host）上最安全**——host 节点没有 bird，路由不会被抢回；rnode 上 bird 可能把静态路由抢回（分类框架 M2 路线图原文）；
- **产出**：一句话功能描述——"运行时增删内核路由（add/del，非持久）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `ip route add/del` 的语法与失败模式；
- **观察到 5 个事实**：
  1. `ip route add <前缀> via <网关> dev <接口>`——普通路由**必须有 via 或 dev**，否则报错；
  2. 黑洞路由语法是 `ip route add blackhole <前缀>`，**不能带 via/dev**；
  3. `ip route del <前缀>` 按前缀匹配删除；重复路由可用 via/dev 精确匹配；
  4. 目标前缀可以是 `default`（`ip route add default via <网关>`）；
  5. 失败时退出码非零、错误进 stderr（如 `RTNETLINK answers: File exists`）——**退出码就是成功标志**；
- **为什么重要**：事实 1/2 直接决定入参校验（跨字段约束），事实 5 决定 `successful = exit_code == 0` 的语义映射；
- **产出**：语法观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `RouteUpdateArguments` / `RouteUpdateResult`；
- **关键决策**：
  - 入参 `operation`（add/del）+ `destination` + 可选 `gateway`/`interface` + `route_type`（unicast/blackhole）；
  - `destination` 校验：支持 `default` 与 CIDR（`ip_network strict=False` 归一化，掩掉主机位）；
  - `gateway` 用 `ip_address` 强校验（写操作入参比只读更严格，P4）；
  - **跨字段约束用 `model_validator`**：黑洞路由不能带 via/dev；普通 add 必须有 via 或 dev——把 iproute2 的隐式规则提前到入参层，Agent 拿到的是明确的 ValidationError 而不是容器里的报错；
  - 结果保留 `successful`/`exit_code`/`stderr`（P2/P3，RTNETLINK 原始错误对排障有价值）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `route_update` 方法；
- **关键决策**：
  - 命令用参数向量：`["ip", "route", operation]` + 分支拼接（blackhole 关键字、via/dev），不拼 shell（P1）；
  - `del` 忽略 `route_type`（`ip route del <前缀>` 按前缀匹配即可删除黑洞路由）；
  - `successful = result.exit_code == 0`；stderr 原样保留；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.route_update`（插在 `route_lookup` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 15 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 7 个用例 + 注册断言 11→15；
- **覆盖场景**：普通 add 命令向量、blackhole add、del、`default` 路由、命令失败（RTNETLINK stderr 透传）、跨字段校验（add 无 via/dev 报错、blackhole 带 gateway 报错）、destination 非法；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟（真实 tools.py + stub 模型，4 场景全过）；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M2 其他 3 个工具合计 4 条）；`test_api.py` count 18→22（4 个工具合计）；`network-tools-index.md` 补总览/详述/排障速查/通用约定（写操作非持久语义）；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：在真实容器 `ip route add/del` 对照；确认 hnode 上 bird 不抢回、rnode 上会抢回（回填到本日志）；重启容器验证非持久语义。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 RouteUpdateArguments / RouteUpdateResult（含 field_validator + model_validator） |
| `tools/network/tools.py` | 新增 `route_update` 方法 |
| `tools/network/registration.py` | 新增 `network.route_update` 注册块 |
| `tests/test_network_tools.py` | 注册断言 11→15（索引顺移）；新增 7 个用例 |
| `tests/test_api.py` | count 18→22；工具列表补 4 个名字 |
| `tool-service/README.md` | network 域补 4 条 + 写操作非持久说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/route-update.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增（入参校验是重点）

```python
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
```

### tools.py 新增

```python
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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.route_update",
        domain="network",
        description="Add or delete a kernel route at runtime (non-persistent).",
    ),
    handler=tools.route_update,
    arguments_model=RouteUpdateArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（A01/B00 已启动）和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令（推荐在 hnode 上验证）

```bash
docker ps | grep -E "as[0-9]+"
docker exec as163h-host_0-10.163.0.71 ip route add 10.99.0.0/24 via 10.163.0.254 dev net0
docker exec as163h-host_0-10.163.0.71 ip route show   # 应看到新路由

结果：
default via 10.163.0.254 dev net0 
10.99.0.0/24 via 10.163.0.254 dev net0 
10.163.0.0/24 dev net0 proto kernel scope link src 10.163.0.71 

docker exec as163h-host_0-10.163.0.71 ip route del 10.99.0.0/24

成功删除：
default via 10.163.0.254 dev net0 
10.163.0.0/24 dev net0 proto kernel scope link src 10.163.0.71 


docker exec as163h-host_0-10.163.0.71 ip route add blackhole 10.99.0.0/24
docker exec as163h-host_0-10.163.0.71 ip route show   # 应看到 blackhole 10.99.0.0/24

结果：
default via 10.163.0.254 dev net0 
blackhole 10.99.0.0/24 
10.163.0.0/24 dev net0 proto kernel scope link src 10.163.0.71 

```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.route_update("as163h-host_0-10.163.0.71", "add", "10.99.0.0/24", gateway="10.163.0.254", interface="net0").model_dump_json(indent=2))
result = tools.route_inspect("as163h-host_0-10.163.0.71")
print(result.model_dump_json(indent=2))
EOF

成功添加：

"source": "as163h-host_0-10.163.0.71",
  "successful": true,
  "exit_code": 0,
  "routes": [
    {
      "destination": "default",
      "gateway": "10.163.0.254",
      "interface": "net0",
      "source": null
    },
    {
      "destination": "10.99.0.0/24",
      "gateway": "10.163.0.254",
      "interface": "net0",
      "source": null
    },
    {
      "destination": "10.163.0.0/24",
      "gateway": null,
      "interface": "net0",
      "source": "10.163.0.71"
    }
  ],
  "stderr": ""

python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.route_update("as163h-host_0-10.163.0.71", "del", "10.99.0.0/24", gateway="10.163.0.254", interface="net0").model_dump_json(indent=2))
result = tools.route_inspect("as163h-host_0-10.163.0.71")
print(result.model_dump_json(indent=2))
EOF

成功删除：

  "source": "as163h-host_0-10.163.0.71",
  "successful": true,
  "exit_code": 0,
  "routes": [
    {
      "destination": "default",
      "gateway": "10.163.0.254",
      "interface": "net0",
      "source": null
    },
    {
      "destination": "10.163.0.0/24",
      "gateway": null,
      "interface": "net0",
      "source": "10.163.0.71"
    }
  ],
  "stderr": ""

```

