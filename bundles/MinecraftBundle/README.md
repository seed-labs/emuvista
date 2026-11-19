# MinecraftBundle

Runs an `itzg/minecraft-server` image on a native SEED network. The experiment
supplies the image, Minecraft environment, resolver, host port and world volume.
The Bundle owns the startup wrapper, routing, healthcheck and volume registration.
It has no dependency on E16 Minecraft 伐木交易实验.

```python
from bundles.MinecraftBundle import MinecraftBundle

minecraft = MinecraftBundle(
    emu, image='itzg/minecraft-server:java25',
    environment={'EULA': 'TRUE', 'TYPE': 'VANILLA', 'VERSION': '26.1',
                 'MEMORY': '4G', 'ONLINE_MODE': 'FALSE'},
    resolver='10.150.0.54', host_port=25565, volume='minecraft-data',
)
emu.render()
minecraft.addInternalNetwork('170', 'net0', ['10.170.0.10'], '10.170.0.254')
minecraft.registerVolumes(compiler)
compiler.addContainerBundle(minecraft)
emu.compile(compiler, 'output', override=True)
```

The topology must already contain AS170 and its router. Register networks after
rendering, as required by the native ContainerBundle API. `host_port=None`
disables host port forwarding. `volume` is an explicit Docker volume name;
choose distinct names for independent worlds. The caller owns EULA acceptance
and server version selection. The image must provide `/start` and its native
Minecraft healthcheck.

## Agent 工具

`MinecraftBundle.getAgentTools()` 返回 `ToolPackage` 所需的 name/source，
源码位于 `tools/`；`getAgentBridge()` 返回 `bridge/` 路径，供 agent 镜像安装
持久 Mineflayer bridge（运行 `npm ci --omit=dev` 后启动 `server.js`）。
Python handler 通过 `tool_config.minecraft.local.bridge_url` 访问 bridge。
`tools/tools.json` 是完整工具目录，包含 32 个工具的描述、参数和 handler，覆盖观察、聊天、寻路、战斗、制作、容器、烧炼、挖掘、读取游戏时间及睡眠等。
具体 agent 的工具权限由调用方的 `setTools([...])` 显式选择，不通过删减公共 manifest 限制。
Bundle 服务端本身不会自动安装或启动 agent bridge；E16 Minecraft 伐木交易实验 的 `experiment.py` 负责集成。

### 入口与寻路

`observe.navigation_landmarks` 独立返回 32 格内的床、告示牌、门、栅栏门、楼梯，
每类最多 8 个，不占用普通方块的 64 个名额；这是客户端已加载数据，不保证可达。
`find_blocks` 支持 `door`、`gate`、`stairs` 类别，并返回开关、朝向等方块属性。
`open_door` 自动靠近木门/栅栏门再交互，不自动穿门；已经打开时不重复切换，
铁门返回需要红石控制。新开门需收到服务器方块更新并确认 `open=true`；
无法确认时返回失败，应先观察再重试。移动失败会附带位置和附近关键方块。
E16 Minecraft 伐木交易实验 提示 agent 优先经过入口和楼梯，等待正在执行的动作，失败后更换中间目标。
保留 pathfinder 默认设置（允许挖掘，不启用实验性的自动开门），因此寻路仍可能改变地形。
以上能力需重新生成、构建后生效；单元测试不代表实际地图通行已验证。

### 冷启动网络就绪

E16 Minecraft 伐木交易实验 设置 `MinecraftBundle(startup_probe_url=...)`，在启动 `/start` 前通过 HTTPS
检查 Mojang 版本清单是否可访问。失败每 5 秒重试，整个等待最多 180 秒；
超时明确报错退出，不无限重启。普通 `depends_on: service_started` 不能证明 BGP 已收敛。
该检查使用容器实际 DNS/出口，只证明探测地址可达，不保证后续所有下载成功。
不配置 `startup_probe_url` 的其他示例保持原启动行为。
