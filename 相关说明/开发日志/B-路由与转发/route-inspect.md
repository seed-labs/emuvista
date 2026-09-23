# network.route_inspect 开发日志

> 说明：本文档是 `route_inspect` 从"一条命令"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.route_inspect` |
| 功能 | 查看仿真节点（容器）的内核路由表，返回结构化路由条目 |
| 模仿命令 | `ip route show`（iproute2） |
| 类型 | 命令型 + 结构化解析 |
| 涉及文件 | 6 个：models/tools/registration + test_network_tools/test_api + README |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定要开发一个"查看节点路由表"的 network 工具；
- **为什么**：路由表是网络排障的核心信息，Agent 需要结构化结果而不是文本；
- **决定**：封装 `ip route show`（几乎所有仿真节点都自带 iproute2）；
- **产出**：一句话功能描述——"查看仿真节点内核路由表，返回结构化路由条目"。

### 条目 2：观察底层命令（阶段 A-1）

- **做了什么**：在 A01 仿真里执行 `docker exec as151h-host0-10.151.0.71 ip route show`；
- **观察到 4 个事实**：
  1. 第一列是目的地：`default` 或网段；
  2. 字段顺序不固定（`proto kernel scope link` 插在中间）；
  3. `via`（下一跳）不是每行都有；
  4. `src`（源地址）不是每行都有；
- **为什么重要**：这 4 个事实直接决定了模型字段（可选字段用 `None`）和解析算法（关键字扫描）；
- **产出**：黄金样本（真实输出）+ 设计需求清单。

### 条目 3：定义契约（阶段 B-1）
- **做了什么**：在 `models.py` 写 `RouteInspectArguments` / `RouteEntry` / `RouteInspectResult`；
- **关键决策**：
  - 入参只有 `source`（命令本身无参数）；
  - 结果拆两层：`RouteEntry`（单条路由，可复用）+ `RouteInspectResult`（整体）；
  - 可选字段 `str | None`：诚实表达"该路由没有此信息"；
  - `extra="forbid"` + `Field(description)`：安全边界 + Agent 说明书；
- **遇到的问题**：会话处于只读模式，写入 `models.py` 被沙箱拒绝 → 提权到 workspace-write 后成功；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：在 `tools.py` 写 `_parse_route_line` + `route_inspect`；
- **关键决策**：
  - 命令用参数向量 `["ip", "route", "show"]`，不拼 shell（防注入）；
  - `source` 是"在哪执行"，不混进命令；
  - 解析用**关键字扫描**（认 `via`/`dev`/`src`，其余跳过）——因为字段顺序不固定；
  - 解析失败返回 `None` 而非抛异常（容错）；
  - `successful = result.exit_code == 0`（语义映射）；
  - 保留 `exit_code`/`stderr`（诊断证据）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：在 `registration.py` 注册 `network.route_inspect`；
- **为什么**：注册后工具才可被发现；`input_schema` 由 `RouteInspectArguments` 自动推导，无需手写；
- **产出**：`/api/v1/tools` 可见该工具。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 2 个用例（正常解析 + 命令失败），更新注册断言；
- **遇到的问题**：
  - `FakeRuntimeBackend` 原来写死 `stdout="ping output"` → 给它加了 `stdout` 参数，让测试能喂黄金样本；
  - `test_api.py` 断言 `count == 5`，但实际已注册 9 个工具——**这个测试本来就是过期的**（DNS 域扩展到 5 个工具后没同步）→ 顺手修复为 `count == 10` 并补全工具列表；
- **产出**：测试用例 + 过期断言修复。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：`tool-service/README.md` 补 `route_inspect` 条目 + 容器前置依赖（`ip`/iproute2）；
- **小修正**：原文 "Both demonstrate..." → "These tools demonstrate..."（因为 network 域现在是 3 个工具）；
- **产出**：文档与代码一致。

### 条目 8：注释本地化（维护）

- **做了什么**：把 `_parse_route_line`、`route_inspect` 及两个模型类的注释从英文改为中文（按需求）；
- **遇到的问题**：写中文注释时遇 JS 模板字符串反引号未转义报错 → 改用转义写法后成功；
- **产出**：中文注释落地。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 3 个类：RouteInspectArguments / RouteEntry / RouteInspectResult |
| `tools/network/tools.py` | 新增 `_parse_route_line`（静态方法）+ `route_inspect` 方法 |
| `tools/network/registration.py` | 新增 `network.route_inspect` 注册块 |
| `tests/test_network_tools.py` | FakeRuntimeBackend 加 stdout 参数；注册断言 2→3；新增 2 个用例 |
| `tests/test_api.py` | count 5→10（含修复过期断言）；工具列表补全 |
| `tool-service/README.md` | network 域补条目 + iproute2 前置说明 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
class RouteInspectArguments(ToolArguments):
    """路由表检查工具的入参模型。"""

    source: str = Field(description="Name or ID of the emulated source container")


class RouteEntry(BaseModel):
    """内核路由表中的一条路由条目。"""

    destination: str = Field(description="Destination prefix, or 'default'")
    gateway: str | None = Field(default=None, description="Next-hop gateway address")
    interface: str | None = Field(default=None, description="Egress interface")
    source: str | None = Field(default=None, description="Preferred source address")


class RouteInspectResult(BaseModel):
    """查看节点路由表的结果。"""

    source: str
    successful: bool
    exit_code: int
    routes: list[RouteEntry] = Field(default_factory=list)
    stderr: str
```

### tools.py 新增

```python
@staticmethod
# 接收一行字符串，解析成一条 RouteEntry 路由条目
def _parse_route_line(line: str) -> RouteEntry | None:
    """把 ``ip route show`` 输出的一行解析成一条路由条目。"""

    # 按空白拆分成 token 列表，空行返回 None
    fields = line.split()
    if not fields:
        return None

    # 第一个 token 永远是目的地
    destination = fields[0]
    # 可选字段（下一跳/接口/源地址）先置为 None
    gateway: str | None = None
    interface: str | None = None
    source: str | None = None

    # 关键字扫描：从第二个 token 开始寻找 via/dev/src
    index = 1
    while index < len(fields):
        token = fields[index]
        # 命中关键字则取其后的 token 作为值
        if token in {"via", "dev", "src"} and index + 1 < len(fields):
            value = fields[index + 1]
            # 按关键字分类赋值
            if token == "via":# via表示下一跳
                gateway = value
            elif token == "dev":# dev表示转发接口
                interface = value
            else:# src表示源IP
                source = value
            index += 2
        else:
            # 非关键字 token 直接跳过
            index += 1

    # 组装并返回路由条目
    return RouteEntry(
        destination=destination,
        gateway=gateway,
        interface=interface,
        source=source,
    )

# 方法签名
def route_inspect(self, source: str) -> RouteInspectResult:
    """查看仿真节点内核的路由表。"""
    # 拼命令
    command = [
        "ip",
        "route",
        "show"
    ]
    # 命令执行
    result = self._backend.execute(source, command)

    routes: list[RouteEntry] = []
    # 逐行解析，无法映射的行直接丢弃
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        entry = self._parse_route_line(line)
        if entry is not None:
            routes.append(entry)

    # 组装最终的结果，并返回
    return RouteInspectResult(
        source=source,
        successful=result.exit_code == 0,
        exit_code=result.exit_code,
        routes=routes,
        stderr=result.stderr,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.route_inspect",
        domain="network",
        description="Inspect the kernel routing table of an emulated node.",
    ),
    handler=tools.route_inspect,
    arguments_model=RouteInspectArguments,
)
```

---

## 5. 验证：在虚拟机里让 emulator 执行工具的底层命令

> 前提：**虚拟机内同时具备** emulator（A01 已启动）和 agent-tools（tool-service 已就绪，.venv 已建好）。
> 目标：让工具服务连上 VM 里的 Docker，直接对 A01 的容器执行 `ip route show`，并和手敲的原始命令对照。

### 5.1 确认 emulator 在运行

```bash
docker ps | grep as151
# 应看到类似 as151h-host0-10.151.0.71 的容器（名字以实际为准）
```

### 5.2 跑单元测试

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python -m pytest
```

### 5.3 启动工具服务（终端 1）

```bash
python -m uvicorn seedemu_tool_service.main:app --reload
# 验证：
#   curl http://127.0.0.1:8000/api/v1/tools      → 应看到 network.route_inspect
#   curl http://127.0.0.1:8000/api/v1/runtime    → 应返回 "available": true（连上了 VM 的 Docker）
```
### 5.4 端到端：让工具真实执行（终端 2）

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python - <<'EOF'
from seedemu_tool_service.backends import DockerRuntimeBackend
from seedemu_tool_service.tools.network.tools import NetworkTools

tools = NetworkTools(DockerRuntimeBackend())
result = tools.route_inspect("as151h-host0-10.151.0.71")
print(result.model_dump_json(indent=2))
EOF
```
### 5.5 对照原始命令（两边输出应一致）

```bash
docker exec as151h-host0-10.151.0.71 ip route show
default via 10.151.0.254 dev net0 
10.151.0.0/24 dev net0 proto kernel scope link src 10.151.0.71 
```

```
"source": "as151h-host0-10.151.0.71",
  "successful": true,
  "exit_code": 0,
  "routes": [
    {
      "destination": "default",
      "gateway": "10.151.0.254",
      "interface": "net0",
      "source": null
    },
    {
      "destination": "10.151.0.0/24",
      "gateway": null,
      "interface": "net0",
      "source": "10.151.0.71"
    }
  ],
  "stderr": ""

```
