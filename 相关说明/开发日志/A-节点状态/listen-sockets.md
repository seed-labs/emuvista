# network.listen_sockets 开发日志

> 说明：本文档是 `listen_sockets` 从"一条命令"到"一个工具"的**真实开发日志**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（A 类 节点状态）。

---

## 0. 工具概览（收尾后回填）

| 项 | 内容 |
|---|---|
| 工具名 | `network.listen_sockets` |
| 功能 | 查看节点监听中的 TCP/UDP 套接字——协议、状态、本地/对端地址端口、进程名与 PID |
| 模仿命令 | `ss -tulnp`（iproute2） |
| 类型 | 命令型 + 文本解析 |
| 分类 | A 节点状态（只读） |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"查看节点监听端口"工具；
- **为什么**：排障"服务在不在"需要知道节点监听了哪些端口、由哪个进程持有；
  分类 A 类还缺这个只读工具；
- **决定**：封装 `ss -tulnp`（iproute2 预装；`-t/-u` 只看 TCP/UDP、`-l` 只看监听态、
  `-n` 数字端口、`-p` 显示进程）；
- **产出**：一句话功能描述（命令型）。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `ss -tulnp` 输出结构（黄金样本）；
- **观察到 5 个事实**：
  1. 首行是表头（`Netid` 开头），需跳过；
  2. 字段顺序固定：Netid State Recv-Q Send-Q Local Peer Process；
  3. 本地/对端地址形如 `0.0.0.0:53`（IPv4）、`[::]:53`（IPv6，带方括号）、`*:*`（通配）；
  4. Process 列形如 `users:(("named",pid=123,fd=20))`，可解析出进程名与 pid；`-p` 失败时该列缺失；
  5. UDP 的 State 是 `UNCONN`，TCP 是 `LISTEN`；
- **为什么重要**：这 5 个事实决定解析策略（位置解析 + 地址端口拆分 + 正则提取进程）；
- **风险点**：`ss` 输出格式因 iproute2 版本略有差异，黄金样本需在 VM 实测回填；
- **产出**：黄金样本 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `ListenSocketsArguments` / `ListenSocket` / `ListenSocketsResult`；
- **关键决策**：
  - 入参 `source` + `include_raw_output`（对齐接口/邻居工具的诊断开关）；
  - `ListenSocket` 拆 netid/state/本地地址端口/对端地址端口/进程名/pid；进程信息可选（None）；
  - 结果保留 `successful`/`exit_code`/`stderr`/`raw_output`（P2/P3）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `_split_addr_port` + `_parse_process`（模块级）+ `_parse_ss_line` + `listen_sockets`；
- **关键决策**：
  - 命令用参数向量 `["ss", "-tulnp"]`（P1）；
  - 位置解析（字段顺序固定，P5 的例外）+ 表头行跳过；
  - `_split_addr_port` 处理 IPv4/IPv6/通配三种地址形态（IPv6 方括号）；
  - `_parse_process` 用正则提取第一个进程名与 pid（容错：无进程信息返回 None）；
  - 文本逐行解析，无法映射的行丢弃（同 route_inspect 策略，无 parse_failed）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.listen_sockets`；
- **产出**：`/api/v1/tools` 可见（network 域达到 8 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 4 个用例（解析/无进程信息/命令失败/入参校验）+ 更新注册断言 7→8；
- **黄金样本**：覆盖 TCP/IPv4/UDP/IPv6 监听条目 + 进程信息；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README 补 `listen_sockets` 条目 + `test_api.py` count 14→15 + 索引补条目；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（第 4 节）

- **回填条件**：在 B00 容器实测 `ss -tulnp`，确认输出格式与黄金样本一致
  （表头、Process 列、IPv6 方括号）；如有差异更新解析器与 fixture。

---

## 2. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 ListenSocketsArguments / ListenSocket / ListenSocketsResult |
| `tools/network/tools.py` | 新增 `import re` + `_PROCESS_PATTERN` + `_split_addr_port`/`_parse_process` + `_parse_ss_line` + `listen_sockets` |
| `tools/network/registration.py` | 注册 `network.listen_sockets` |
| `tests/test_network_tools.py` | 注册断言 7→8；新增 4 个用例 + `GOLDEN_SS_OUTPUT` |
| `tests/test_api.py` | count 14→15 |
| `tool-service/README.md` | network 域补条目 |
| `learning/network-tools-index.md` | 补 listen_sockets 条目 |
| `learning/listen-sockets.md` | 本日志 |

---

## 3. 附录：最终代码（关键部分）

### models.py 新增

```python
class ListenSocketsArguments(ToolArguments):
    """监听套接字检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")
    include_raw_output: bool = Field(
        default=False,
        description="Include the complete ss output for diagnostics",
    )


class ListenSocket(BaseModel):
    """一个处于监听状态的套接字。"""

    netid: str = Field(description="Protocol and address family, e.g. tcp/udp/tcp6/udp6")
    state: str = Field(description="Socket state, e.g. LISTEN/UNCONN")
    local_address: str
    local_port: str
    peer_address: str
    peer_port: str
    process_name: str | None = Field(
        default=None,
        description="Process name listening on the socket",
    )
    pid: int | None = Field(default=None, description="Process ID listening on the socket")


class ListenSocketsResult(BaseModel):
    """查看节点监听套接字的结果。"""

    source: str
    successful: bool
    exit_code: int
    sockets: list[ListenSocket] = Field(default_factory=list)
    stderr: str
    raw_output: str | None = None
```

### tools.py 新增

```python
_PROCESS_PATTERN = re.compile(r'\("([^"]+)",pid=(\d+)')


def _split_addr_port(token: str) -> tuple[str, str]:
    """把 ``ss`` 的 ``地址:端口`` 拆成 (地址, 端口)。"""
    if token.startswith("["):
        # IPv6 形如 [::]:80，去掉方括号后拆端口
        end = token.rfind("]")
        return token[1:end], token[end + 2:]
    if ":" in token:
        # IPv4 或通配形如 0.0.0.0:53 / *:*，按最后一个冒号拆
        address, port = token.rsplit(":", 1)
        return address, port
    return token, ""


def _parse_process(token: str) -> tuple[str | None, int | None]:
    """从 ``users:(("named",pid=123,fd=20))`` 提取第一个进程名和 pid。"""
    match = _PROCESS_PATTERN.search(token)
    if match:
        return match.group(1), int(match.group(2))
    return None, None


@staticmethod
def _parse_ss_line(line: str) -> ListenSocket | None:
    """把 ``ss -tulnp`` 输出的一行解析成一条监听套接字。"""
    fields = line.split()
    if not fields or fields[0] == "Netid":
        return None
    if len(fields) < 6:
        return None

    local_address, local_port = _split_addr_port(fields[4])
    peer_address, peer_port = _split_addr_port(fields[5])
    process_name: str | None = None
    pid: int | None = None
    if len(fields) > 6:
        process_name, pid = _parse_process(fields[6])

    return ListenSocket(
        netid=fields[0],
        state=fields[1],
        local_address=local_address,
        local_port=local_port,
        peer_address=peer_address,
        peer_port=peer_port,
        process_name=process_name,
        pid=pid,
    )


# 方法签名
def listen_sockets(
    self,
    source: str,
    include_raw_output: bool = False,
) -> ListenSocketsResult:
    """查看仿真节点上监听中的 TCP/UDP 套接字及其进程。"""
    result = self._backend.execute(source, ["ss", "-tulnp"])

    sockets: list[ListenSocket] = []
    for line in result.stdout.splitlines():
        socket = self._parse_ss_line(line)
        if socket is not None:
            sockets.append(socket)

    return ListenSocketsResult(
        source=source,
        successful=result.exit_code == 0,
        exit_code=result.exit_code,
        sockets=sockets,
        stderr=result.stderr,
        raw_output=result.stdout if include_raw_output else None,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.listen_sockets",
        domain="network",
        description="Inspect the TCP and UDP listening sockets of an emulated node.",
    ),
    handler=tools.listen_sockets,
    arguments_model=ListenSocketsArguments,
)
```

---

## 4. 验证：在虚拟机里让 emulator 执行工具的底层命令

### 4.1 验证环境：B00_mini_internet

> 使用 `examples/internet/B00_mini_internet` 进行验证（BGP 全互联，节点上有 dns/bgp 等监听服务）。

构建（VM 内）：

```bash
cd <seed-emulator>/examples/internet/B00_mini_internet
python mini_internet.py
cd output && docker compose up -d
```

> **踩坑记录（切换实验必看）**：从旧实验切到 B00 前，必须先 `docker compose down` 旧实验
> 并 `docker network prune` 清理残留网络，否则报 `Pool overlaps with other one on this address space`。

### 4.2 对照原始命令

```bash
docker ps | grep -E "as[0-9]+"      # 看实际容器
docker exec <容器名> ss -tulnp        # 看该节点的监听端口（DNS 服务等）

这里使用：as150h-host_1-10.150.0.72
Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess
udp   UNCONN 0      0         127.0.0.11:50312      0.0.0.0:*          
tcp   LISTEN 0      4096      127.0.0.11:38933      0.0.0.0:*          

```

### 4.3 端到端

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python3.11 - <<EOF
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools

tools = NetworkTools(DockerRuntimeBackend())
result = tools.listen_sockets("as150h-host_1-10.150.0.72")
print(result.model_dump_json(indent=2))
EOF
```
```
{
  "source": "as150h-host_1-10.150.0.72",
  "successful": true,
  "exit_code": 0,
  "sockets": [
    {
      "netid": "udp",
      "state": "UNCONN",
      "local_address": "127.0.0.11",
      "local_port": "50312",
      "peer_address": "0.0.0.0",
      "peer_port": "*",
      "process_name": null,
      "pid": null
    },
    {
      "netid": "tcp",
      "state": "LISTEN",
      "local_address": "127.0.0.11",
      "local_port": "38933",
      "peer_address": "0.0.0.0",
      "peer_port": "*",
      "process_name": null,
      "pid": null
    }
  ],
  "stderr": "",
  "raw_output": null
}


```
> 对照要点：sockets 条目与 `ss -tulnp` 原始输出一致（协议/状态/地址/端口/进程）；
> IPv6 地址应为不带方括号的形式（如 `::`）；无进程信息的条目 process_name/pid 为 null。