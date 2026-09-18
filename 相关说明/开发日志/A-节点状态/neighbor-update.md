# network.neighbor_update 开发日志

> 说明：本文档是 `neighbor_update` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（A 类 节点状态·写）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.neighbor_update` |
| 功能 | 运行时增删内核邻居表条目（ARP 实验） |
| 底层 | `ip neigh add/del`（iproute2） |
| 类型 | 命令型（**写操作**，非持久） |
| 分类 | A 节点状态（写）·容器级调试 |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"邻居表写操作"工具；
- **为什么**：A 类写操作此前空白（interface_update / sysctl_update / neighbor_update 都是计划）；ARP 实验（手工指定对端 MAC、伪造邻居、验证邻居超时）需要 add/del；
- **决定**：封装 `ip neigh add/del`——邻居表是容器实现层（docker bridge 内）真实存在的对象（分类框架 1.2 定位：容器级调试工具）；
- **产出**：一句话功能描述——"运行时增删邻居表条目（ARP 实验，非持久）"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：分析 `ip neigh add/del` 的入参要求；
- **观察到 3 个事实**：
  1. `ip neigh add <IP> lladdr <MAC> dev <iface>`——**add 必须同时给 MAC 与接口**；
  2. `ip neigh del <IP> dev <iface>`——del 按 (destination, interface) 匹配；
  3. 手工添加的条目状态默认 PERMANENT（不走 ARP 解析）——这正是"伪造邻居"实验的语义；
- **为什么重要**：事实 1 决定入参校验（add 必须带 lladdr，model_validator 兜底）；事实 2 决定 del 的匹配语义；
- **产出**：语法观察 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `NeighborUpdateArguments` / `NeighborUpdateResult`；
- **关键决策**：
  - 入参 `operation`（add/del）+ `destination`（`ip_address` 强校验）+ `interface`（_IFNAME_PATTERN）+ `lladdr`（`_MAC_PATTERN` 格式校验，**add 必填**）；
  - **跨字段约束**：`model_validator` 兜底——add 无 lladdr 直接 ValidationError（写操作入参严格，P4）；
  - 结果保留 `successful`/`exit_code`/`stderr`（P2/P3）；
  - `extra="forbid"` + `Field(description)`（P4）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `neighbor_update` 方法；
- **关键决策**：
  - 命令用参数向量：`["ip", "neigh", operation, destination]` + add 时 `["lladdr", mac]` + `["dev", interface]`（P1）；
  - del 不带 lladdr（匹配删除）；
  - `successful = result.exit_code == 0`；stderr 原样保留；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.neighbor_update`（插在 `neighbor_inspect` 之后）；
- **产出**：`/api/v1/tools` 可见（network 域达到 20 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 3 个用例 + 注册断言 15→20；
- **覆盖场景**：add 命令向量（IP+MAC+dev）、del 命令向量、三连校验（add 无 MAC / 坏 MAC / 坏 IP）；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ `py_compile` + 纯 stdlib 冒烟；真实 pytest 由虚拟机验证；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M3 其他 4 个工具合计 5 条）；`test_api.py` count 22→27；`network-tools-index.md` 补总览/详述/排障速查/通用约定；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机端到端验证（见第 5 节）

- **回填条件**：真实容器 `ip neigh add/del` 行为；伪造邻居后 ping 的走向；重启还原确认。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 NeighborUpdateArguments / NeighborUpdateResult（含 MAC/接口/IP 校验 + model_validator） |
| `tools/network/tools.py` | 新增 `neighbor_update` 方法 |
| `tools/network/registration.py` | 新增 `network.neighbor_update` 注册块 |
| `tests/test_network_tools.py` | 注册断言 15→20（索引顺移）；新增 3 个用例 |
| `tests/test_api.py` | count 22→27；工具列表补 5 个名字 |
| `tool-service/README.md` | network 域补 5 条 + 条件可用说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查/通用约定 |
| `learning/neighbor-update.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增（校验是重点）

```python
class NeighborUpdateArguments(ToolArguments):
    """邻居表写操作（ip neigh add/del）的入参模型——ARP 实验，非持久。

    ``add`` 必须提供 MAC（lladdr）；``del`` 按 (destination, interface) 匹配删除。
    """

    source: str = Field(description="Name or ID of the emulated source container")
    operation: Literal["add", "del"] = Field(description="Whether to add or delete the neighbor entry")
    destination: str = Field(description="Neighbor IP address")
    interface: str = Field(description="Interface the neighbor is on, e.g. net0")
    lladdr: str | None = Field(
        default=None,
        description="Neighbor MAC address (required for add)",
    )

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        """必须是合法 IP。"""
        return str(ip_address(value))

    @field_validator("lladdr")
    @classmethod
    def validate_lladdr(cls, value: str | None) -> str | None:
        """MAC 地址格式校验。"""
        if value is None:
            return None
        if not _MAC_PATTERN.fullmatch(value):
            raise ValueError(f"invalid MAC address: {value!r}")
        return value

    @model_validator(mode="after")
    def require_lladdr_for_add(self):
        """add 必须提供 MAC。"""
        if self.operation == "add" and self.lladdr is None:
            raise ValueError("adding a neighbor entry requires lladdr (MAC address)")
        return self
```

### tools.py 新增

```python
# 方法签名
def neighbor_update(
    self,
    source: str,
    operation: str,
    destination: str,
    interface: str,
    lladdr: str | None = None,
) -> NeighborUpdateResult:
    """运行时增删内核邻居表条目（ip neigh add/del，ARP 实验，非持久）。"""
    command = ["ip", "neigh", operation, destination]
    if operation == "add":
        command += ["lladdr", lladdr]
    command += ["dev", interface]

    result = self._backend.execute(source, command)

    return NeighborUpdateResult(
        source=source,
        operation=operation,
        destination=destination,
        interface=interface,
        lladdr=lladdr,
        successful=result.exit_code == 0,
        exit_code=result.exit_code,
        stderr=result.stderr,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.neighbor_update",
        domain="network",
        description="Add or delete a kernel neighbor (ARP) entry at runtime (non-persistent).",
    ),
    handler=tools.neighbor_update,
    arguments_model=NeighborUpdateArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（A01/B00 已启动）和 agent-tools（tool-service 已就绪）。

### 5.1 对照原始命令

```bash
docker ps | grep -E "as[0-9]+" # 这里使用：as2brd-r100-10.100.0.2
docker exec as2brd-r100-10.100.0.2 ip neigh show
# 记一个真实的邻居 IP 与 MAC：
docker exec as2brd-r100-10.100.0.2 ip neigh add 10.151.0.1 lladdr 00:11:22:33:44:55 dev net_100_101
docker exec as2brd-r100-10.100.0.2 ip neigh show            # 应看到新条目（PERMANENT）
结果：
10.2.0.253 dev net_100_101 lladdr 1a:f4:24:40:d2:9c REACHABLE 
10.100.0.151 dev ix100 lladdr 7e:76:a7:eb:04:8d REACHABLE 
10.2.2.253 dev net_100_105 lladdr 82:90:52:eb:f0:06 REACHABLE 
10.100.0.150 dev ix100 lladdr f6:06:6d:18:65:17 REACHABLE 
10.100.0.100 dev ix100 lladdr 8a:27:64:6b:db:04 REACHABLE 
10.151.0.1 dev net_100_101 lladdr 00:11:22:33:44:55 PERMANENT 


docker exec as2brd-r100-10.100.0.2 ip neigh del 10.151.0.1 dev net_100_101
docker exec as2brd-r100-10.100.0.2 ip neigh show            # 条目删除
结果：
10.2.0.253 dev net_100_101 lladdr 1a:f4:24:40:d2:9c REACHABLE 
10.100.0.151 dev ix100 lladdr 7e:76:a7:eb:04:8d REACHABLE 
10.2.2.253 dev net_100_105 lladdr 82:90:52:eb:f0:06 REACHABLE 
10.100.0.150 dev ix100 lladdr f6:06:6d:18:65:17 REACHABLE 
10.100.0.100 dev ix100 lladdr 8a:27:64:6b:db:04 REACHABLE 
```

### 5.2 端到端

```bash
# 首先增添一下：
cd <agent-tools>/tool-service && source .venv/bin/activate
python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.neighbor_update("as2brd-r100-10.100.0.2", "add", "10.151.0.1", "net_100_101", lladdr="00:11:22:33:44:55").model_dump_json(indent=2))
EOF
# 成功添加(stderr为空)
{
  "source": "as2brd-r100-10.100.0.2",
  "operation": "add",
  "destination": "10.151.0.1",
  "interface": "net_100_101",
  "lladdr": "00:11:22:33:44:55",
  "successful": true,
  "exit_code": 0,
  "stderr": ""
}
# 然后验证一下结果
python3.11 - <<EOF
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools

tools = NetworkTools(DockerRuntimeBackend())
# 容器名替换为你 docker ps 里实际存在的（任一主机或路由器）
result = tools.neighbor_inspect("as2brd-r100-10.100.0.2")
print(result.model_dump_json(indent=2))
EOF
{
  "source": "as2brd-r100-10.100.0.2",
  "successful": true,
  "exit_code": 0,
  "parse_failed": false,
  "entries": [
    {
      "destination": "10.2.0.253",
      "lladdr": "1a:f4:24:40:d2:9c",
      "interface": "net_100_101",
      "state": [
        "REACHABLE"
      ],
      "is_router": false
    },
    {
      "destination": "10.100.0.151",
      "lladdr": "7e:76:a7:eb:04:8d",
      "interface": "ix100",
      "state": [
        "REACHABLE"
      ],
      "is_router": false
    },
    {
      "destination": "10.2.2.253",
      "lladdr": "82:90:52:eb:f0:06",
      "interface": "net_100_105",
      "state": [
        "STALE"
      ],
      "is_router": false
    },
    {
      "destination": "10.100.0.150",
      "lladdr": "f6:06:6d:18:65:17",
      "interface": "ix100",
      "state": [
        "STALE"
      ],
      "is_router": false
    },
    {
      "destination": "10.100.0.100",
      "lladdr": "8a:27:64:6b:db:04",
      "interface": "ix100",
      "state": [
        "STALE"
      ],
      "is_router": false
    },
    {
      "destination": "10.151.0.1",
      "lladdr": "00:11:22:33:44:55",
      "interface": "net_100_101",
      "state": [
        "PERMANENT"
      ],
      "is_router": false
    }
  ],
  "stderr": "",
  "raw_output": null
}
# 是可以看到最后有新添加的neighbor

# 再试一下删除
 python3.11 - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools
tools = NetworkTools(DockerRuntimeBackend())
print(tools.neighbor_update("as2brd-r100-10.100.0.2", "del", "10.151.0.1", "net_100_101", lladdr="00:11:22:33:44:55").model_dump_json(indent=2))
EOF                                                      
{
  "source": "as2brd-r100-10.100.0.2",
  "operation": "del",
  "destination": "10.151.0.1",
  "interface": "net_100_101",
  "lladdr": "00:11:22:33:44:55",
  "successful": true,
  "exit_code": 0,
  "stderr": ""
}
# 成功删除
```

### 5.3 回填条件

- add/del 命令向量与原始命令一致；`neighbor_inspect` 复查条目出现/消失；
- 伪造邻居后 ping 对端的行为（走手工 MAC）回填经验；
- 重启容器验证条目消失（非持久）。
