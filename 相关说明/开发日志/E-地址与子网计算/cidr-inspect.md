# network.cidr_inspect 开发日志

> 说明：本文档是 `cidr_inspect` 从"一个想法"到"一个工具"的**真实开发日志**。
> 每个条目记录：**做了什么 / 为什么 / 结果 / 遇到的问题与解决**。
> 配套抽象方法论：`learning/framework.md`；分类依据：`learning/network-domain-classification-detailed.md`（E 类 地址与子网计算）。

---

## 0. 工具概览

| 项 | 内容 |
|---|---|
| 工具名 | `network.cidr_inspect` |
| 功能 | 归一化 IPv4/IPv6 CIDR 子网，报告网段/掩码/广播/主机范围/地址数/属性；可选测试某 IP 或子网的包含关系 |
| 底层 | 纯 Python `ipaddress` 模块（**不碰容器**，纯计算型） |
| 类型 | 纯计算型 |
| 分类 | E 地址与子网计算（只读） |
| 涉及文件 | models/tools/registration + tests + README + 索引 + 本日志 |

---

## 1. 开发日志条目

### 条目 1：需求定位（阶段 A-0）

- **做了什么**：确定开发"子网级计算"工具；
- **为什么**：E 类目前只有 `inspect_ip_address`（单地址）；Agent 做子网规划时需要网络地址/掩码/广播/可用主机范围/包含关系，单地址工具回答不了；
- **决定**：封装 `ipaddress.ip_network` 纯计算——零 backend 依赖，与 `inspect_ip_address` 同属 E 类样板；
- **产出**：一句话功能描述——"归一化 CIDR 子网并报告其属性（纯计算）"。

### 条目 2：观察底层模块行为（阶段 A-1）

- **做了什么**：用纯 stdlib 脚本核对 `ipaddress` 模块的真实行为（不依赖 VM）；
- **观察到 5 个事实**：
  1. **Python 3.14 移除了 `IPv4Network.num_hosts`**（AttributeError）——VM 的 3.10/3.11 有这个属性，主机 3.14 没有，**跨版本差异坑**；
  2. **IPv6 的 `broadcast_address` 在新版 Python 才存在**——3.10/3.11 无此属性，不能依赖；
  3. `/31` 可用 2 个地址、`/32` 可用 1 个地址（点对点/单地址前缀特殊语义）；
  4. `ip_network(value, strict=False)` 会**掩掉主机位**（`10.0.0.5/24` → `10.0.0.0/24`）；
  5. `subnet_of()` 可做子网包含判断；跨版本 `in` 返回 False 而非抛异常；
- **为什么重要**：这 5 个事实直接决定契约字段（`num_hosts` 手工计算、IPv6 `broadcast` 显式置 None）与入参校验策略（`strict=False` 归一化）；
- **产出**：行为核对结论 + 设计需求清单。

### 条目 3：定义契约（阶段 B-1）

- **做了什么**：`models.py` 写 `CidrInspectArguments` / `CidrInfo`；
- **关键决策**：
  - 入参 `network`（CIDR）+ `contains`（可选，IP 或 CIDR）；两个 `field_validator` 归一化入参（`strict=False` 容忍主机位；`contains` 先按 IP 解析、失败再按 CIDR）；
  - `num_hosts` **手工计算**：/31→2、/32→1、其余 `num_addresses-2`——不依赖已移除的 `num_hosts` 属性，跨 Python 版本稳定（P6 容错）；
  - IPv6 `broadcast=None`、`num_hosts=None`：无广播概念、无实用主机数语义（避免 2^64 级计算），用 `num_addresses` 表达规模；
  - `first_host`/`last_host`：IPv4 指可用主机范围，IPv6 指子网首/末地址——语义差异写进字段 description（P5 诚实表达）；
  - `contains_type`（address/network）区分"成员测试"与"子网包含"两种语义；
  - `extra="forbid"` + `Field(description)`（P4 安全边界 + Agent 说明书）；
- **产出**：契约定稿。

### 条目 4：实现方法本体（阶段 A-2）

- **做了什么**：`tools.py` 写 `cidr_inspect` 方法（放在 `inspect_ip_address` 之后，E 类兄弟方法相邻）；
- **关键决策**：
  - **纯计算**：不调用 backend（P7 纯计算型样板）；
  - 版本分支：IPv4 算广播与可用主机范围；IPv6 只算首/末地址；
  - `contains` 双模式解析：先 `ip_address`（成员测试），失败再 `ip_network`（子网包含）；**版本不一致直接返回 False**，避免跨版本 `subnet_of` 的异常风险；
  - `contains_address in parsed_network` 前先判版本（belt-and-suspenders，各版本行为统一）；
- **产出**：方法本体完成。

### 条目 5：注册（阶段 B-2）

- **做了什么**：`registration.py` 注册 `network.cidr_inspect`（插在 `inspect_ip_address` 之前）；
- **产出**：`/api/v1/tools` 可见（network 域达到 9 个）。

### 条目 6：测试（阶段 B-3）

- **做了什么**：`test_network_tools.py` 新增 9 个用例 + 注册断言 8→11；
- **覆盖场景**：IPv4 /24 全字段、掩主机位、IPv6 /64、/31 与 /32 特殊语义、地址包含（内/外）、子网包含（内/外）、`network` 与 `contains` 的入参校验失败；
- **遇到的问题**：本机无 pytest/pydantic（VM 才有）→ 用 `py_compile` 做语法检查，并用纯 stdlib 脚本核对 `ipaddress` 行为假设（见条目 2）；真实 pytest 由虚拟机验证（见第 5 节）；
- **产出**：测试用例 + 断言更新。

### 条目 7：文档同步（阶段 B-4）

- **做了什么**：README network 域补条目（与 M1 其他两个工具合计 3 条）；`test_api.py` count 15→18（3 个工具合计）；`network-tools-index.md` 补总览表/详述/排障速查；
- **产出**：文档与代码一致。

### 条目 8：待办——虚拟机 pytest 验证（见第 5 节）

- **回填条件**：在 VM 跑 `python -m pytest`，确认 9 个用例全过；若有断言与实际 `ipaddress` 行为不符（尤其 VM Python 版本差异），按真实行为更新断言。

---

## 3. 最终交付物清单

| 文件 | 改动 |
|---|---|
| `tools/network/models.py` | 新增 CidrInspectArguments / CidrInfo（含 2 个 field_validator）；import 加 `ip_network` |
| `tools/network/tools.py` | 新增 `cidr_inspect` 方法（纯计算）；import 加 `ip_network` 与 CidrInfo |
| `tools/network/registration.py` | 新增 `network.cidr_inspect` 注册块 |
| `tests/test_network_tools.py` | 注册断言 8→11（索引顺移）；新增 9 个用例 |
| `tests/test_api.py` | count 15→18；工具列表补 3 个名字 |
| `tool-service/README.md` | network 域补 3 条 + 纯计算说明 |
| `learning/network-tools-index.md` | 补总览/详述/排障速查 |
| `learning/cidr-inspect.md` | 本日志 |

---

## 4. 附录：最终代码（关键部分）

### models.py 新增

```python
class CidrInspectArguments(ToolArguments):
    """CIDR 子网检查工具的入参模型（纯计算，不碰容器）。"""

    network: str = Field(
        description="IPv4 or IPv6 network in CIDR notation, e.g. 10.0.0.0/24",
    )
    contains: str | None = Field(
        default=None,
        description="Optional IP address or CIDR network to test for membership in `network`",
    )

    @field_validator("network")
    @classmethod
    def validate_network(cls, value: str) -> str:
        """解析并归一化 CIDR；strict=False 容忍主机位（10.0.0.5/24 → 10.0.0.0/24）。"""
        return str(ip_network(value, strict=False))

    @field_validator("contains")
    @classmethod
    def validate_contains(cls, value: str | None) -> str | None:
        """把 contains 归一化为 IP 地址或 CIDR 网络的字符串形式。"""
        if value is None:
            return None
        try:
            return str(ip_address(value))
        except ValueError:
            pass
        try:
            return str(ip_network(value, strict=False))
        except ValueError:
            raise ValueError(f"contains must be an IP address or CIDR network, got {value!r}")


class CidrInfo(BaseModel):
    """一个 CIDR 子网的计算结果。

    ``broadcast`` 仅 IPv4 有（IPv6 无广播概念，恒为 None）；``num_hosts`` 仅 IPv4
    给出（IPv6 无实用主机数语义，用 ``num_addresses`` 表达规模）；
    ``first_host``/``last_host`` 在 IPv4 指可用主机范围（含 /31、/32 特殊语义），
    在 IPv6 指子网首/末地址。
    """

    network: str = Field(description="Normalized network in CIDR notation, e.g. 10.0.0.0/24")
    version: Literal[4, 6]
    prefixlen: int
    netmask: str
    broadcast: str | None = Field(
        default=None,
        description="Broadcast address (IPv4 only; IPv6 has no broadcast concept)",
    )
    num_addresses: int = Field(description="Total number of addresses in the network")
    num_hosts: int | None = Field(
        default=None,
        description="Usable host count (IPv4; IPv6 has no practical host-count semantics)",
    )
    first_host: str | None = Field(
        default=None,
        description="IPv4: first usable host; IPv6: first address of the network",
    )
    last_host: str | None = Field(
        default=None,
        description="IPv4: last usable host; IPv6: last address of the network",
    )
    is_private: bool
    is_global: bool
    is_loopback: bool
    is_link_local: bool
    contains: str | None = Field(default=None, description="Normalized membership-test input")
    contains_type: Literal["address", "network"] | None = Field(
        default=None,
        description="Whether `contains` is an IP address or a CIDR network",
    )
    contains_result: bool | None = Field(default=None, description="Membership test outcome")
```

### tools.py 新增（方法本体，纯计算）

```python
# 方法签名
def cidr_inspect(self, network: str, contains: str | None = None) -> CidrInfo:
    """纯计算：归一化一个 CIDR 子网并报告其属性（不碰容器）。"""
    parsed_network = ip_network(network, strict=False)

    # IPv4：广播/主机范围有明确定义；/31、/32 是点对点/单地址前缀，语义特殊
    if parsed_network.version == 4:
        broadcast = str(parsed_network.broadcast_address)
        if parsed_network.prefixlen == 31:
            num_hosts = 2
            first_host = str(parsed_network.network_address)
            last_host = str(parsed_network.network_address + 1)
        elif parsed_network.prefixlen == 32:
            num_hosts = 1
            first_host = str(parsed_network.network_address)
            last_host = str(parsed_network.network_address)
        else:
            num_hosts = parsed_network.num_addresses - 2
            first_host = str(parsed_network.network_address + 1)
            last_host = str(parsed_network.broadcast_address - 1)
    else:
        # IPv6 无广播概念；主机数无实用语义（避免 2^64 级计算），报告子网首/末地址
        broadcast = None
        num_hosts = None
        first_host = str(parsed_network.network_address)
        last_host = str(parsed_network.network_address + (parsed_network.num_addresses - 1))

    # 可选的包含关系测试：contains 可能是 IP 地址（成员测试）或 CIDR（子网包含）
    contains_type: str | None = None
    contains_result: bool | None = None
    if contains is not None:
        try:
            contains_address = ip_address(contains)
            contains_type = "address"
            contains_result = (
                contains_address.version == parsed_network.version
                and contains_address in parsed_network
            )
        except ValueError:
            contains_network = ip_network(contains, strict=False)
            contains_type = "network"
            contains_result = (
                contains_network.version == parsed_network.version
                and contains_network.subnet_of(parsed_network)
            )

    return CidrInfo(
        network=str(parsed_network),
        version=parsed_network.version,
        prefixlen=parsed_network.prefixlen,
        netmask=str(parsed_network.netmask),
        broadcast=broadcast,
        num_addresses=parsed_network.num_addresses,
        num_hosts=num_hosts,
        first_host=first_host,
        last_host=last_host,
        is_private=parsed_network.is_private,
        is_global=parsed_network.is_global,
        is_loopback=parsed_network.is_loopback,
        is_link_local=parsed_network.is_link_local,
        contains=contains,
        contains_type=contains_type,
        contains_result=contains_result,
    )
```

### registration.py 新增

```python
registry.register(
    definition=ToolDefinition(
        name="network.cidr_inspect",
        domain="network",
        description="Inspect a CIDR network: normalized address, netmask, broadcast, host range, and membership.",
    ),
    handler=tools.cidr_inspect,
    arguments_model=CidrInspectArguments,
)
```

---

## 5. 验证：在虚拟机里跑 pytest

> 前提：VM 内具备完整开发环境（pytest/fastapi/pydantic 已装、tool-service 依赖就绪）。
> 本工具是**纯计算**，不依赖容器/Docker，验证只需跑单元测试。

### 5.1 跑单元测试

```bash
cd <agent-tools>/tool-service
source .venv/bin/activate
python -m pytest tests/test_network_tools.py -k cidr -v
# 再跑全量确认无回归
python -m pytest
```

### 5.2 手工冒烟（可选）

```bash
python - <<'EOF'
from ipaddress import ip_network, ip_address
n = ip_network('10.151.0.0/24', strict=False)
print(n.network_address, n.netmask, n.broadcast_address)
print(ip_address('10.151.0.7') in n)
EOF
```
```
10.151.0.0 255.255.255.0 10.151.0.255
True

```

