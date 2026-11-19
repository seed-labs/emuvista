# E16：Minecraft 伐木交易实验

本实验包含 Alice、Bob、Carol 三个 agent、Mastodon 和独立的 Minecraft Java 26.1 服务端。
Alice、Bob 白天砍树收集原木，晚上把原木存入自己的箱子、发一条 Mastodon 帖子，再回房睡觉，次日继续。
Carol 不砍树，负责从 Alice、Bob 已确认归属的箱子中取出原木。
Alice 不允许合成；Bob 擅长制作工具，可以自愿合成并装备斧头；
网络恢复使用 SEED 的 B02 mini Internet with DNS；Minecraft 配置保留在 E16 入口，不依赖其他实验入口。
继续复用仓库公共的 AgentService、MastodonBundle 和 E99 活动页面资源。

Minecraft 使用 `itzg/minecraft-server:java25`，`TYPE=VANILLA`、`VERSION=26.1`。
服务器配置直接位于 `experiment.py`，底层实现位于 `bundles/MinecraftBundle`；Java 堆默认 2G。
E16 单独指定原有的 `output_minecraft-data` 存档卷。
镜像标签 java25 会更新；需要严格复现实验时，将镜像固定为经过验证的 digest。
首次启动需要联网下载服务端。此配置不预装 Fabric、Mods，也不自动迁移旧世界。
参考：[镜像文档](https://docker-minecraft-server.readthedocs.io/en/latest/)、
[版本选择](https://docker-minecraft-server.readthedocs.io/en/latest/versions/minecraft/)、
[健康检查](https://docker-minecraft-server.readthedocs.io/en/latest/misc/healthcheck/)。


## SeedEmu 网络

E16 使用 `examples.internet.B02_mini_internet_with_dns` 的完整拓扑，
保留 IX、路由服务器、中转/边缘 AS、eBGP、iBGP、OSPF 和 DNS 层级。
另外创建 AS99999 的 RealWorldRouter，接入 IX100 并与 AS3 建立对等关系，提供外网出口。

| 服务 | ASN | 地址 |
| --- | --- | --- |
| Alice、Bob、Carol | 171 | 10.171.0.80–82 |
| AgentService 时钟 | 171 | 10.171.0.79 |
| Minecraft | 170 | 10.170.0.10 |
| Mastodon | 161 | 10.161.0.10 |
| Payment（14 个组件） | 150 | 10.150.0.10–23 |
| 递归 DNS | 153 | 10.153.0.53 |

`minecraft.com`、`mastodon.com`、`payment.com` 由模拟 DNS 解析，Minecraft 下载使用 Docker DNS。
Internet Map 保留：拓扑页 8080、流量观察 8081、地理页 8082。
使用 AgentService 内置框架与共享时钟，Minecraft 通知由实验中间件提供。
监控读取生成的 `agents.json`，对应原生服务名 `hnode_171_alice` 等。

从旧版普通 Compose 部署迁移时，先在旧 output 中运行 `docker compose down`（不要加 `-v`），
再重新生成、构建和启动。如果 output 已重新生成，本次迁移保存了旧 Compose 配置，
可在 E16 目录执行 `docker compose --project-directory output -f .runtime/compose-before-seed.yml down`。
Minecraft、Mastodon、Agent 使用原 `output_*` 实际卷名。
旧 `.env` 的 `MC_HOST=minecraft` 会在启动时映射到
`minecraft.com`；无需改动 LLM 凭据。

## 配置和启动

以下命令在 emuvista 仓库根目录执行。首次没有 `.env` 时，生成器会自动复制 `.env.example`。
本地已有 `.env` 时保留其 LLM、agent 配置，不要覆盖：

```bash
.venv/bin/python experiments/E16_minecraft_logging_trade/experiment.py
```

编辑 `experiments/E16_minecraft_logging_trade/.env`，填写模型配置，内部服务器地址保持：

```dotenv
MC_HOST=minecraft.com
MC_PORT=25565
MC_AUTH=offline
LLM_API_KEY=你的密钥
LLM_BASE_URL=你的模型接口地址
LLM_MODEL=你的模型名称
```

Compose 项目名为 `output`；同一 Docker 主机上的其他实验应使用不同项目名，避免容器和持久卷冲突。
agent 通过模拟 DNS 解析并连接 `minecraft.com:25565`，等待 Minecraft 和 Mastodon 健康后启动。
跨 AS 流量经过模拟路由，外部流量再经过 NAT 出口，所有网络由 `emu.render()` / `emu.compile()` 生成。
无需在 PCL 中“对局域网开放”，退出游戏客户端不会关闭服务器。

服务配置包含 `EULA=TRUE`，启动前请阅读并同意 [Minecraft EULA](https://www.minecraft.net/eula)。
默认 `ONLINE_MODE=FALSE` 对应离线实验机器人，端口只应在受控实验网络使用。

```bash
cd experiments/E16_minecraft_logging_trade/output
docker compose build
docker compose up -d --remove-orphans
docker compose logs -f minecraft hnode_171_alice hnode_171_bob mastodon
```

PCL 使用 **Java 26.1** 客户端，在多人游戏中连接 `Docker宿主机IP:25565`；
若客户端与 Docker 在同一台机器，可使用 `localhost:25565`。
Minecraft 宿主机端口为 25565，Mastodon 保持 18443；启动前须确保端口未被其他实验占用。
需要并行运行时调整生成器中的端口映射；agent 的内部 `MC_PORT` 仍为 25565。

世界、服务器配置及玩家数据保存在 `output_minecraft-data` 卷，普通 `docker compose down`
和重新生成 output 不会删除世界；`docker compose down -v` 会删除包括世界在内的实验持久卷。
重新生成只替换构建文件，不要将唯一存档或手工配置放进 output 构建目录。
服务器管理可执行 `docker compose exec minecraft rcon-cli`。

修改源码后重新生成，然后 `docker compose up -d --build`。
`.env` 只读挂载到 agent，不复制到镜像；修改后 `docker compose restart hnode_171_alice hnode_171_bob`。
未填写模型密钥或模型名时只启动机器人；填写后等待连接 Minecraft 再启动 LLM 循环。
`AGENT_MAX_CYCLES=0` 表示持续运行；正数限制本次启动的活动次数。
`AGENT_DEFAULT_REST_SECONDS=2` 控制每轮结束后的默认休息间隔（2 秒）；日志位于 `/home/emuvista-agent/agent.log`。
旧的 `AGENT_ROUNDS`、`AGENT_INTERVAL_SECONDS` 和 `AGENT_READY_TIMEOUT_SECONDS` 不再使用。

## Payment 服务（参考 H20）

E16 复用 `PaymentBundle`，在 render 后接入 AS150，内部地址为
`http://payment.com`，宿主机访问 `http://localhost:8443/login-mail`。
首次构建前，在 emuvista 根目录构建公共 payment 镜像：

```bash
docker compose -f docker_images/payment/compose.yml build
.venv/bin/python experiments/E16_minecraft_logging_trade/experiment.py
cd experiments/E16_minecraft_logging_trade/output
docker compose build
docker compose up -d
```

`payment-groups.json` 配置单一 SEED 社区，货币为 USD：
Alice（`alice@mail.com`）和 Bob（`bob@mail.com`）初始余额为 0 USD；
Carol（`carol@mail.com`）初始余额为 1000 USD。密码均为 `payment-demo`。
管理员为 `admin@payment.com` / `PaymentAdmin123!`。
三个 agent 均拥有 PaymentBundle 的 `payment.balance`、`payment.transfer` 和
`payment.receipt`。工具金额单位为美分，100 美分 = 1 USD。
Alice/Bob 白天砍树，晚上存箱、发帖、睡觉。Carol 白天收木头，晚上睡在告示牌标识的自己的床上，不砍树、不发帖；
任务价格为每根 1 USD。Carol 自己判断收款人、数量和金额，使用收款人邮箱转账。
同一笔付款使用相同 UUID，结果不明时可以查询回执。

支付数据库、账本和初始化记录保存在 `.runtime/payment-usd-state/`，独立于 output。
重新生成会复用状态，不重置余额。修改初始社区配置后，需要在
`experiment.py` 中指定新的 `PAYMENT_STATE` 目录，或停止支付服务后清空该支付状态目录。
木材交易场景已改用新目录，旧的 `.runtime/payment-state/` 已按要求清除。
运行中的部署重新生成前应先停止容器。`payment-initialize` 正常完成初始化后退出；
可用 `docker compose logs payment-initialize` 查看结果。

## 从本地世界初始化

在 `experiment.py` 顶部通过 `WORLD_SOURCE` 硬编码要导入的存档目录。
当前值为 `HERE / 'world'`，对应当前已放入的存档。
如果直接复制整个存档文件夹，改为：

```python
WORLD_SOURCE = HERE / 'world' / '我的世界'
```

对应 `world/我的世界/level.dat`。只读取指定目录，不自动查找；
缺少 `level.dat` 时会在覆盖 output 之前报错。
设为 `None` 则不导入存档，数据卷无世界时使用 E16 中的服务器配置生成。

然后运行 `../../.venv/bin/python experiment.py`，在 `output` 中执行
`docker compose up -d --no-build minecraft`（模拟网络需已启动）。
指定目录只读挂载，通过 `WORLD=/world-template` 和 `FORCE_WORLD_COPY=false`
在服务器首次启动时复制到数据卷。已有世界不会覆盖，原始存档不会修改。
改变 `WORLD_SOURCE` 后需重新生成配置。存档文件已从 Git 忽略。

如果数据卷已有旧世界，需要先停止 Minecraft 和全部 agent，然后删除旧世界，
才会在下一次启动导入模板。以下命令在 `output` 中执行，会清除旧世界且不备份：

```bash
docker compose stop minecraft hnode_171_alice hnode_171_bob
docker compose run --rm --no-deps --entrypoint sh minecraft -c 'rm -rf -- /data/world'
docker compose up -d --no-build minecraft
```

此处 `/data/world` 对应默认 `LEVEL=world`；自定义 LEVEL 时需使用对应目录。
参考：[镜像世界导入文档](https://docker-minecraft-server.readthedocs.io/en/latest/misc/world-data/)。

## 住宅区域冒险模式保护

E16 已设置 `ENABLE_COMMAND_BLOCK=true`，允许执行世界中保存的命令方块。
此开关本身不会创建保护区；需要在单人世界中放好命令方块后导入，或在运行中的世界中配置。

保护区为 X=-14～6、Z=-30～10，Y=-64～319，覆盖所有楼层。
进入区域的普通生存模式玩家切为冒险模式，离开后恢复生存模式。
冒险模式限制普通挖掘和放置，但仍可开门、存取箱子、睡觉和使用已有工作台。
房屋应与区域边界留出至少 6 格距离，避免玩家从范围外挖到房屋；此方案不防爆炸等其他破坏方式。

在单人世界开启作弊后，聊天栏执行：

```mcfunction
/gamemode creative
/give @s minecraft:repeating_command_block 2
/tag @s add region_bypass
```

并排放置两个循环命令方块，右键配置为“循环、无条件、保持开启”，分别填入以下命令（不带开头的 `/`）：

```mcfunction
execute as @a[tag=!region_bypass,gamemode=survival] if entity @s[x=-14,y=-64,z=-30,dx=20,dy=383,dz=40] run gamemode adventure @s
```

```mcfunction
execute as @a[tag=!region_bypass,gamemode=adventure] unless entity @s[x=-14,y=-64,z=-30,dx=20,dy=383,dz=40] run gamemode survival @s
```

这两个方块独立运行，不需要红石或箭头连接。分别站到每个命令方块上，在聊天栏执行
`/forceload add ~ ~`，确保所在区块持续加载；若已加载则无需重复添加。
保存退出后复制整个世界目录，保留命令方块及强制加载设置。

规则作用于所有未带 `region_bypass` 标签的生存/冒险模式玩家，不限 Alice、Bob。
原版选择器不直接识别 OP；管理员需手动执行 `/tag 玩家名 add region_bypass` 获得豁免，
取消豁免使用 `/tag 玩家名 remove region_bypass`。标签不会随 `/op`、`/deop` 自动同步。
测试时可先移除自己的豁免并切为生存模式，走入/走出范围验证模式切换，再恢复豁免。

重新生成 E16 后，在 `output` 下执行以下命令应用命令方块开关，保留现有数据卷：

```bash
docker compose up -d --no-deps --no-build --force-recreate minecraft
```

这只应用容器配置，不会把新世界模板覆盖到已有 `/data/world`；更新模板存档需按前文的世界导入步骤操作。

## 昼夜任务与工具权限

Minecraft 工具由 `bundles/MinecraftBundle/tools/` 提供，Mineflayer bridge 位于
`bundles/MinecraftBundle/bridge/`。E16 通过 `MinecraftBundle.getAgentTools()` 和
`getAgentBridge()` 加载，不再保留实验目录中的工具副本。

共享工具包保留完整清单，E16 通过 `experiment.py` 的 `agent_tools(name)` 分配权限：

- 三人都可使用 `minecraft.chat` 交流，也都有观察、搜索物品与方块、检查告示牌、
  移动、开门、查询动作、停止、查询时间、睡觉、装备、开箱、检查箱子、
  关箱和 `payment.balance` 工具。三人睡前都需读取姓名告示牌，确认目标床属于自己。
- Alice、Bob 另有 `dig_blocks`、`deposit_item` 和 `socialmedia.post/profile/posts`；晚上存木材、发帖、睡觉。
- Alice、Bob 均有 `payment.transfer`、`payment.receipt` 和 `withdraw_item`，都能转账和取货。
  两人的工具权限唯一区别是 Bob 额外拥有 `get_recipes`、`craft`、`place_block`，用于合成和放置工作台、制作工具。
- Alice 没有合成权限，可以购买 Bob 制作的斧头。
  她与 Bob 通过 chat 商定斧头种类、数量、总价和交货箱，向 `bob@mail.com` 付款，
  并发送付款 UUID；Bob 核验 committed 回执后，将斧头放入自己的箱子并通知 Alice 取货。
  Alice 只可提取约定购买的斧头，核对背包后装备。价格由双方商议，资金不足时可以暂缓购买。
- Carol 另有 `payment.transfer`、`payment.receipt` 和 `withdraw_item`，没有挖掘、合成、
  放置或社交发帖权限。她读取告示牌确认 Alice/Bob 的箱子，只收购 `_log` 原木，
  不取用于斧头交易的工具或其他财物。取货后核对箱子和背包，按实际数量付款。
  箱子为空时稍后再来；背包满时停止收取。原木只保存在背包，Carol 没有 `deposit_item`
  权限，不能把收购的木材存回供应商箱子或任何其他箱子。
  她晚上睡自己的床；世界中应有带 Carol 姓名告示牌的床。
  `.env` 需要 `MC_CAROL_USERNAME=Carol`。
- 箱子取货范围和归属由提示词约束，通用 `withdraw_item` 工具本身不按所有者过滤。
- 白天只采集自然树木，用实际原木名称（如 `oak_log`）搜索；`log` 不是搜索类别。
  挖掉方块不代表拾取成功，需要靠近掉落物并检查背包。
- 晚上按“自己的箱子存原木 → 一条当日社交帖子 → 自己房间睡觉”执行，次日继续。
  箱子归属需由名字告示牌确认；存放后核对背包和箱内物品。帖子只报告真实结果，
  同一篇重试使用相同 `idempotency_key`，结果不确定时先查自己的帖子。
- Mastodon 工具使用各自 `/run/socialmedia/credentials.json`，无需修改 Mastodon 服务配置。

- `observe.nearby_blocks` 返回 32 格内最多 256 个最近的非空气方块；实体仍最多 20 个。方块列表不是完整地图。
- `find_blocks(name="bed")` 搜索所有床颜色；`name="sign"` 搜索所有告示牌类型。
  仍支持具体方块名，搜索已加载区域，半径最多 32 格、最多 20 个结果。
- `inspect_block` 读取告示牌文字和床属性，agent 根据自己的名字识别床，不预设坐标。
- E16 在 `start.py` 中固定 `MC_PATHFINDER_CAN_DIG=false`，禁止寻路自动挖门、墙或其他方块（包括 `open_door` 靠近门时的寻路）。
  先靠近入口，调用 `open_door`，再 `move_to` 到门内路径点。没有可用入口且确需清障时，先靠近方块再显式调用 `dig_blocks`；不要破坏门、床或名字告示牌。
  共享 bridge 默认仍保留原有寻路策略，E16 单独启用此限制。
- 上楼使用已观察到的楼梯入口、转角和平台路径点，`move_to(arrival_radius=0)` 要求到达指定脚部方块；默认半径为 1。楼梯方块也可能是屋檐装饰，需确认连续可走路线。移动完成会检查客户端实际位置（含高度），不会仅凭寻路 promise 返回就报告到达。
- `get_time` 立即读取游戏时间，返回 tick 和换算的 `HH:MM`，不等待、不修改时间。
  根据当前游戏时间切换采集和晚间流程；等待天亮时使用内置框架的活动间休息，并重新读取游戏时间。
- Bridge 根据服务器时间更新，每跨过一个游戏小时（1000 ticks）产生一条 `time` 通知，包含 `day`（从 0 开始）、`clock_24h`、`time_of_day` 和 `dimension`。首次收到时间只建立基线；时间冻结不重复通知，睡觉或命令跳时只通知最新时刻。
- 时间通知沿用 `/notifications`，在下一次模型调用前进入 agent 上下文，不会中断正在执行的动作，也不会额外启动模型轮次。
- 到床旁后调用 `sleep`，通过返回结果或 `observe.is_sleeping` 确认入睡。
  动作仍在运行时用 `action_status` 查询，不能把提交动作当作完成。

请在世界中为 Alice、Bob 分别准备有明确名字告示牌的箱子，为 Alice、Bob、Carol 分别准备
有姓名告示牌的卧室/床，并提供可到达的自然树木。
若告示牌不能明确对应箱子或床，agent 应继续核实归属。Bob 可自行制作工作台，也可使用现有工作台。
昼夜循环需要游戏正常推进时间；设置正数活动次数上限后，达到上限时 LLM 会停止，bridge 仍保持连接。
真实入睡是否成功受服务器规则、床占用、距离和附近怪物等实际条件影响。

重新生成后执行 `docker compose up -d --build --remove-orphans`，移除旧的
Dave、Eve 容器并应用新工具；不删除持久卷。
只做源码与生成检查不代表已在游戏中完成找床或入睡。

## 监控

E16 的 `monitor.py` 包含容器发现、日志采集、进程检测、事件解析和 Minecraft 状态接口，复用 E99 的活动页静态资源。
在 E16 目录、具有 Docker 访问权限的宿主机终端运行：

```bash
python monitor.py
```

打开 `http://localhost:8090`。可查看 Alice、Bob、Carol 三个 agent 的进程状态、轮次、工具调用、回复和错误。

新增游戏状态页：`http://localhost:8090/minecraft`，也可从活动面板的「Minecraft 状态」进入。
显示每位 agent 的生命值（Health）、饱食度（Hunger）、背包物品及数量、手持物品、
坐标、维度和当前游戏动作；同名物品堆叠合并计数。页面每 2 秒刷新。
数据由 monitor 通过容器内 bridge 的只读 `/observe` 接口采集，不依赖模型是否调用观察工具。
容器未运行、游戏断线或采集失败时会显示不可用状态；保留的旧数值标注为上次记录。

E16 的监控入口与后端统一保存在 `monitor.py`，页面位于 `dashboard/`；
E99 文件不作修改，仅复用其原活动页静态资源。更新后重启 E16 的 `monitor.py` 即可，
不需要重建 agent 镜像。monitor 需要当前用户具备 Docker 读取与 exec 权限。
可用 `--port` 更换端口。关闭 monitor 不会停止 agents。
此页面观察 LLM 进程；MC 连接状态通过 `minecraft.observe` 或 Compose 健康状态单独确认。

项目名由之前的 `e16-minecraft` 改为 `output`；旧项目的容器和卷不会自动迁移或删除。
同一 Docker 主机上，其他实验若也叫 `output`，会属于同一个 Compose 项目，不能作为独立 stack 同时部署。

### 实现边界

工具 manifest 与 Python handler 位于 `bundles/MinecraftBundle/tools/`；
HTTP 路由位于该 bundle 的 `bridge/tool_api.js`，连接与动作生命周期位于 `bridge/server.js`。
E16 使用 AgentService 内置 LangChain/LangGraph 框架；实验目录仅保留 bridge 启动、
角色/工具配置、Minecraft 通知中间件和监控。
修改工具后需重新生成、构建并重建 agent 容器。

### 入口与寻路

`observe.navigation_landmarks` 独立返回 32 格内的床、告示牌、门、栅栏门、楼梯，
每类最多 8 个，不占用普通方块的 256 个名额；这是客户端已加载数据，不保证可达。
`find_blocks` 支持 `door`、`gate`、`stairs` 类别，并返回开关、朝向等方块属性。
`open_door` 自动靠近木门/栅栏门再交互，不自动穿门；已经打开时不重复切换，
铁门返回需要红石控制。新开门需收到服务器方块更新并确认 `open=true`；
无法确认时返回失败，应先观察再重试。移动失败会附带位置和附近关键方块。
E16 提示 agent 优先经过入口和楼梯，等待正在执行的动作，失败后更换中间目标。
E16 使用 `mineflayer-pathfinder@2.4.5`，不再加载 Baritone。
保留 `MC_PATHFINDER_CAN_DIG=false`，并禁用自动垫高与搭桥；显式 `dig_blocks` 仍受游戏模式检查约束。
保留实际位置到达检查和 `arrival_radius` 参数。
以上能力需重新生成、构建后生效；单元测试不代表实际地图通行已验证。

### 冷启动网络就绪

E16 设置 `MinecraftBundle(startup_probe_url=...)`，在启动 `/start` 前通过 HTTPS
检查 Mojang 版本清单是否可访问。失败每 5 秒重试，整个等待最多 180 秒；
超时明确报错退出，不无限重启。普通 `depends_on: service_started` 不能证明 BGP 已收敛。
该检查使用容器实际 DNS/出口，只证明探测地址可达，不保证后续所有下载成功。
不配置 `startup_probe_url` 的其他示例保持原启动行为。

服务器默认设置在 `experiment.py` 中固定为 `MODE=survival`（生存）、
`DIFFICULTY=peaceful`（和平）。在 `OP_NAMES = ('seed',)` 中填写 OP 的游戏登录名；
例如 `OP_NAMES = ('seed', 'Alice')` 同时授权 seed 和 Alice，无需查询或填写 UUID。
名字区分大小写，应与实际游戏登录名一致（agent 标识 `alice` 不一定是游戏名 `Alice`）。
生成器按 Minecraft 离线规则自动计算 UUID，避免在线用户名解析。
`EXISTING_OPS_FILE=SYNCHRONIZE` 会在每次启动时将 OP 名单同步为配置的玩家，
清除旧的错误 UUID，也会移除未列入配置的手动 OP。此计算仅适用于 `ONLINE_MODE=FALSE`。
重新生成并重新创建 Minecraft 容器后应用，无需 build 或删除世界数据卷。

### Mastodon 启动文件打包

E16 在生成阶段将 `mastodon-config` 和 Mastodon 的启动包装脚本复制进
`application-images/mastodon/generated/`，并追加 Dockerfile `COPY` 指令。
运行镜像为 `e16-mastodon:local`，不再挂载这些 output 文件；持久数据卷、
agent 的 `.env` 和 Minecraft 世界模板挂载保持原方式。配置包含实验初始化账号，
该运行镜像仅供本地实验使用。

修改 Mastodon 配置后，重新生成 output，再执行：

```bash
docker compose build mastodon
docker compose up -d --no-build --no-deps --force-recreate mastodon
```

普通 `up` 不再强制构建 Mastodon；重新生成 output 不会改变旧容器中的脚本。
新配置需要 build 后重建容器才能生效，不删除数据卷。

E16 设置 `SPAWN_PROTECTION=0`：实验房屋位于世界出生点附近，允许非 OP 的 Alice/Bob 使用门和床。默认 OP 仍只有 `seed`。

### Native framework and Minecraft notifications

E16 uses `services/AgentService/frameworks/langchain/application.py` directly.
The framework owns the wake/act/rest loop, model-call limits, message history,
summary policy and SQLite checkpoints. Default summarization triggers at 40
messages and keeps 20 recent messages; the former E16 eight-round summary is removed.
Conversation and execution state persist in
`/home/emuvista-agent/state/langgraph.sqlite` on each agent's existing state volume.
Old E16 text logs and in-process summaries are not imported into checkpoints.

`notifications.py` supplies the optional `observation_middleware` factory configured
by E16. Before each model call it polls the existing Minecraft `/notifications`
feed, puts urgent events first, and adds observations plus their epoch/cursor to
the checkpointed graph state. Model failures retain these observations. Bridge
resets and buffer overflow are conveyed using `cursor_reset` and `truncated`.
Delivery logs mean the middleware prepared the state update, not that the model
has understood or acted on the notification. Notifications do not interrupt
ongoing actions or wake the resident during framework rest.

The framework ClockServer schedules activities. Minecraft time notifications and
`minecraft.get_time` determine in-game daytime; the two clocks are distinct.
The bridge supervisor still starts Mineflayer before `agentctl run`, which now
launches the built-in `/opt/emuvista-agent/framework/main.py`. Agents wait for the
ClockServer, Minecraft, Mastodon and payment gateway Compose health dependencies.

Offline integration checks (in an environment with the framework requirements):
`python -m unittest discover -s experiments/E16_minecraft_logging_trade -p test_native_framework.py`
