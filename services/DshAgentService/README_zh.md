# DshAgentService

DshAgentService 用于在 SEED Emulator 的容器中部署 DeepSeek Harness（DSH）。你可以为每个 Agent 选择不同的插件组合，并通过 Python 脚本启停运行中实例的 Bundle。

安装 SEED Emulator、Python 和 Docker Compose，并在构建拓扑前构建共享 DSH 运行时镜像。 [共享运行时镜像说明](../../docker-images/deepseek-harness/README.md)

## 常用 API

| 调用 | 用途 |
| --- | --- |
| `DshAgentService()` | 创建可加入 SEED 拓扑的服务层。 |
| `agents.install(name, *, bundles=(), config=None)` | 声明一个 Agent。可选参数分别指定 Bundle 列表和实例配置文件。 |
| `DshAgentRuntime.from_compose(compose_file, *, project=None)` | 连接已部署的 Compose 项目。 |
| `runtime.agent(name)` | 按部署时声明的名称选择 Agent。 |
| `agent.plugins.list()` / `agent.plugins.get(name)` | 查看全部已安装 Bundle，或查询指定 Bundle 的状态。 |
| `agent.plugins.enable(name)` / `agent.plugins.disable(name)` | 启用或停用已安装的 Bundle，默认等待生效。 |

## 给 Agent 选择插件

在已有的 SEED 拓扑脚本中添加服务层，用 install() 声明 Agent 和它的 Bundle，再通过 Binding 绑定到拓扑中已经创建的主机。下面假设 AS150 中已有 alice 和 bob 两台主机。

```python
from pathlib import Path

from seedemu.core import Binding, Filter
from services.DshAgentService import DshAgentService

here = Path(__file__).resolve().parent
agents = DshAgentService()
agents.install("alice", bundles=[here / "bundles/chat-tools.yml"])
agents.install("bob")

emu.addLayer(agents)
emu.addBinding(Binding("alice", filter=Filter(asn=150, nodeName="^alice$")))
emu.addBinding(Binding("bob", filter=Filter(asn=150, nodeName="^bob$")))
```

Bundle 可以是原生 DSH Bundle 目录，也可以是 YAML 文件。单个插件可以用只包含一项的 Bundle 声明。例如，在拓扑脚本旁的 bundles/chat-tools.yml 中填写：

```yaml
name: chat-tools
plugins:
  - id: chat
    package: ../plugins/chat-client
    preset: resident
    config:
      endpoint: ws://chat.example.test:6060
```

上例假设插件包位于拓扑脚本旁的 plugins/chat-client 目录。将 package 和 endpoint 改为实际的插件路径及服务地址。preset: resident 将插件交给默认 Agent；省略该字段时由 DSH Host 加载。也可以通过 install() 的 config 参数传入实例 YAML，例如单独设置某个 Agent 的 Chat 用户名。

声明完成后，使用 SEED 的 render() 和 compile() 生成部署文件，再通过 Docker Compose 构建并启动容器。DSH 运行时由共享镜像提供。默认在容器内执行 dshagent web 手动启动 DSH Web，也可在实例 YAML 中设置 profile.startup: auto。模型凭据在运行时配置。

## 从 Python 热启停 Bundle

DSH Web 启动后，在单独的 Python 脚本中引用生成的 Compose 文件，并使用 install() 时指定的实例名：

```python
from pathlib import Path

from services.DshAgentService import DshAgentRuntime

here = Path(__file__).resolve().parent
runtime = DshAgentRuntime.from_compose(here / "output/docker-compose.yml")
alice = runtime.agent("alice")

for bundle in alice.plugins.list():
    print(bundle.name, bundle.enabled, bundle.status)

alice.plugins.disable("chat-tools")
alice.plugins.enable("chat-tools")
print(alice.plugins.get("chat-tools").status)
```

如果启动时指定了 Compose 项目名，请给 from_compose() 传入同一个 project 值。启停默认等待变更生效，失败时会报告原因。使用同一份持久化状态目录重新启动实例，可保留现场的插件启停选择。
