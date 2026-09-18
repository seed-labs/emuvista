# network.packet_capture 开发日志

> 说明：本文档是 `packet_capture` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（F 类 兜底诊断）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.packet_capture` |
| 功能 | 用 tcpdump 抓原始包——F 类"无假设、看原始证据" |
| 底层 | `timeout <秒> tcpdump -i <iface> -c <包数> -nn [BPF 过滤]` |
| 类型 | 命令型 + 文本（原始行） |
| 分类 | F 兜底诊断（只读） |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"抓包"工具；
- **为什么**：A/B/C/D/E 五类都是"定向提问"；当都查不出时（协议行为、握手失败、被谁丢弃），需要把最原始的包证据摊开——这是 F 类存在的原因；
- **决定**：封装 `tcpdump`（**seedemu-base 预装**，零新增依赖）；
- **产出**：一句话功能描述——"抓原始包（F 类兜底：原始证据，不做翻译）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 tcpdump 的行为与边界；
- **观察到 4 个事实**：
  1. `tcpdump -c N` 收满 N 个包后退出——**按包数有界**；但静默链路上会一直挂住，必须有墙钟上限；
  2. 墙钟上限用 `timeout(1)` 包装（coreutils 预装），超时退出码为 **124**（timeout 约定）——可据此识别"超时截断"而非失败；
  3. `-nn` 关闭主机名/端口解析——输出可解析、列宽稳定；
  4. tcpdump 会把**所有非选项参数拼接成 BPF 表达式**——过滤表达式传一个 argv token 即可，不需要自己分词；
  5. 抓包需要 root/CAP_NET_RAW（仿真容器默认满足，A-1 需实测确认）；
- **为什么重要**：事实 1/2 决定双上限（count + timeout）与 `timed_out` 语义字段；事实 4 决定过滤表达式作为一个 token 传入；
- **产出**：行为观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `PacketCaptureArguments` / `PacketCaptureResult`；
- **关键决策**：
  - 入参 `interface`（默认 any）+ `count`（默认 10，1-100）+ `timeout_seconds`（默认 5，1-30）+ `filter_expression`（可选，≤200 字符）；
  - `interface` 校验：`any` 或合法接口名（_IFNAME_PATTERN）；
  - `packets: list[str]`——一行一包的原始 tcpdump 行（F 类不做翻译，P5 诚实表达）；
  - **`timed_out` 语义字段**：exit_code==124 → 超时截断，**不是命令失败**（successful=False 但语义是"被墙钟截断"）；
  - `raw_output` 常驻（原始证据是 F 类的核心交付物）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `packet_capture` 方法；
- **关键决策**：
  - 命令用参数向量：`["timeout", sec, "tcpdump", "-i", iface, "-c", n, "-nn"]` + 可选过滤表达式（P1）；
  - 过滤表达式整体作为一个 token 追加（tcpdump 拼接非选项参数）；
  - `packets` = stdout 非空行列表；`timed_out = exit_code == 124`；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.packet_capture`（插在 `node_networks` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 20 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 4 个用例 + 注册断言 15→20；
- **覆盖场景**：黄金样本解析（2 行原始包）、过滤表达式透传 + 自定义接口/包数、超时截断（exit 124 → timed_out）、入参校验（count=0、坏接口名）；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M3 其他 4 个工具合计 5 条）；`test_api.py` count 22→27；`network-tools-index.md` 补总览/详述/排障速查/通用约定（条件可用说明）；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：真实容器 `tcpdump` 输出格式与预期一致（一行一包、`-nn` 无解析）；确认容器内 tcpdump 有抓包权限；timeout(1) 行为与 124 退出码。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 PacketCaptureArguments / PacketCaptureResult |
| `tools/network/tools.py` | 新增 `packet_capture` 方法 |
| `tools/network/registration.py` | 新增 `network.packet_capture` 注册块 |
| `tests/test_network_tools.py` | 注册断言 15→20（索引顺移）；新增 4 个用例 |
| `tests/test_api.py` | count 22→27；工具列表补 5 个名字 |
| `tool-service/README.md` | network 域补 5 条 + 条件可用说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/packet-capture.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### tools.py 新增

```python
# 方法签名
def packet_capture(
    self,
    source: str,
    interface: str = "any",
    count: int = 10,
    timeout_seconds: int = 5,
    filter_expression: str | None = None,
) -> PacketCaptureResult:
    """用 tcpdump 抓包（F 类兜底：原始证据，不做翻译）。

    ``timeout(1)`` 做墙钟上限——tcpdump 的 -c 只按包数退出，静默链路上会挂住；
    退出码 124 表示超时截断（timed_out=True），不是命令失败。
    """
    command = [
        "timeout",
        str(timeout_seconds),
        "tcpdump",
        "-i",
        interface,
        "-c",
        str(count),
        "-nn",
    ]
    if filter_expression is not None:
        # tcpdump 会把所有非选项参数拼接为 BPF 表达式，传一个 token 即可
        command.append(filter_expression)

    result = self._backend.execute(source, command)
    packets = [line for line in result.stdout.splitlines() if line.strip()]

    return PacketCaptureResult(
        source=source,
        interface=interface,
        count=count,
        timeout_seconds=timeout_seconds,
        filter_expression=filter_expression,
        successful=result.exit_code == 0,
        timed_out=result.exit_code == 124,  # timeout(1) 约定：124 = 超时被杀
        packets=packets,
        exit_code=result.exit_code,
        stderr=result.stderr,
        raw_output=result.stdout,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.packet_capture",
        domain="network",
        description="Capture raw packets on an interface with tcpdump (bounded by count and timeout).",
    ),
    handler=tools.packet_capture,
    arguments_model=PacketCaptureArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（B00 已启动）和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令

```bash
docker ps | grep -E "as[0-9]+"
# 一边 ping 一边抓包：
docker exec as162brd-router0-10.162.0.254 timeout 5 tcpdump -i any -c 10 -nn icmp
# 对照：另一终端 docker exec as162h-host_0-10.162.0.71 ping -c 10 as162brd-router0-10.162.0.254
```
```
tcpdump: data link type LINUX_SLL2
tcpdump: verbose output suppressed, use -v[v]... for full protocol decode
listening on any, link-type LINUX_SLL2 (Linux cooked v2), snapshot length 262144 bytes
09:40:19.642606 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 20, seq 2, length 64
09:40:19.642640 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 20, seq 2, length 64
09:40:20.697684 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 20, seq 3, length 64
09:40:20.697717 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 20, seq 3, length 64
09:40:21.721664 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 20, seq 4, length 64
09:40:21.721696 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 20, seq 4, length 64
09:40:22.745586 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 20, seq 5, length 64
09:40:22.745617 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 20, seq 5, length 64

8 packets captured
10 packets received by filter
0 packets dropped by kernel

```
### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.packet_capture("as162brd-router0-10.162.0.254", count=10, filter_expression="icmp").model_dump_json(indent=2))
EOF
```
```
"source": "as162brd-router0-10.162.0.254",
  "interface": "any",
  "count": 10,
  "timeout_seconds": 5,
  "filter_expression": "icmp",
  "successful": false,
  "timed_out": true,
  "packets": [
    "09:41:16.185647 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 4, length 64",
    "09:41:16.185683 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 4, length 64",
    "09:41:17.209739 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 5, length 64",
    "09:41:17.209778 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 5, length 64",
    "09:41:18.233581 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 6, length 64",
    "09:41:18.233613 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 6, length 64",
    "09:41:19.257857 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 7, length 64",
    "09:41:19.257895 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 7, length 64"
  ],
  "exit_code": 124,
  "stderr": "tcpdump: data link type LINUX_SLL2\ntcpdump: verbose output suppressed, use -v[v]... for full protocol decode\nlistening on any, link-type LINUX_SLL2 (Linux cooked v2), snapshot length 262144 bytes\n8 packets captured\n8 packets received by filter\n0 packets dropped by kernel\n",
  "raw_output": "09:41:16.185647 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 4, length 64\n09:41:16.185683 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 4, length 64\n09:41:17.209739 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 5, length 64\n09:41:17.209778 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 5, length 64\n09:41:18.233581 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 6, length 64\n09:41:18.233613 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 6, length 64\n09:41:19.257857 net0  In  IP 10.162.0.71 > 10.162.0.254: ICMP echo request, id 21, seq 7, length 64\n09:41:19.257895 net0  Out IP 10.162.0.254 > 10.162.0.71: ICMP echo reply, id 21, seq 7, length 64\n\n"

```

