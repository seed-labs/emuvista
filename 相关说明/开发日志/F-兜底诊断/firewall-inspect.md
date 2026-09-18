# network.firewall_inspect 开发日志

> 说明：本文档是 `firewall_inspect` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（F 类 兜底诊断）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.firewall_inspect` |
| 功能 | 查看节点防火墙——链、默认策略、规则清单 |
| 底层 | `iptables -S -t <table>`（默认 filter 表） |
| 类型 | 命令型 + 文本解析 |
| 分类 | F 兜底诊断（只读）·**条件可用** |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"防火墙检查"工具；
- **为什么**：**iptables 会在内核里悄悄丢包**——A（接口/邻居）、B（路由）、C（连通性）类工具看到的都是"正常"，但包就是不通；F 类需要把这个隐藏层摊开；
- **决定**：封装 `iptables -S`（输出规则为可执行命令形态，比 `-L` 更精确、更易解析）；
- **⚠️ 条件可用（已落地）**：iptables **不在 seedemu-base 基础镜像里**（分类框架调研结论），仅特定实验镜像有——工具做**优雅降级**：命令不存在时 successful=False + stderr（"iptables: not found"），Agent 据此知道"该节点没有防火墙工具链"；
- **产出**：一句话功能描述——"查看防火墙链/策略/规则（条件可用）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `iptables -S -t <table>` 的输出结构；
- **观察到 3 个事实**：
  1. 行格式固定：`-P <链> <策略>`（默认策略）与 `-A <链> <规则体>`（规则）；
  2. 链按出现顺序排列，规则引用链名（`-A INPUT -i lo -j ACCEPT`）；
  3. 规则体是**原始 iptables 参数**——不翻译，保留给 Agent 自行解读（F 类哲学）；
- **为什么重要**：事实 1 决定解析器（正则匹配 -P/-A/-I/-D/-R）；事实 2 决定按链分组；事实 3 决定 rules 存原始串；
- **风险点（已落地）**：不同 iptables 版本/镜像是 `iptables-save` 还是 `iptables -S` 输出可能有差异——VM 实测回填；
- **产出**：输出结构 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `FirewallInspectArguments` / `FirewallChain` / `FirewallInspectResult`；
- **关键决策**：
  - 入参 `source` + `table`（filter/nat/mangle/raw/security，默认 filter）+ `include_raw_output`（可选）；
  - `FirewallChain{name, policy, rules[]}`——按链分组（策略 + 规则清单），Agent 可直接回答"INPUT 链的默认策略和规则是什么"；
  - `rules` 存原始规则串（`-A <规则体>`，F 类不翻译，P5 诚实表达）；
  - 结果保留 `successful`/`exit_code`/`stderr`（P2/P3，"not found" 本身是诊断信息）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `_parse_iptables_rules`（静态方法）+ `firewall_inspect` 方法；
- **关键决策**：
  - 命令用参数向量 `["iptables", "-S", "-t", table]`（P1）；
  - 解析：正则 `^(-P|-A|-I|-D|-R) (\S+)(?: (.+))?$`；`-P` 设策略、其余追加规则；链按首次出现顺序；无法识别的行跳过（P6 容错）；
  - 解析 gate 在 `exit_code == 0` 上：命令缺失（127）时不解析 stdout；
  - `include_raw_output` 诊断开关（对齐其他工具）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.firewall_inspect`（插在 `cidr_inspect` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 20 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 3 个用例 + 注册断言 15→20；
- **覆盖场景**：黄金样本解析（3 链：策略 + 规则分组）、命令缺失（exit 127 → successful=False + stderr）、table 参数透传；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M3 其他 4 个工具合计 5 条）；`test_api.py` count 22→27；`network-tools-index.md` 补总览/详述/排障速查/通用约定（条件可用说明）；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：确认哪些实验镜像带 iptables；真实 `iptables -S` 输出与解析器对照。

### 条目 9：VM 实测——环境无 iptables 的确认过程与保留结论（回填）

- **测试过程**（VM 内）：
  1. 批量探测所有运行容器（判定标准与工具一致：直接执行 `iptables -S -t filter` 看退出码）：
     ```bash
     docker ps --format '{{.Names}}' | while read c; do
       docker exec "$c" iptables -S -t filter >/dev/null 2>&1 && echo "OK $c" || echo "FAIL $c"
     done
     ```
     → **全部 FAIL**（stderr 为 `command not found`）；
  2. 源码确认：`ls <seed-emulator>/seedemu/layers/` **无 `Firewall.py`**（只有 Base / Routing / Mpls / Ospf / Ebgp / Ibgp / Evpn / Scion* 等）；`ls <seed-emulator>/examples/` 无防火墙示例（basic / blockchain / internet / sample / scion / wireless）→ **当前 seed-emulator 版本没有防火墙能力**，构建的镜像均不带 iptables；
- **结论：保留本工具**，定位为"条件可用 + 排除法诊断"：
  - 无防火墙节点上返回 not-found 本身就是有用结论——Agent 可据此**排除**"丢包是 iptables 干的"，转向 B/C/D 类排查（F 类兜底的排除法价值）；
  - 平台通用：自定义镜像 / 其他实验环境（如 SeedLabs 的 handsonsecurity 镜像）带 iptables 时工具即生效；已实现 + 测试 + 文档齐全，保留成本≈0；
  - 启用方式：运行时 `docker exec <容器> apt-get install -y --no-install-recommends iptables`（写容器层，`compose up` 重建丢失）；或构建时在生成的 Dockerfile 加 `RUN apt-get install -y iptables`；
- **后续验证**：装好 iptables 后按第 5 节完成端到端（真实 `iptables -S` 输出与解析器对照）。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 FirewallInspectArguments / FirewallChain / FirewallInspectResult |
| `tools/network/tools.py` | 新增 `_parse_iptables_rules`（静态方法）+ `firewall_inspect` 方法 |
| `tools/network/registration.py` | 新增 `network.firewall_inspect` 注册块 |
| `tests/test_network_tools.py` | 注册断言 15→20（索引顺移）；新增 3 个用例 |
| `tests/test_api.py` | count 22→27；工具列表补 5 个名字 |
| `tool-service/README.md` | network 域补 5 条 + 条件可用说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/firewall-inspect.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### tools.py 新增（解析器 + 方法）

```python
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
def firewall_inspect(
    self,
    source: str,
    table: str = "filter",
    include_raw_output: bool = False,
) -> FirewallInspectResult:
    """查看节点防火墙规则（iptables -S，条件可用：基础镜像无 iptables）。"""
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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.firewall_inspect",
        domain="network",
        description="Inspect iptables firewall rules (conditional: iptables is not in the base image).",
    ),
    handler=tools.firewall_inspect,
    arguments_model=FirewallInspectArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator 和 agent-tools（tool-service 已就绪）。

### 5.1 确认 iptables 可用性 + 对照原始命令

```bash
docker ps | grep -E "as[0-9]+"
# 先确认哪些容器带 iptables：
docker exec as161brd-router0-10.161.0.254 which iptables
# 若存在：
docker exec <容器名> iptables -S -t filter
# 若没有防火墙，可临时装：
docker exec as150brd-router0-10.150.0.254 apt-get update
docker exec as150brd-router0-10.150.0.254 apt-get install -y --no-install-recommends iptables
docker exec as150brd-router0-10.150.0.254 iptables -S -t filter   # 验证
```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.firewall_inspect("<带iptables的容器>").model_dump_json(indent=2))
EOF
```

