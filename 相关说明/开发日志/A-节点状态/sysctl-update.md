# network.sysctl_update 开发日志

> 说明：本文档是 `sysctl_update` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（A 类 节点状态·写）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.sysctl_update` |
| 功能 | 运行时改内核 net.* 参数（如开转发、关 ICMP 响应） |
| 底层 | `sysctl -w <key>=<value>` |
| 类型 | 命令型（**写操作**，非持久） |
| 分类 | A 节点状态（写） |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"内核网络参数写操作"工具；
- **为什么**：A 类写操作空白；实验经常需要改内核行为——`net.ipv4.ip_forward=1`（把 host 变路由器）、`net.ipv4.icmp_echo_ignore_all=1`（节点对 ping 装死）、`net.ipv4.conf.all.rp_filter`（反欺骗）等；
- **决定**：封装 `sysctl -w`；
- **安全边界（已落地）**：键**只允许 `net.*` 命名空间**——防止 Agent 误写 kernel.* / vm.* 等区域（写操作入参严格，P4）；
- **产出**：一句话功能描述——"运行时改内核 net.* 参数（非持久）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `sysctl -w` 的行为；
- **观察到 3 个事实**：
  1. 语法 `sysctl -w <key>=<value>`；成功时 stdout 打印确认行（`net.ipv4.ip_forward = 1`）——**stdout 本身就是证据**；
  2. 值类型多样：0/1 整数、字符串（如 tcp_congestion_control=cubic）、含点号的值——校验要宽松但排除空格；
  3. 非持久：容器重启后 sysctl 还原（除非镜像内置配置）——实验语义；
- **为什么重要**：事实 1 决定结果带 `stdout`；事实 2 决定 `_SYSCTL_VALUE_PATTERN` 的宽松度；
- **产出**：行为观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `SysctlUpdateArguments` / `SysctlUpdateResult`；
- **关键决策**：
  - 入参 `key`（`_SYSCTL_KEY_PATTERN`：`^net\.[a-z0-9_.-]+$`）+ `value`（`_SYSCTL_VALUE_PATTERN`：字母数字 + 少数符号，无空格）；
  - 结果带 `stdout`（sysctl 确认行，P3 证据保留）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `sysctl_update` 方法；
- **关键决策**：
  - 命令用参数向量 `["sysctl", "-w", f"{key}={value}"]`（P1，key/value 已过格式校验，无注入面）；
  - `successful = result.exit_code == 0`；stdout/stderr 原样保留；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.sysctl_update`（插在 `route_update` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 20 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 2 个用例 + 注册断言 15→20；
- **覆盖场景**：命令向量 + stdout 透传；键不在 net.* 报错、值含空格报错；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M3 其他 4 个工具合计 5 条）；`test_api.py` count 22→27；`network-tools-index.md` 补总览/详述/排障速查/通用约定；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：真实容器 `sysctl -w net.ipv4.ip_forward=1` 行为；开转发后跨子网 ping 是否通；重启还原确认。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 SysctlUpdateArguments / SysctlUpdateResult（含 net.* 键校验） |
| `tools/network/tools.py` | 新增 `sysctl_update` 方法 |
| `tools/network/registration.py` | 新增 `network.sysctl_update` 注册块 |
| `tests/test_network_tools.py` | 注册断言 15→20（索引顺移）；新增 2 个用例 |
| `tests/test_api.py` | count 22→27；工具列表补 5 个名字 |
| `tool-service/README.md` | network 域补 5 条 + 条件可用说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/sysctl-update.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
class SysctlUpdateArguments(ToolArguments):
    """内核参数写操作（sysctl -w）的入参模型（A 类节点状态·写）。

    键**只允许 net.* 命名空间**（如 net.ipv4.ip_forward、net.ipv4.icmp_echo_ignore_all），
    防止误写内核其他区域；非持久（容器重启即还原）。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    key: str = Field(description="sysctl key under net.*, e.g. net.ipv4.ip_forward")
    value: str = Field(description="Value, e.g. 1 or 0")

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        """只允许 net.* 命名空间。"""
        if not _SYSCTL_KEY_PATTERN.fullmatch(value):
            raise ValueError(f"sysctl key must be under net.*, got {value!r}")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        """无空格的值（参数向量下防注入）。"""
        if not _SYSCTL_VALUE_PATTERN.fullmatch(value):
            raise ValueError(f"invalid sysctl value: {value!r}")
        return value
```

### tools.py 新增

```python
# 方法签名
def sysctl_update(self, source: str, key: str, value: str) -> SysctlUpdateResult:
    """运行时改内核 net.* 参数（sysctl -w，非持久）。

    键只允许 net.* 命名空间（入参层已校验）；stdout 保留 sysctl 确认行作为证据。
    """
    result = self._backend.execute(source, ["sysctl", "-w", f"{key}={value}"])

    return SysctlUpdateResult(
        source=source,
        key=key,
        value=value,
        successful=result.exit_code == 0,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.sysctl_update",
        domain="network",
        description="Set a kernel net.* parameter at runtime (non-persistent).",
    ),
    handler=tools.sysctl_update,
    arguments_model=SysctlUpdateArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator 和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令

```bash
docker exec as2brd-r100-10.100.0.2 sysctl -w net.ipv4.ip_forward=1
docker exec as2brd-r100-10.100.0.2 sysctl net.ipv4.ip_forward    # 复查：应为 1
docker exec as2brd-r100-10.100.0.2 sysctl -w net.ipv4.icmp_echo_ignore_all=1
docker exec as100brd-ix100-10.100.0.100 ping -c 2 as2brd-r100-10.100.0.2          # 应无响应（装死）

结果：
PING as2brd-r100-10.100.0.2 (10.100.0.2) 56(84) bytes of data.

--- as2brd-r100-10.100.0.2 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss, time 1022ms

docker exec as2brd-r100-10.100.0.2 sysctl -w net.ipv4.icmp_echo_ignore_all=0   # 还原

结果：
PING as2brd-r100-10.100.0.2 (10.100.0.2) 56(84) bytes of data.
64 bytes from as2brd-r100-10.100.0.2.output_net_ix_ix100 (10.100.0.2): icmp_seq=1 ttl=64 time=0.084 ms
64 bytes from as2brd-r100-10.100.0.2.output_net_ix_ix100 (10.100.0.2): icmp_seq=2 ttl=64 time=0.068 ms

--- as2brd-r100-10.100.0.2 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1001ms
rtt min/avg/max/mdev = 0.068/0.076/0.084/0.008 ms

```

### 5.2 端到端

```bash
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.sysctl_update("as2brd-r100-10.100.0.2", "net.ipv4.ip_forward", "1").model_dump_json(indent=2))
print(tools.sysctl_update("as2brd-r100-10.100.0.2", "net.ipv4.icmp_echo_ignore_all", "1").model_dump_json(indent=2))
EOF

{
  "source": "as2brd-r100-10.100.0.2",
  "key": "net.ipv4.ip_forward",
  "value": "1",
  "successful": true,
  "exit_code": 0,
  "stdout": "net.ipv4.ip_forward = 1\n",
  "stderr": ""
}
{
  "source": "as2brd-r100-10.100.0.2",
  "key": "net.ipv4.icmp_echo_ignore_all",
  "value": "1",
  "successful": true,
  "exit_code": 0,
  "stdout": "net.ipv4.icmp_echo_ignore_all = 1\n",
  "stderr": ""
}
# 改变生效，没有回显
docker exec as100brd-ix100-10.100.0.100 ping -c 2 as2brd-r100-10.100.0.2
PING as2brd-r100-10.100.0.2 (10.100.0.2) 56(84) bytes of data.

--- as2brd-r100-10.100.0.2 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss, time 1062ms

```

### 5.3 回填条件

- `sysctl -w` 确认行与 stdout 一致；改后效果（开转发→跨子网通、关 ICMP→ping 无响应）符合预期；
- 重启容器确认参数还原（非持久）；
- 若需支持 net.* 之外的其他键（如 kernel.*），需评估后扩展校验。
