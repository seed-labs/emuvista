# DshAgentService 设计

本文定义 EmuVista 中的 SEED 服务层 `dshagent`。每次 `install()` 声明一个 Agent 实例。实例通过 SEED Binding 绑定到容器，拥有独立的 DSH Profile、`DSH_HOME` 和运行状态。本文中的接口与运行行为为设计约定。

## 部署 Python API

```python
from pathlib import Path

from seedemu.compiler import Docker
from seedemu.core import Binding, Emulator, Filter
from seedemu.layers import Base, Routing

from services.DshAgentService import DshAgentService

here = Path(__file__).resolve().parent
emu = Emulator()
base = Base()
asys = base.createAutonomousSystem(150)
asys.createNetwork("net0")
asys.createRouter("router0").joinNetwork("net0")
asys.createHost("alice").joinNetwork("net0")
asys.createHost("bob").joinNetwork("net0")

agents = DshAgentService()
agents.install("alice")
agents.install("bob")

emu.addLayer(base)
emu.addLayer(Routing())
emu.addLayer(agents)
emu.addBinding(Binding("alice", filter=Filter(asn=150, nodeName="^alice$")))
emu.addBinding(Binding("bob", filter=Filter(asn=150, nodeName="^bob$")))

emu.render()
emu.compile(Docker(), str(here / "output"))
```

| 调用 | 契约 |
| --- | --- |
| `DshAgentService(*, runtime_image=None, state_root=None)` | 创建 SEED 服务层。默认使用项目固定版本的共享 DSH 运行时镜像。`state_root` 可指定容器内的绝对路径，作为实例状态目录的根。 |
| `agents.install(name, *, bundles=(), config=None)` | 声明实例并返回对应的 SEED Server 对象。`name` 是虚拟节点名，也是默认的 Soul 居民 ID。`bundles` 是有序路径列表，`config` 是可选的实例 YAML 文件路径。 |
| `emu.addBinding(...)` | 将实例绑定到 SEED 主机。重复实例名和多个实例绑定到同一容器都应报错，最晚在渲染阶段发现。 |

上例遵循 SEED 的 Service、Server 和 Binding 结构。调用 install() 声明虚拟实例并返回 Server，Binding 选择实际节点，render() 完成校验和装配，compile() 生成部署文件。需要组合额外插件时，把 install() 声明改为：

```python
agents.install(
    "alice",
    bundles=[here / "bundles/cloud-tools.yml", here / "bundles/chat-tools.yml"],
    config=here / "agents/alice.yml",
)
agents.install("bob", bundles=[here / "bundles/cloud-tools.yml"])
```

`dshagent()` 仍可作为工厂入口，接受相同参数。

## Bundle 声明

`bundles=` 接受原生 DSH Bundle 包目录和 EmuVista YAML 声明。对于 YAML，服务生成原生 DSH 所需的 `package.json` 和 `cordis.patch.yml`，再将 Bundle 装配到实例的 Profile。单个插件也使用同一入口，通过只含一个插件的 Bundle 声明。可复用插件源码放在 `agent-plugins/`，示例或实验在自己的目录中维护 Bundle 装配配置。

```yaml
name: chat-tools
plugins:
  - id: chat
    package: ../../../agent-plugins/chat-client
    preset: resident
    config:
      endpoint: ws://chat.example.test:6060
```

`package` 的相对路径以声明文件所在目录为基准。`preset: resident` 将插件装配到服务提供的 Agent preset，省略该字段时装配到 Host。

## 实例配置

`config=` 用于 Profile 设置和实例级插件参数。该实例加载哪些额外 Bundle 由 `bundles=` 决定。

```yaml
profile:
  name: resident
  template: web
  startup: manual
plugins:
  soul:
    config:
      card:
        identity: 负责整理共享资料的居民
        values: [清晰沟通]
  chat:
    config:
      username: alice
```

装配按服务默认值、Bundle 配置、实例覆盖的顺序执行。插件配置的映射递归合并，列表整项替换。上例中的 `chat.username` 和 Bundle 提供的 `chat.endpoint` 同时生效，Soul 的 `residentId` 保持由实例名推导。服务向 DSH 提供合并后的完整 `config`，以适应 Cordis patch 对配置块的替换行为。实例覆盖引用未装配的插件，或多个 Bundle 在同一作用域声明同一个插件 ID 时，渲染报错并列出配置来源。

## 服务默认值

| 项目 | 默认行为 |
| --- | --- |
| Profile | 以 DSH 官方 `web` 模板初始化名为 `dshagent` 的自定义 Profile，默认 Agent preset 为 `resident`。 |
| 基础能力 | EmuVista 默认装配 Soul、Claw 和 Schedule，并提供中性人格卡和运行时上下文。Claw 使用可用的会话和观察工具，Soul 周期生活模式由操作者显式启用。 |
| 启动 | 默认为 `manual`。设为 `auto` 时，容器启动流程在 Profile 初始化成功后启动 DSH Web。 |
| 状态 | 每个实例使用独立的 `DSH_HOME`。跨容器重建保留 Profile、会话、记忆和计划需要将该目录挂载到持久卷。`state_root` 用于指定状态目录的位置。 |
| 凭据 | 模型密钥和用户密码在运行时配置。生成的 Bundle、Profile 初始化脚本和镜像只包含公开配置。 |

## 部署与热插拔

1. **渲染。** 校验 SEED 绑定、Bundle 来源、插件 ID 和实例覆盖，生成装配文件。
2. **构建。** 复用共享运行时镜像，将 Bundle 和插件源码放到稳定的容器路径。开发用的 `link:` 依赖指向容器内路径。
3. **初始化。** 首次初始化使用 DSH CLI 从模板创建 Profile 并装配 Bundle，后续启动复用已有 Profile。拓扑声明变更后，通过显式操作更新已有 Profile，以保留对现场热插拔结果的控制。
4. **运行。** 已装配且支持热更新的插件可通过 DSH Plugin Manager 在 Web 中启停。新增包或变更 Bundle 成员后，检查当前进程的加载状态，并通过实际工具调用验证。拓扑中的 `bundles=` 是下一次部署的声明来源。

## 运行时 Python API

部署脚本用 `DshAgentService().install(...)` 声明首次启动的插件组合。容器启动后，使用 `DshAgentRuntime` 操作当前 DSH 进程。设计中的常用操作默认等待生效，失败时抛出带诊断的异常。若启动时通过 Compose 的项目参数指定了项目名，调用 from_compose() 时传入同一个 project 值。

```python
from pathlib import Path

from services.DshAgentService import DshAgentRuntime

here = Path(__file__).resolve().parent
runtime = DshAgentRuntime.from_compose(here / "output/docker-compose.yml")
alice = runtime.agent("alice")

for bundle in alice.plugins.list():
    print(bundle.name, bundle.status)

alice.plugins.disable("chat-tools")
alice.plugins.enable("chat-tools")
print(alice.plugins.get("chat-tools").status)
```

| 接口 | 返回值与行为 |
| --- | --- |
| `DshAgentRuntime.from_compose(compose_file, *, project=None)` | 接收 Compose 文件路径，返回运行时管理对象。省略 `project` 时使用 Compose 解析得到的项目名。 |
| `runtime.agent(name)` | 按 `install()` 声明的实例名返回 `DshAgentHandle`。每次操作时解析当前容器。 |
| `agent.plugins.list()` | 返回 `tuple[BundleState, ...]`，包含启用和停用的已安装 Bundle，按逻辑名称排序。 |
| `agent.plugins.get(name)` | 返回指定 Bundle 的 `BundleState`。接受声明中的逻辑名称和完整 DSH 包名。 |
| `agent.plugins.enable(name, *, wait=True, timeout=30, check=True)` | 请求运行中的 DSH 启用已安装的 Bundle，返回 `PluginChange`。 |
| `agent.plugins.disable(name, *, wait=True, timeout=30, check=True)` | 请求运行中的 DSH 停用已安装的 Bundle，返回 `PluginChange`。保留包和配置供重新启用。 |

`BundleState`、`PluginState` 和 `PluginChange` 是只读数据对象，适合脚本判断或使用 `dataclasses.asdict()` 序列化。

| 类型 | 字段 |
| --- | --- |
| `BundleState` | `name`（逻辑名称）、`package`（DSH 包名）、`enabled`（配置中的启用状态）、`status`（`active`、`inactive`、`pending`、`failed` 或 `unknown`）、`plugins`（`tuple[PluginState, ...]`）。 |
| `PluginState` | `id`、`package`、`scope`（`host` 或 preset 名）、`status`（与 Bundle 使用相同的状态枚举）、`detail`（可选诊断）。 |
| `PluginChange` | `operation`、`name`、`status`、`before`、`after`、`detail`。`before` 和 `after` 为可取得的 `BundleState` 快照。 |

启停方法默认使用 check=True。wait=True 时只有 applied 正常返回，wait=False 时 pending 也可正常返回。使用 check=False 可直接检查操作结果，例如在批量脚本中汇总失败。变更状态与 Bundle 当前加载状态各有独立的含义。

| `PluginChange.status` | 语义 |
| --- | --- |
| `applied` | 当前 DSH 进程确认目标状态已生效。重复请求已生效的状态也返回此值。 |
| `pending` | DSH 已接受请求，调用选择了 `wait=False`，加载结果需要随后用 `get()` 查询。 |
| `restart_required` | DSH 明确报告变更需要重启。调用方可据此安排重启。 |
| `failed` | DSH 拒绝变更或插件加载失败。`detail` 提供可获取的原因。 |
| `timeout` | 等待期限内未确认结果，可能仍在应用。调用方先用 `get()` 核对再决定是否重试。 |

实例名不存在、Bundle 未安装、实例未运行、容器不唯一或管理接口认证失败时抛出 `DshAgentRuntimeError`。异常提供 `code`、`instance` 和可选的 `bundle`，便于脚本处理。参数无效时抛出 ValueError。check=False 只控制变更结果的处理，实例定位和认证等错误仍抛出异常。check=True 下，未达到目标状态的异常通过 change 字段携带 PluginChange，并使用对应的状态作为 code。修改请求发出后连接断开且结果未知时，以 `timeout` 报告并提示重新查询。等待时间以秒为单位。

### 实例定位与状态同步

一个容器运行多个隔离的 DSH Web 进程时，可使用 agent.for_process(port=..., log=...) 选择该容器内的端口和绝对日志路径。默认实例使用服务提供的启动入口和管理端口。agent.container 返回当前容器 ID，agent.metadata() 返回该实例的部署元数据。

服务层将虚拟实例名作为 SEED 节点标签写入生成的 Compose 服务，并在镜像内另存 Profile 名、DSH 本地管理端点和 Bundle 映射。运行时 API 按实例名标签定位服务，并在选定项目内解析当前容器。映射缺失或匹配不唯一时抛出异常。连接使用该实例的 DSH 认证，诊断只返回操作状态和脱敏原因。运行时 API 与 Web Plugin Manager 使用同一套管理接口，没有第二份插件启停状态。

Bundle 启停结果需要检查当前进程的实际状态。尤其是装配到 `resident` preset 的工具，验收要用同一活动会话确认停用前后工具都随 Bundle 状态变更。如果固定版本只能在新会话应用某类变更，API 返回 failed，并在 detail 说明变更仅适用于新会话。已有会话的工具状态无法确认时，等待结束后返回 timeout。

现场启停保存于实例 Profile。再次启动或用同一持久卷重建容器时复用该状态。拓扑中的 `bundles=` 继续作为首次部署声明，现有 Profile 的声明更新由操作者显式执行。

### 在线安装与移除

首版稳定契约包含查询、启用和停用。在线安装与移除的候选接口分别为 `agent.plugins.add(source, *, wait=True, timeout=30, check=True)` 和 `agent.plugins.remove(name, *, wait=True, timeout=30, check=True)`。首个支持的安装来源是容器内可访问的原生 DSH Bundle 目录。待固定 DSH 版本验证它们能通过运行时管理接口完成包变更，并区分「已安装」与「已生效」后，再纳入稳定 API。

## 首版验收

使用双 Agent 拓扑验证两个实例都有默认能力，只有 Alice 暴露 Chat，两者都能调用 Cloud，并分别保存 Soul 状态。随后用 Python API 在同一个 Alice 会话中停用 Chat，验证工具从清单消失且原调用被拒绝。重新启用后执行一次真实工具调用，核对 DSH 进程 PID 和会话 ID 均未变化。最后用同一个持久卷重建容器，验证插件启停状态、会话与 Soul 状态能够恢复。

## API 设计参考

SEED 是部署 API 的主要参考。服务使用它的 Service、Server、Binding 和编译流程。运行时实例定位借鉴 SEED 的 ComposeRuntimeTest，它使用生成的 ASN 和节点名标签查找服务。这里扩展的是运行中的 DSH 管理操作。 [SEED Service 与 Server](https://github.com/Z-Vanadium/seed-emulator/blob/7c42ab9c5f475a9faced749768efe50bc407cc2a/seedemu/core/Service.py) · [SEED Compose 运行时工具](https://github.com/Z-Vanadium/seed-emulator/blob/7c42ab9c5f475a9faced749768efe50bc407cc2a/seedemu/testing/runtime.py)

运行时按名称获取实例、在实例下管理插件的写法可参考 Docker SDK 的对象和集合接口，以及 pluggy 的具名插件管理。默认同步等待、按需提前返回的调用方式可参考 Ansible Runner 的 Python 接口。 [Docker SDK](https://docker-py.readthedocs.io/en/stable/containers.html) · [pluggy](https://pluggy.readthedocs.io/en/stable/api_reference.html) · [Ansible Runner](https://docs.ansible.com/projects/runner/en/latest/python_interface/)
