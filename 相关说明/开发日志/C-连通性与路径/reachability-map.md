# network.reachability_map 开发日志

> 说明：本文档是 `reachability_map` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（C 类 连通性与路径·批量）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.reachability_map` |
| 功能 | 批量 ICMP 连通矩阵——多源 × 多目标逐对 ping，含每对 RTT |
| 底层 | `ping -c N -W T <target>` × (N×M)（批量只读） |
| 类型 | 命令型（**批量**只读） |
| 分类 | C 连通性与路径（批量） |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"连通矩阵"批量工具；
- **为什么**：完整性判据要求**批量工具 ≥1**；`ping` 只回答单对连通性，Agent 做"断网后检查全网收敛情况""对比多节点两两连通"时，逐对调 ping 会爆炸——需要一次调用返回矩阵；
- **决定**：封装"多源 × 多目标逐对 ping"，复用 `network.ping` 的命令语义（`ping -c -W`）；
- **产出**：一句话功能描述——"多源 × 多目标连通矩阵（批量）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析批量探测的约束；
- **观察到 3 个事实**：
  1. `ping` 的 `time=` 行可直接提取 RTT（GNU ping 形如 `time=1.23 ms`、`time<1 ms`；busybox 同为 `time=` 格式）——矩阵可以带 RTT，不只是布尔连通；
  2. 每次 `backend.execute` 是一次 docker exec，N×M 对是**串行**的——矩阵开销随规模线性增长；
  3. 单次 ping 的 `-c 1` 就能给出可靠的连通性结论（退出码），批量场景不需要多探测；
- **为什么重要**：事实 1 决定结果带 `round_trip_ms`；事实 2/3 决定入参上限（sources/targets ≤ 20）与 `count` 默认 1；
- **产出**：行为观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `ReachabilityMapArguments` / `ReachabilityEntry` / `ReachabilityMapResult`；
- **关键决策**：
  - 入参 `sources`/`targets`（list，min 1 / max 20，pydantic Field 直接限制）+ `count`（默认 1，1-5）+ `timeout_seconds`（默认 2，1-10）；
  - `ReachabilityEntry{source, target, reachable, exit_code, round_trip_ms}`——逐对留证（P3），exit_code 保留探测证据；
  - 结果带 `reachable_count` / `total_pairs` 汇总——Agent 不用自己数；
  - **`successful` = 探测全部执行完成（不是全部可达）**——不可达是合法结果，不是工具失败；语义写进字段 description；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `_parse_ping_rtt`（模块级）+ `reachability_map` 方法；
- **关键决策**：
  - 命令用参数向量 `["ping", "-c", str(count), "-W", str(timeout_seconds), target]`（P1，复用 ping 语义）；
  - `_parse_ping_rtt`：正则 `time[=<]` 提取最后一个 RTT 值（`<` 的情况归一为数值）；解析失败返回 None（P6 容错）；
  - 行主序遍历（外层 source、内层 target），entries 顺序确定，Agent 可按索引展开矩阵；
  - 逐对 `reachable = exit_code == 0`；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.reachability_map`（插在 `ping` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 15 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 3 个用例 + 注册断言 11→15；
- **覆盖场景**：2×2 矩阵（可达/不可达混合 + `time=`/`time<` RTT 解析 + 命令向量）、count/timeout 透传、列表大小校验（空列表、21 个 source）；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟（真实 tools.py + stub 模型 + QueueBackend 模拟 4 次探测响应）；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M2 其他 3 个工具合计 4 条）；`test_api.py` count 18→22；`network-tools-index.md` 补总览/详述/排障速查/通用约定；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：真实容器 ping 输出格式与 `_parse_ping_rtt` 的预期（time= / time<）一致；矩阵耗时与规模的关系（20×20 的实测耗时回填，供 Agent 参考）。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 ReachabilityMapArguments / ReachabilityEntry / ReachabilityMapResult |
| `tools/network/tools.py` | 新增 `_parse_ping_rtt`（模块级）+ `reachability_map` 方法 |
| `tools/network/registration.py` | 新增 `network.reachability_map` 注册块 |
| `tests/test_network_tools.py` | 注册断言 11→15（索引顺移）；新增 3 个用例 |
| `tests/test_api.py` | count 18→22；工具列表补 4 个名字 |
| `tool-service/README.md` | network 域补 4 条 + 批量说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/reachability-map.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### tools.py 新增（RTT 解析 + 矩阵方法）

```python
def _parse_ping_rtt(stdout: str) -> float | None:
    """从 ping 输出提取最后一个 time= / time< 的 RTT 值（毫秒）。

    GNU ping 形如 ``time=1.23 ms`` 或 ``time<1 ms``；解析失败返回 None。
    """
    matches = re.findall(r"time[=<]\s*(\d+(?:\.\d+)?)", stdout)
    if not matches:
        return None
    return float(matches[-1])


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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.reachability_map",
        domain="network",
        description="Probe reachability from multiple sources to multiple targets (connectivity matrix).",
    ),
    handler=tools.reachability_map,
    arguments_model=ReachabilityMapArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（B00 已启动，多 AS 多主机）和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令

```bash
docker ps | grep -E "as[0-9]+"
docker exec as150brd-router0-10.150.0.254 ping -c 1 -W 2 10.150.0.72   # 可达
docker exec as151brd-router0-10.151.0.254 ping -c 1 -W 2 10.199.0.71   # 不可达（无此网段）
```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
result = tools.reachability_map(
    ["as150brd-router0-10.150.0.254", "as151brd-router0-10.151.0.254"],
    ["10.150.0.72", "10.199.0.71"],
)
print(result.model_dump_json(indent=2))
EOF
矩阵符合测试结果：
"sources": [
    "as150brd-router0-10.150.0.254",
    "as151brd-router0-10.151.0.254"
  ],
  "targets": [
    "10.150.0.72",
    "10.199.0.71"
  ],
  "count": 1,
  "timeout_seconds": 2,
  "successful": true,
  "reachable_count": 2,
  "total_pairs": 4,
  "entries": [
    {
      "source": "as150brd-router0-10.150.0.254",
      "target": "10.150.0.72",
      "reachable": true,
      "exit_code": 0,
      "round_trip_ms": 0.242
    },
    {
      "source": "as150brd-router0-10.150.0.254",
      "target": "10.199.0.71",
      "reachable": false,
      "exit_code": 2,
      "round_trip_ms": null
    },
    {
      "source": "as151brd-router0-10.151.0.254",
      "target": "10.150.0.72",
      "reachable": true,
      "exit_code": 0,
      "round_trip_ms": 0.244
    },
    {
      "source": "as151brd-router0-10.151.0.254",
      "target": "10.199.0.71",
      "reachable": false,
      "exit_code": 2,
      "round_trip_ms": null
    }
  ]

```

### 5.3 回填条件

- 真实 ping 输出与 `_parse_ping_rtt` 预期（`time=` / `time<`）对照；busybox ping 若格式不同则更新正则；
- 回填 20×20 矩阵的实测耗时（供 Agent 评估批量调用成本）；
- 对照可达性结论与真实网络拓扑（跨 AS 可达、无网段不可达）。
