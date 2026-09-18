# network.node_networks 开发日志

> 说明：本文档是 `node_networks` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（D 类 仿真网络 ★emulator 特有）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.node_networks` |
| 功能 | 查看节点连接的**仿真网络**清单及每个网络配置的链路属性（网络名/前缀/延迟/带宽/丢包） |
| 底层 | `cat /ifinfo.txt`（seed-emulator Base.py 在编译期写入每个容器的配置清单） |
| 类型 | 命令型 + 文本解析（冒号分隔） |
| 分类 | D 仿真网络（只读）★emulator 特有 |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"节点连接的仿真网络"工具；
- **为什么**：D 类（仿真网络）是分类矩阵里**完全空白**的核心类别；Agent 回答"这个节点连了哪些仿真网络、每条链路配了多少延迟/带宽/丢包"时，A/B/C 类工具都答不了——链路属性是 emulator 的一等公民概念，但只存在于容器内的配置清单里；
- **决定**：读 `/ifinfo.txt`——seed-emulator 的 `Base.py` 给每个节点写入该文件（`网络名:前缀:延迟:带宽:丢包`），零新增依赖、零额外命令；
- **产出**：一句话功能描述——"查看节点连接的仿真网络及其链路属性配置"。

### 条目 2：观察底层文件（阶段 A-1）

- **做了什么**：分析 `/ifinfo.txt` 的结构（基于对 seed-emulator 源码调研的分类框架结论）；
- **预期 4 个事实**：
  1. 每行一条仿真网络，行格式 `网络名:前缀:延迟:带宽:丢包`（冒号分隔 5 字段）；
  2. 延迟形如 `10ms`、带宽形如 `100mbit`、丢包形如 `0%` 或 `0.1%`——**带单位字符串**，不是纯数字；
  3. 字段可能缺失（emulator 版本差异）——网络名必有，其余可能为空；
  4. 文件不存在/读失败时 `cat` 退出码非零、错误进 stderr；
- **风险点（已落地）**：**真实输出必须在 VM 实测回填**（黄金样本）——若实际分隔符/字段数与预期不同，按真实输出更新解析器与测试 fixture；
- **产出**：预期结构 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `NodeNetworksArguments` / `NetworkInfo` / `NodeNetworksResult`；
- **关键决策**：
  - 入参 `source` + `include_raw_output`（可选，诊断开关，对齐接口/邻居/监听工具）；
  - `NetworkInfo` 的 latency/bandwidth/drop 用 **`str | None`**：文件存的就是带单位字符串（`10ms`），不猜单位不数值化——诚实表达、零转换风险（P6）；
  - `parse_failed` 字段：命令成功但 stdout 非空且一行都没解析出来 → 区分"文件为空（合法状态）"与"格式不识别（emulator 版本差异）"；
  - 结果保留 `successful`/`exit_code`/`stderr`/`raw_output`（P2/P3）；
  - `extra="forbid"` + `Field(description)`（P4 安全边界 + Agent 说明书）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `_parse_ifinfo_line`（静态方法）+ `node_networks` 方法；
- **关键决策**：
  - 命令用参数向量 `["cat", "/ifinfo.txt"]`，不拼 shell（P1）；`cat` 是 coreutils 基础命令，seedemu-base 镜像必然预装（A-1 需一并确认）；
  - 解析 gate 在 `exit_code == 0` 上：命令失败（文件不存在）时不解析 stdout（内容可能是报错文本）；
  - 逐行容错：`split(":")` 后第一个字段为空的行丢弃；字段缺失补 None（版本差异容忍）；
  - `parse_failed = bool(non_empty_lines) and not networks`——非空输出但零解析 = 格式不识别；
  - `include_raw_output` 决定是否返回原文（诊断用，格式依赖 emulator 版本）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.node_networks`（插在 `neighbor_inspect` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 10 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 5 个用例 + 注册断言 8→11；
- **覆盖场景**：黄金样本解析（2 条网络全字段）、字段缺失容忍（只有名字/只有名字+前缀）、`parse_failed`（`: ` 行 → 零解析）、命令失败（文件不存在）、`include_raw_output` 透传；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ 用 `py_compile` 做语法检查；真实 pytest + docker 端到端由虚拟机验证（见第 5 节）；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M1 其他两个工具合计 3 条）；`test_api.py` count 15→18（3 个工具合计）；`network-tools-index.md` 补总览表/详述/排障速查；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：在真实容器 `cat /ifinfo.txt`，确认行格式与黄金样本一致（字段数、分隔符、单位写法）；如有差异更新解析器与 fixture。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 NodeNetworksArguments / NetworkInfo / NodeNetworksResult |
| `tools/network/tools.py` | 新增 `_parse_ifinfo_line`（静态方法）+ `node_networks` 方法 |
| `tools/network/registration.py` | 新增 `network.node_networks` 注册块 |
| `tests/test_network_tools.py` | 注册断言 8→11（索引顺移）；新增 5 个用例 + `GOLDEN_IFINFO` |
| `tests/test_api.py` | count 15→18；工具列表补 3 个名字 |
| `tool-service/README.md` | network 域补 3 条 + ifinfo 说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查 |
| `learning/node-networks.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
class NodeNetworksArguments(ToolArguments):
    """节点仿真网络检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete /ifinfo.txt content for diagnostics",
    )


class NetworkInfo(BaseModel):
    """仿真网络配置清单（/ifinfo.txt）中的一条：节点连接的一个仿真网络。"""

    name: str = Field(description="Emulated network name, e.g. net0")
    prefix: str | None = Field(default=None, description="Network prefix, e.g. 10.151.0.0/24")
    latency: str | None = Field(default=None, description="Configured latency, e.g. 10ms")
    bandwidth: str | None = Field(default=None, description="Configured bandwidth, e.g. 100mbit")
    drop: str | None = Field(default=None, description="Configured drop ratio, e.g. 0%")


class NodeNetworksResult(BaseModel):
    """查看节点连接的仿真网络的结果。

    ``parse_failed`` 表示命令成功但 stdout 非空且一行都没解析出来——
    用于区分"文件为空（合法状态）"与"格式不识别（emulator 版本差异）"。
    """

    source: str
    successful: bool
    exit_code: int
    parse_failed: bool = False
    networks: list[NetworkInfo] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None
```

### tools.py 新增

```python
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
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.node_networks",
        domain="network",
        description="Inspect the emulated networks a node connects to and their configured link properties.",
    ),
    handler=tools.node_networks,
    arguments_model=NodeNetworksArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（B00/A01 已启动）和 agent-tools（tool-service 已就绪，.venv 已建好）。

### 5.1 对照原始命令

```bash
docker ps | grep -E "as[0-9]+"      # 看实际有哪些容器在跑
docker exec as150brd-router0-10.150.0.254 cat /ifinfo.txt
# 预期每行形如：net0:10.151.0.0/24:10ms:100mbit:0%
net0:10.150.0.0/24:0:0:0
ix100:10.100.0.0/24:0:0:0
```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python3.11 - <<EOF
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools

tools = NetworkTools(DockerRuntimeBackend())
result = tools.node_networks("as150brd-router0-10.150.0.254")
print(result.model_dump_json(indent=2))
EOF
```
```
"source": "as150brd-router0-10.150.0.254",
  "successful": true,
  "exit_code": 0,
  "parse_failed": false,
  "networks": [
    {
      "name": "net0",
      "prefix": "10.150.0.0/24",
      "latency": "0",
      "bandwidth": "0",
      "drop": "0"
    },
    {
      "name": "ix100",
      "prefix": "10.100.0.0/24",
      "latency": "0",
      "bandwidth": "0",
      "drop": "0"
    }
  ],
  "stderr": "",
  "raw_output": null

```

