# MinecraftAgentService

`MinecraftAgentService` 继承公共 `AgentService`，在 SEED 主机上安装 Minecraft agent。
公共 `services/AgentService` 保持与 `seed-labs/emuvista` 的 `main` 一致，
本次同步基准为 `2825b79eb03494264a181a679d13520f89adf21a`。

```python
from services.AgentService import ToolPackage
from services.MinecraftAgentService import MinecraftAgentService

agents = MinecraftAgentService(
    tools=[social_tools, payment_tools],
    supervisor=HERE / 'start.py',
    notifications=HERE / 'notifications.py',  # 可选
)
agent = agents.install('alice').setPersona(person)
agent.setTools(['minecraft.observe', 'minecraft.chat'])
# 像 AgentService 一样绑定 agent 和 agents.clock，然后 emu.addLayer(agents)。
```

子类自动注册 `MinecraftBundle` 提供的工具，将本地 bridge 地址设为
`http://127.0.0.1:8765`。调用者通过 `setTools()` 控制各 agent 的授权工具。
人物、交易规则、世界配置、环境文件挂载和持久卷仍由实验定义。

安装时，子类为 agent 选择 `BaseSystem.SEEDEMU_BASE`，由 Docker 编译器映射到
`handsonsecurity/seedemu-base:2.0`。父类安装 Python、虚拟环境、框架与工具依赖，
子类安装官方 Node.js 22.23.5 和随包提供的 npm，验证固定 SHA-256 后执行 bridge 的
`npm ci --omit=dev`。当前支持 AMD64 和 LangChain；Node.js 版本及校验值在
`MinecraftAgentService.py` 中一起维护。

`supervisor` 是必需的 Python 启动脚本，安装到 `/opt/minecraft-agent/start.py`。
它负责读取实验环境、降权运行 bridge、等待连接、启动 `agentctl run` 并管理子进程。
启动时提供与配置身份一致的 `MC_AGENT_NAME`、`PYTHONPATH=/opt/emuvista-agent`，
日志位于 `/var/log/minecraft-agent-supervisor.log`。E16 的实现仍位于实验的 `start.py`。
若传入父类的 `environment_file`，文件仍挂载到 `/run/emuvista-agent.env`；
自定义 supervisor 必须自行加载所需环境，因为父类的启动命令已被替换。

`notifications` 是可选的 Python 模块，需提供 `make_middleware(context)`。
它安装到 `/opt/emuvista-agent/minecraft_notifications.py`，在每次模型调用前运行。
未提供时不添加通知状态和中间件，但仍安装 bridge、Minecraft 工具和启动脚本。

原来放在公共 AgentService 中的 Minecraft 定制只作用于生成的节点文件：

- 框架默认休息时间允许低至 2 秒；普通 AgentService 仍为上游的 30 秒下限。
- 工具参数错误包含字段路径、类型和范围，便于 agent 修正调用。
- 工具返回非空 `error` 或 `status='failed'` 时，完成事件标记为错误，并保留错误摘要。

这些扩展通过检查唯一匹配的源码位置应用；上游结构变化时明确报错，要求检查适配。
共享时钟保持父类安装方式，不安装 bridge，也不替换启动命令。
子类沿用 `AgentService` 层名称，同一个 emulator 中使用其中一个服务实例。
E99 继续直接使用公共 `AgentService`。Compose 构建依赖处理不属于该子类。
