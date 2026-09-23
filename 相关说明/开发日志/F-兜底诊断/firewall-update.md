# network.firewall_update 开发日志

> 说明：本文档是 `firewall_update` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（F 类 兜底诊断·写）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.firewall_update` |
| 功能 | 运行时增删防火墙规则（`iptables -A/-D`） |
| 底层 | `iptables -A/-D <链> <规则体>` |
| 类型 | 命令型（**写操作**，条件可用 + 非持久） |
| 分类 | F 兜底诊断（写）·**条件可用** |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"防火墙写操作"工具；
- **为什么**：排障实验需要"丢某个端口的流量验证行为""放行某条路径"——只读不够；且分类矩阵 F 类写操作此前为空白；
- **决定**：封装 `iptables -A/-D`（条件可用 + 非持久，语义同其他写操作）；
- **安全考量（已落地）**：文档与日志显式警告——**错误的规则（如 DROP INPUT 全部流量）可能把节点锁死**；
- **产出**：一句话功能描述——"运行时增删防火墙规则（条件可用 + 非持久）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `iptables -A/-D` 的入参形态；
- **观察到 2 个事实**：
  1. 规则体是**自由格式的 iptables 参数**（`-p tcp --dport 22 -j DROP`）——无法结构化成固定字段，只能整段透传；
  2. 链名有约定（INPUT/OUTPUT/FORWARD + 自定义链，字母数字下划线）；
- **为什么重要**：事实 1 决定 `rule` 入参为整段字符串（按空白拆 argv 传输）；事实 2 决定链名校验；
- **限制（已文档化）**：带引号的参数（如 `-m string --string "x y"`）暂不支持（空白拆分会拆碎）——v1 明确边界；
- **产出**：入参形态观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `FirewallUpdateArguments` / `FirewallUpdateResult`；
- **关键决策**：
  - 入参 `action`（append/delete）+ `chain`（`_IPTABLES_CHAIN_PATTERN` 校验）+ `rule`（min 1 / max 500）；
  - 结果保留 `successful`/`exit_code`/`stderr`（P2/P3，iptables 原始错误如 "No chain/target/match by that name" 对排障有价值）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `firewall_update` 方法；
- **关键决策**：
  - 命令用参数向量 `["iptables", flag, chain] + rule.split()`——rule 按空白拆成 argv token，**无 shell、无注入**（P1）；
  - `-A`（append）/ `-D`（delete）由 action 映射；
  - `successful = result.exit_code == 0`；stderr 原样保留；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.firewall_update`（插在 `firewall_inspect` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 20 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 3 个用例 + 注册断言 15→20；
- **覆盖场景**：append 命令向量（rule 空白拆分）、delete 命令向量、坏链名校验；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M3 其他 4 个工具合计 5 条）；`test_api.py` count 22→27；`network-tools-index.md` 补总览/详述/排障速查/通用约定；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填（VM 实测，2026）**：当前实验环境**所有容器均无 iptables**（seed-emulator 无 Firewall 层，与 firewall-inspect 日志同结论）——给容器 apt-get install iptables 后可实测 append/delete；验证规则生效（firewall_inspect 复查）；验证重启还原。

### 条目 9：VM 实测——环境无 iptables 与保留结论（回填）

- **测试过程**：与 firewall-inspect 同批探测——所有容器 `iptables -S` 均 `command not found`；`seedemu/layers/` 无 Firewall.py、`examples/` 无防火墙示例（详见 firewall-inspect 日志条目 9）；
- **结论：保留工具**（条件可用 + 非持久）。由于环境无 iptables，append/delete 的**端到端实测尚未完成**；
  - 排除法价值：无防火墙节点上确认"没有 iptables"，Agent 可排除"规则丢包"这个原因；
  - 启用方式：运行时 `docker exec <容器> apt-get install -y iptables`，或构建时在 Dockerfile 加 `RUN apt-get install -y iptables`；
- **待回填**：装好 iptables 后按第 5 节实测——append/delete 命令向量、firewall_inspect 复查增删、重启还原、DROP INPUT 锁死风险。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 FirewallUpdateArguments / FirewallUpdateResult |
| `tools/network/tools.py` | 新增 `firewall_update` 方法 |
| `tools/network/registration.py` | 新增 `network.firewall_update` 注册块 |
| `tests/test_network_tools.py` | 注册断言 15→20（索引顺移）；新增 3 个用例 |
| `tests/test_api.py` | count 22→27；工具列表补 5 个名字 |
| `tool-service/README.md` | network 域补 5 条 + 条件可用说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/firewall-update.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### tools.py 新增

```python
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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.firewall_update",
        domain="network",
        description="Append or delete an iptables rule at runtime (conditional and non-persistent).",
    ),
    handler=tools.firewall_update,
    arguments_model=FirewallUpdateArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator 和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令

```bash
docker exec <带iptables的容器> iptables -A INPUT -p tcp --dport 8080 -j DROP
docker exec <带iptables的容器> iptables -S -t filter   # 复查规则在
docker exec <带iptables的容器> iptables -D INPUT -p tcp --dport 8080 -j DROP
docker exec <带iptables的容器> iptables -S -t filter   # 复查规则删掉
```

### 5.2 端到端 + 效果验证

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.firewall_update("<容器名>", "append", "INPUT", "-p tcp --dport 8080 -j DROP").model_dump_json(indent=2))
EOF
```

### 5.3 回填条件

- append/delete 命令向量与原始命令一致；firewall_inspect 复查规则增删成功；
- **已实测**：实验环境无 iptables 容器（seed-emulator 无 Firewall 层，见条目 9），需先 apt-get install iptables 再验证；
- **已实测**：实验环境无 iptables 容器（seed-emulator 无 Firewall 层），需先 apt-get install iptables 再验证；
- 验证非持久语义（重启容器规则消失）；
- 若实测发现 DROP INPUT 影响 ssh 等（锁死风险），回填经验供 Agent 参考。
