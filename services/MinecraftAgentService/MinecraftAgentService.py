"""Extend AgentService with a local Minecraft bridge and experiment hooks."""

import json
from pathlib import Path
import shlex

from seedemu.core import BaseSystem
from services.AgentService import AgentService, ToolPackage
from bundles.MinecraftBundle import MinecraftBundle


# 当前安装包用于 AMD64；升级时同时更新官方版本与 SHA-256。
NODE_VERSION = '22.23.5'
NODE_SHA256 = 'c54118104acc524633b5abe106bbf44a53126ec8b4e5fa105cb92b5d7de8a1a1'


def _replace_once(source, original, replacement):
    """Fail explicitly when an upstream integration point changes."""
    if source.count(original) != 1:
        raise ValueError('Built-in framework changed; review Minecraft integration: '
                         + original.strip())
    return source.replace(original, replacement, 1)


def _extend_framework(source, notifications):
    """Apply Minecraft behavior to the generated copy of the LangChain entrypoint."""
    # 游戏活动允许较短休息；公共 AgentService 仍保留上游的 30 秒下限。
    source = _replace_once(source,
                           "number('AGENT_DEFAULT_REST_SECONDS', 120, 30, 1800)",
                           "number('AGENT_DEFAULT_REST_SECONDS', 120, 2, 1800)")
    replacements = (
        ('class ConversationState(AgentState):\n',
         'class ConversationState(AgentState):\n    environment_observation: dict\n'),
        ('    messages: list\n    cycle: int\n',
         '    messages: list\n    environment_observation: dict\n    cycle: int\n'),
        ('    middleware.append(model_observation)\n',
         '    middleware.append(model_observation)\n'
         '    from minecraft_notifications import make_middleware\n'
         '    middleware.append(make_middleware(context))\n'),
    )
    if notifications:
        for original, replacement in replacements:
            source = _replace_once(source, original, replacement)
    return source


class MinecraftAgentService(AgentService):
    """Install Minecraft agents; the supplied supervisor owns process startup.

    ``supervisor`` is a Python script that starts the bridge and ``agentctl run``.
    ``notifications`` optionally supplies a LangChain ``make_middleware(context)``
    factory. Experiment-specific environment mounts and policies stay with the
    caller. Like AgentService, this occupies the AgentService layer in an emulator.
    """

    def __init__(self, tools=(), environment_file=None, *, supervisor, notifications=None):
        self._supervisor = self._script(supervisor, 'supervisor')
        self._notifications = (self._script(notifications, 'notifications')
                               if notifications is not None else None)
        super().__init__(tools=tools, environment_file=environment_file)
        self.addToolPackage(ToolPackage(
            **MinecraftBundle.getAgentTools(),
            configuration={'local': {'bridge_url': 'http://127.0.0.1:8765'}},
        ))

    @staticmethod
    def _script(path, name):
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError(f'{name} script not found: {path}')
        return path

    def _doConfigure(self, node, server):
        super()._doConfigure(node, server)
        if server is not self.clock:
            if server._framework != 'langchain':
                raise ValueError('MinecraftAgentService currently requires the langchain framework')
            # 由 SEED 的系统配置选择基础镜像，不要求实验自行注册或覆盖镜像。
            node.setBaseSystem(BaseSystem.SEEDEMU_BASE)

    def _doInstall(self, node, server):
        first = len(node.getStartCommands())
        super()._doInstall(node, server)
        if server is self.clock:
            return
        config = next(json.loads(file.get()[1]) for file in node.getFiles()
                      if file.get()[0] == '/etc/emuvista-agent/config.json')
        entrypoint = config['framework']['entrypoint']
        files = {file.get()[0]: file.get()[1] for file in node.getFiles()}
        node.setFile(entrypoint, _extend_framework(files[entrypoint], self._notifications is not None))
        self._extend_runtime(node)
        if self._notifications is not None:
            node.importFile(str(self._notifications), '/opt/emuvista-agent/minecraft_notifications.py')
        bridge = MinecraftBundle.getAgentBridge()
        for path in bridge.rglob('*'):
            if path.is_file() and not {'node_modules', '__pycache__'} & set(path.parts):
                node.importFile(str(path), '/opt/minecraft-bridge/' + path.relative_to(bridge).as_posix())
        node.importFile(str(self._supervisor), '/opt/minecraft-agent/start.py')
        node.addSoftware('util-linux curl ca-certificates tar gzip libstdc++6')
        # Python 由父类安装；bridge 需要 Node.js >= 22，随官方安装包一起安装 npm。
        archive = f'node-v{NODE_VERSION}-linux-x64.tar.gz'
        node.addBuildCommand(
            'test "$(dpkg --print-architecture)" = amd64 '
            f'&& curl -fsSL --retry 3 https://nodejs.org/dist/v{NODE_VERSION}/{archive} '
            f'-o /tmp/{archive} '
            f'&& echo "{NODE_SHA256}  /tmp/{archive}" | sha256sum -c - '
            f'&& tar -xzf /tmp/{archive} -C /usr/local --strip-components=1 --no-same-owner '
            f'&& rm /tmp/{archive} '
            f'&& test "$(node --version)" = "v{NODE_VERSION}" && npm --version')
        node.addBuildCommandAtEnd('cd /opt/minecraft-bridge && npm ci --omit=dev && npm cache clean --force')
        # 仅替换父类本次添加的启动命令，保留 SEED 路由和调用者已有的启动设置。
        del node.getStartCommands()[first:]
        node.appendStartCommand(
            'env PYTHONPATH=/opt/emuvista-agent PYTHONDONTWRITEBYTECODE=1 '
            + shlex.quote('MC_AGENT_NAME=' + config['identity'])
            + ' python3 -u /opt/minecraft-agent/start.py '
            '> /var/log/minecraft-agent-supervisor.log 2>&1', fork=True)

    @staticmethod
    def _extend_runtime(node):
        """Keep Minecraft tool diagnostics out of the shared AgentService sources."""
        root = '/opt/emuvista-agent/'
        node.importFile(str(Path(__file__).parent / 'runtime/validation.py'),
                        root + 'minecraft_validation.py')
        imports = node.getImportedFiles()
        runtime_path = root + 'emuvista_agent/runtime.py'
        events_path = root + 'emuvista_agent/events.py'
        runtime = Path(imports[runtime_path]).read_text()
        runtime = _replace_once(runtime, 'from .clock import ClockClient\n',
                                'from .clock import ClockClient\n'
                                'from minecraft_validation import validate as validate_minecraft\n')
        runtime = _replace_once(runtime, "        validate(arguments, definition['input_schema'])\n",
                                "        validate_minecraft(arguments, definition['input_schema'])\n")
        runtime = _replace_once(
            runtime,
            "        self.context.emit('tool_finished', tool=name, call_id=call_id, status='success',\n",
            "        failed = isinstance(result, dict) and (bool(result.get('error')) or result.get('status') == 'failed')\n"
            "        self.context.emit('tool_finished', tool=name, call_id=call_id, status='error' if failed else 'success',\n")
        events = _replace_once(Path(imports[events_path]).read_text(),
                                "'reachable', 'ready', 'status', 'agent', 'hostname')",
                                "'reachable', 'ready', 'status', 'agent', 'hostname', 'error')")
        # 编译器在 setFile 内容之后复制 importFile；移除原导入，避免扩展被覆盖。
        del imports[runtime_path]
        del imports[events_path]
        node.setFile(runtime_path, runtime)
        node.setFile(events_path, events)
