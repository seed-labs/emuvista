# network.link_properties_inspect 开发日志

> 说明：本文档是 `link_properties_inspect` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（D 类 仿真网络 ★emulator 特有）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.link_properties_inspect` |
| 功能 | 查看节点各接口上**实际生效**的链路属性——tbf 限速（rate/burst）+ netem 延迟/丢包（delay/loss），按接口分组 |
| 底层 | `tc qdisc show`（iproute2，文本 + 关键字扫描） |
| 类型 | 命令型 + 文本解析 |
| 分类 | D 仿真网络（只读）★emulator 特有 |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"读实际生效链路属性"工具；
- **为什么**：emulator 的链路属性（延迟/带宽/丢包）编译后是用 `tc qdisc`（tbf 限速 + netem 延迟/丢包）打在接口队列上的——`node_networks` 读的是**配置**（`/ifinfo.txt`），本工具读的是**实际生效值**（`tc qdisc show`），两者对照才能回答"配了没生效/实际值是多少"；
- **决定**：封装 `tc qdisc show`——iproute2 自带 `tc`，零新增依赖；
- **产出**：一句话功能描述——"查看节点接口上实际生效的链路属性（tbf/netem）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `tc qdisc show` 输出结构（黄金样本）；
- **预期 4 个事实**：
  1. 每行一个 qdisc，行结构：`qdisc <kind> <handle>: dev <iface> [root | parent <x>] [参数...]`；
  2. seed-emulator 的典型形态：`tbf` 挂在 root（限速：`rate`/`burst`/`lat`），`netem` 挂在 tbf 的 child（延迟/丢包：`limit`/`delay`/`loss`）；
  3. 参数是**键值对 token**（`rate 100Mbit`、`delay 10.0ms`、`loss 0.1%`），但顺序不固定、随 qdisc 种类变化；
  4. `lo` 等接口只有 `noqueue`，没有链路属性——**空属性是合法状态**；
- **风险点（已落地）**：**真实输出必须在 VM 实测回填**——不同 iproute2 版本参数名/列序可能不同，所以解析器用**关键字扫描**（认 rate/delay/loss/limit/burst，其余跳过）而非位置解析；
- **产出**：黄金样本 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `LinkPropertiesArguments` / `QdiscInfo` / `InterfaceLinkState` / `LinkPropertiesResult`；
- **关键决策**：
  - 入参 `source` + `include_raw_output`（可选，诊断开关）；
  - `QdiscInfo` 只建模 emulator 链路属性相关参数：`kind`/`handle`/`parent`/`rate`/`delay`/`loss`/`limit`/`burst`，全部 `str | None`（带单位原始字符串，P6 诚实表达）；
  - **tbf 的 `lat`（时延上界）不建模**——它不是 netem 的延迟，建模会让 Agent 混淆；保留在 raw_output；
  - 结果按接口分组：`InterfaceLinkState{interface, qdiscs[]}`——Agent 的自然提问"net0 的链路属性是什么"可直接回答；
  - 结果保留 `successful`/`exit_code`/`stderr`/`raw_output`（P2/P3）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `_parse_qdisc_line`（静态方法）+ `link_properties_inspect` 方法；
- **关键决策**：
  - 命令用参数向量 `["tc", "qdisc", "show"]`，不拼 shell（P1）；
  - 关键字扫描（同 route_inspect 思路）：认 `dev`/`root`/`parent`/`rate`/`delay`/`loss`/`limit`/`burst`，其余 token 跳过——字段顺序不固定也能解析；
  - `handle` 去掉尾冒号归一化（`1:` → `1`）；无法归属到接口的行（无 `dev`）丢弃；
  - 按接口分组（dict 保持首次出现顺序）；`noqueue`/`fq_codel` 等非链路属性 qdisc 也照实返回（kind 字段可区分），Agent 可自行过滤；
  - 文本逐行解析，无法映射的行丢弃（同 route_inspect 策略）；空输出（无 qdisc）是合法状态（interfaces=[]）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.link_properties_inspect`（插在 `interface_inspect` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 11 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 5 个用例 + 注册断言 8→11；
- **覆盖场景**：黄金样本解析（lo noqueue + net0 tbf root + netem child，全字段断言）、未知参数跳过（fq_codel 的 flows/quantum/target 等被忽略、limit 保留）、命令失败、空输出、`include_raw_output` 透传；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ 用 `py_compile` 做语法检查；真实 pytest + docker 端到端由虚拟机验证（见第 5 节）；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M1 其他两个工具合计 3 条）；`test_api.py` count 15→18（3 个工具合计）；`network-tools-index.md` 补总览表/详述/排障速查；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：在真实容器 `tc qdisc show`，确认输出结构（qdisc 前缀、dev 标记、参数名）与黄金样本一致；如有差异更新解析器与 fixture。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 LinkPropertiesArguments / QdiscInfo / InterfaceLinkState / LinkPropertiesResult |
| `tools/network/tools.py` | 新增 `_parse_qdisc_line`（静态方法）+ `link_properties_inspect` 方法 |
| `tools/network/registration.py` | 新增 `network.link_properties_inspect` 注册块 |
| `tests/test_network_tools.py` | 注册断言 8→11（索引顺移）；新增 5 个用例 + `GOLDEN_QDISC` |
| `tests/test_api.py` | count 15→18；工具列表补 3 个名字 |
| `tool-service/README.md` | network 域补 3 条 + tc 说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查 |
| `learning/link-properties-inspect.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
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
```

### tools.py 新增

```python
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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.link_properties_inspect",
        domain="network",
        description="Inspect the effective link properties (tbf/netem qdiscs) on a node's interfaces.",
    ),
    handler=tools.link_properties_inspect,
    arguments_model=LinkPropertiesArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（B00 已启动）和 agent-tools（tool-service 已就绪，.venv 已建好）。

### 5.1 对照原始命令

```bash
docker ps | grep -E "as[0-9]+"      # 看实际有哪些容器在跑
docker exec as151brd-router0-10.151.0.254 tc qdisc show

qdisc noqueue 0: dev lo root refcnt 2 
qdisc tbf 1: dev net0 root refcnt 129 rate 1Tbit burst 992000b limit 1000b 
qdisc netem 10: dev net0 parent 1: limit 1000
qdisc tbf 1: dev ix100 root refcnt 129 rate 1Tbit burst 992000b limit 1000b 
qdisc netem 10: dev ix100 parent 1: limit 1000
qdisc noqueue 0: dev dummy0 root refcnt 2 

```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python3.11 - <<EOF
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools

tools = NetworkTools(DockerRuntimeBackend())
result = tools.link_properties_inspect("as151brd-router0-10.151.0.254")
print(result.model_dump_json(indent=2))
EOF
```
```
"source": "as151brd-router0-10.151.0.254",
  "successful": true,
  "exit_code": 0,
  "interfaces": [
    {
      "interface": "lo",
      "qdiscs": [
        {
          "kind": "noqueue",
          "handle": "0",
          "parent": "root",
          "rate": null,
          "delay": null,
          "loss": null,
          "limit": null,
          "burst": null
        }
      ]
    },
    {
      "interface": "net0",
      "qdiscs": [
        {
          "kind": "tbf",
          "handle": "1",
          "parent": "root",
          "rate": "1Tbit",
          "delay": null,
          "loss": null,
          "limit": "1000b",
          "burst": "992000b"
        },
        {
          "kind": "netem",
          "handle": "10",
          "parent": "1:",
          "rate": null,
          "delay": null,
          "loss": null,
          "limit": "1000",
          "burst": null
        }
      ]
    },
    {
      "interface": "ix100",
      "qdiscs": [
        {
          "kind": "tbf",
          "handle": "1",
          "parent": "root",
          "rate": "1Tbit",
          "delay": null,
          "loss": null,
          "limit": "1000b",
          "burst": "992000b"
        },
        {
          "kind": "netem",
          "handle": "10",
          "parent": "1:",
          "rate": null,
          "delay": null,
          "loss": null,
          "limit": "1000",
          "burst": null
        }
      ]
    },
    {
      "interface": "dummy0",
      "qdiscs": [
        {
          "kind": "noqueue",
          "handle": "0",
          "parent": "root",
          "rate": null,
          "delay": null,
          "loss": null,
          "limit": null,
          "burst": null
        }
      ]
    }
  ],
  "stderr": "",
  "raw_output": null

```

