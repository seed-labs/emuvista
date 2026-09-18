# network.link_properties_update 开发日志

> 说明：本文档是 `link_properties_update` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（D 类 仿真网络·写）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.link_properties_update` |
| 功能 | 运行时改接口的链路属性——延迟（netem delay）、带宽（tbf rate）、丢包（netem loss） |
| 底层 | `tc qdisc show`（读当前）+ `tc qdisc replace/add`（改，非持久） |
| 类型 | 命令型（**写操作**，读-合并-替换，非持久） |
| 分类 | D 仿真网络（写）★emulator 特有 |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"运行时改链路属性"工具；
- **为什么**：Performance 管理功能面全空；Agent 做"把延迟从 10ms 改到 50ms 看 TCP 拥塞控制怎么变""把丢包改到 5% 看路由协议收敛"这类实验时，只能重建环境——而 emulator 的链路属性是 `tc qdisc` 实现在队列层的，**可以运行时替换**，不用重建；
- **决定**：封装 `tc qdisc replace`（官方 `seedemu_worker` 语义的接口粒度版）；
- **产出**：一句话功能描述——"运行时改延迟/带宽/丢包（读-合并-替换，非持久）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `tc qdisc` 的替换语义（关键设计点）；
- **观察到 4 个事实**：
  1. seed-emulator 的典型结构：`tbf` 挂 root（handle 1:，限速 rate/burst/latency）+ `netem` 挂 tbf 的 child（parent 1:1，handle 8002:，limit/delay/loss）——和 `link_properties_inspect` 的黄金样本一致；
  2. **`tc qdisc replace` 需要完整参数**：替换 tbf 要重给 rate+burst+latency，替换 netem 要重给 limit+delay+loss——只给一个参数会丢掉其他；
  3. 接口还没有对应 qdisc 时 `replace` 报错（`Cannot find specified qdisc`），要用 `add`；
  4. netem 的 parent 1:1 依赖 tbf 存在——接口没有 tbf 时不能直接挂 netem；
- **为什么重要**：事实 2/3/4 直接决定了"**读-合并-替换**"设计——工具内部先 `tc qdisc show` 读当前生效值，未指定的属性沿用当前值，再 replace（没有就 add）；
- **风险点（已落地）**：**handle 号（1:/8002:）与默认参数（burst/latency/limit）依赖 seed-emulator 的实际配置，必须在 VM 实测回填**；若真实 handle 不同，replace 会报错并保留在 stderr，据此更新；
- **产出**：语义观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `LinkPropertiesUpdateArguments` / `UpdateCommand` / `LinkPropertiesUpdateResult`；
- **关键决策**：
  - 入参 `source` + `interface`（格式校验）+ `latency`/`bandwidth`/`drop`（**至少给一个**，model_validator 兜底）；
  - **值格式校验**：`latency` 必须形如 `10ms`/`0.5s`；`drop` 形如 `5%`/`0.1%`，纯数字自动补 `%`（"5"→"5%"）；`bandwidth` 宽松校验（tc 速率单位太多，语法错误留给 tc 报错）——写操作入参比只读严格（P4），但不替 tc 做全部语法检查；
  - `UpdateCommand{command, exit_code, stderr}` 逐条记录已执行的命令——读-合并-替换可能执行 1~2 条，逐条留证（P3）；
  - `successful` = 所有已执行命令退出码均为 0；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `link_properties_update` 方法（复用 `link_properties_inspect` 的解析逻辑做读）；
- **关键决策**：
  - **读-合并-替换三步**：① `link_properties_inspect(source)` 读当前 qdisc → 找该接口的 tbf/netem；② 合并——bandwidth 给 rate、未指定的 burst 沿用当前（查不到用默认 2000b）；latency/drop 给 netem 的 delay/loss、未指定的沿用当前（查不到归零 0ms/0%）；③ 有则 replace、无则 add；
  - **默认值文档化**：tbf 的 burst=2000b、latency（时延上界）=400.0ms、netem 的 limit=1000、补建 tbf 时 rate=100Mbit——与 seed-emulator 典型配置一致（A-1 需实测确认）；
  - netem 需要 parent 1:1：接口没有 tbf 时先补建 tbf（默认参数），再挂 netem；
  - 命令一律参数向量（P1）；逐条执行、逐条记录 exit_code/stderr；
  - 注意：`link_properties_inspect` 不建模 tbf 的 lat（时延上界），replace 时用文档化默认 400.0ms——如 VM 实测发现不同，更新默认值；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.link_properties_update`（插在 `link_properties_inspect` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 15 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 `QueueRuntimeBackend`（按调用顺序吐响应的后端，写操作"先读后写"场景专用）+ 6 个用例 + 注册断言 11→15；
- **覆盖场景**：只改 bandwidth（1 条 replace，burst 沿用当前 2000b）、只改 latency（netem replace，loss 沿用当前 0.1%）、drop 纯数字归一化（"5"→"5%"）、接口无 qdisc 时补建（2 条 add）、命令失败传播、入参校验（全缺/坏带宽/坏接口名）；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟（真实 tools.py + stub 模型，4 场景全过，含读-合并-替换的合并结果断言）；真实 pytest + docker 端到端由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M2 其他 3 个工具合计 4 条）；`test_api.py` count 18→22；`network-tools-index.md` 补总览/详述/排障速查/通用约定；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：真实 `tc qdisc show` 的 handle 号与参数（1:/8002:、burst/latency/limit）与默认值是否一致；`tc qdisc replace` 在该容器版本的行为；如有差异更新默认值与命令构造。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 LinkPropertiesUpdateArguments / UpdateCommand / LinkPropertiesUpdateResult（含 3 个值校验 + model_validator） |
| `tools/network/tools.py` | 新增 `link_properties_update` 方法（读-合并-替换） |
| `tools/network/registration.py` | 新增 `network.link_properties_update` 注册块 |
| `tests/test_network_tools.py` | 新增 QueueRuntimeBackend；注册断言 11→15；新增 6 个用例 |
| `tests/test_api.py` | count 18→22；工具列表补 4 个名字 |
| `tool-service/README.md` | network 域补 4 条 + 写操作非持久说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/link-properties-update.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 

```python
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

    @field_validator("latency")
    @classmethod
    def validate_latency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _LATENCY_PATTERN.fullmatch(value):
            raise ValueError(f"latency must look like '10ms' or '0.5s', got {value!r}")
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
```

### tools.py

```python
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
    if bandwidth is not None:
        rate = bandwidth
        burst = tbf.burst if tbf is not None and tbf.burst else "2000b"
        latency_bound = "400.0ms"  # tbf 的时延上界默认值（QdiscInfo 不建模 lat）
        qdisc = "replace" if tbf is not None else "add"
        commands.append(
            ["tc", "qdisc", qdisc, "dev", interface, "root", "handle", "1:",
             "tbf", "rate", rate, "burst", burst, "latency", latency_bound]
        )
    if latency is not None or drop is not None:
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

    return LinkPropertiesUpdateResult(
        source=source,
        interface=interface,
        latency=latency,
        bandwidth=bandwidth,
        drop=drop,
        successful=all_ok,
        executed=executed,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.link_properties_update",
        domain="network",
        description="Change the effective link properties (latency/bandwidth/drop) on an interface at runtime.",
    ),
    handler=tools.link_properties_update,
    arguments_model=LinkPropertiesUpdateArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（B00 已启动）和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令（先看真实 handle 与参数）

```bash
docker ps | grep -E "as[0-9]+"
docker exec as151brd-router0-10.151.0.254 tc qdisc show dev net0
# 记录真实的 handle（预期 1: 与 8002:）、burst、latency、limit
qdisc tbf 1: root refcnt 129 rate 1Tbit burst 992000b limit 1000b 
qdisc netem 10: parent 1: limit 1000
# 手动验证 replace 语义：
docker exec as151brd-router0-10.151.0.254 tc qdisc replace dev net0 parent 1:1 handle 8002: netem limit 1000 delay 50ms loss 0.1%
docker exec as151brd-router0-10.151.0.254 tc qdisc show dev net0   # 应看到 delay 50ms
qdisc netem 8002: parent 1:1 limit 1000 delay 50ms loss 0.1%


docker exec as151brd-router0-10.151.0.254 tc qdisc replace dev net0 parent 1:1 handle 8002: netem limit 1000 delay 10ms loss 0.1%  # 还原
```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.link_properties_update("as151brd-router0-10.151.0.254", "net0", latency="50ms").model_dump_json(indent=2))
EOF

  "source": "as151brd-router0-10.151.0.254",
  "interface": "net0",
  "latency": "50ms",
  "bandwidth": null,
  "drop": null,
  "successful": true,
  "executed": [
    {
      "command": [
        "tc",
        "qdisc",
        "replace",
        "dev",
        "net0",
        "parent",
        "1:1",
        "handle",
        "8002:",
        "netem",
        "limit",
        "1000",
        "delay",
        "50ms",
        "loss",
        "0.1%"
      ],
      "exit_code": 0,
      "stderr": ""
    }
  ],
  "effective": {
    "rate": null,
    "burst": null,
    "latency_bound": null,
    "delay": "50ms",
    "loss": "0.1%",
    "limit": "1000"
  }

```