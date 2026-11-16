# E16：Minecraft 见闻与 Mastodon 社交

本实验包含 Alice、Bob、Carol、Dave、Eve 五个 agent 容器和一个独立 Mastodon 实例；五位玩家连接宿主机上的 **Minecraft Java 26.1**。
容器使用 Node 22、Mineflayer 4.39.0、mineflayer-pathfinder 2.4.5，并通过 lockfile 固定 npm 依赖。
不启动 MC 服务器，不依赖 E15 或 H00。Mastodon 的部署生成由 `bundles/MastodonBundle/compose.py` 封装，E16 仅声明账号、端口、站点标题和令牌卷；镜像安装源码仍在 `docker_images/mastodon`。

复用 AgentService 的工具授权、安装和运行时；E16 使用独立的 LangChain adapter，提供基于实时观察的运行循环。
`experiment.py` 使用 detached Node 收集 AgentService 安装文件，生成项目名为 `output` 的 Docker Compose；
当前通过 Docker bridge 访问宿主机，游戏流量尚未经过 SEED 仿真路由。

## 配置和启动

以下命令在 emuvista 仓库根目录执行：

```bash
cp experiments/E16_minecraft/.env.example experiments/E16_minecraft/.env
chmod 600 experiments/E16_minecraft/.env
```

在 **26.1 Java 客户端**中打开世界，选择“对局域网开放”。将游戏显示的端口填入 `.env`：

```dotenv
MC_HOST=host.docker.internal
MC_PORT=这里填写游戏显示的数字端口
MC_ALICE_USERNAME=Alice
MC_BOB_USERNAME=Bob
MC_CAROL_USERNAME=Carol
MC_DAVE_USERNAME=Dave
MC_EVE_USERNAME=Eve
MC_AUTH=offline
LLM_API_KEY=你的密钥
LLM_BASE_URL=你的模型接口地址
LLM_MODEL=你的模型名称
```

`MC_PORT` 初始留空，必须填写后才能启动。再次开放局域网时端口可能改变。
`host.docker.internal` 指 Docker daemon 所在宿主机；若游戏在另一台电脑，填那台电脑的可达 IP。
宿主机需允许容器访问这个 TCP 端口，游戏不能只监听 127.0.0.1。
`offline` 用于允许离线玩家的局域网测试环境；若服务器要求正版验证，设置
`MC_AUTH=microsoft`，`MC_<NAME>_USERNAME` 使用各自账号标识（每人需要不同账号），并按容器日志提示完成登录。
此时实际游戏名来自账号，不保证叫 Alice。认证缓存保存在各自独立的持久卷中。每个 agent 必须显式设置自己的 `MC_<NAME>_USERNAME`，不再使用共享用户名或 Alice 专用回退配置。

```bash
.venv/bin/python experiments/E16_minecraft/experiment.py
cd experiments/E16_minecraft/output
docker compose build
docker compose up -d
docker compose logs -f alice bob carol dave eve mastodon
```

MC 版本在 bridge 中固定为 `26.1`。不要把它改成 26.3 而期待协议自动兼容。
生成器允许重复运行：重新生成五个 agent 和 Mastodon 配置与镜像构建目录和 `docker-compose.yml`，清除旧构建文件，
保留 `.env` 和 Docker 持久卷。不要在生成的构建目录中存放环境配置或手工文件。
修改代码后重新执行 `python experiment.py`，再在 output 中运行
`docker compose up -d --build` 应用更新。
`.env` 只读挂载，密钥不复制到镜像。修改 `.env` 后 `docker compose restart alice bob carol dave eve` 生效。

未填写 `LLM_API_KEY` 或 `LLM_MODEL` 时，容器仅运行对应的 MC 机器人，支持手动工具调用。
两者都填写后，启动器等待 MC 成功连接后启动 LLM 循环；等待超时则按实际离线状态启动，允许继续使用 Mastodon，bridge 继续重连。
`AGENT_ROUNDS` 控制执行轮数（默认 10）；轮数结束后机器人仍保持连接。
LLM 日志位于 `/home/emuvista-agent/agent.log`：

```bash
docker compose exec alice tail -f /home/emuvista-agent/agent.log
```

## 工具与检查

每个 agent 的 Mineflayer 在各自容器中持续运行，Python 工具通过容器内的 `127.0.0.1:8765` 调用它。
该接口不发布到宿主机，不会为每次工具调用重新登录。

| 工具 | 用途 |
| --- | --- |
| `observe`、`action_status` | 当前状态与动作结果 |
| `chat` | 发送聊天，接收使用自动通知 |
| `move_to`、`stop` | 寻路到目标与停止 |
| `find_blocks`、`inspect_block` | 按名称查找方块、检查坐标 |
| `equip`、`consume`、`drop_item` | 按物品名称装备、进食与丢弃 |
| `get_recipes`、`craft` | 按名称查看配方并合成 |
| `place_block`、`dig_blocks` | 放置、批量挖掘 |
| `attack`、`hunt_entity` | 跟随指定实体并攻击一次，或有次数和时间限制地持续追击 |
| `open_container`、`inspect_container`、`deposit_item`、`withdraw_item`、`close_container` | 储物容器与物品转移；关闭也适用于熔炉窗口 |
| `open_furnace`、`inspect_furnace` | 打开熔炉、高炉、烟熏炉，查看槽位、燃料与烧炼进度 |
| `put_furnace_input`、`put_furnace_fuel`、`take_furnace_item` | 放入原料、燃料，取出指定槽位的整堆物品 |
| `use_on_block`、`interact_entity` | 手持物品右键方块或实体，用于耕种、施肥、动物交互等 |
| `sleep`、`wake` | 尝试睡觉与起床；`observe.is_sleeping` 查看当前睡眠状态 |

以上均带 `minecraft.` 前缀，共 30 个工具。模型不再获得底层 `_call`、
`native_call` 或 `native_methods` 工具；monitor 直接显示具体封装工具名称。

### 基础生存流程

打猎由 agent 自己选择目标和武器：`observe → equip → attack/hunt_entity → action_status`。
`attack({"entity_id": 123, "timeout_seconds": 30})` 根据实体 ID 跟随同一目标，
位置距离不超过 2.5 格后攻击一次。`hunt_entity({"entity_id": 123, "timeout_seconds": 30, "max_attacks": 20})`
在 bridge 内重复调用同一个接近与攻击函数，不需要模型每挥击一次都调用工具。
两者使用原生 `GoalFollow` 动态寻路，不修改 pathfinder 默认移动规则，寻路可能挖掘或放置方块。
持续攻击之间至少间隔 1 秒；此间隔不保证每种武器都完成冷却，距离检查也不保证没有遮挡或命中。
超时范围 1～120 秒，持续攻击次数 1～100；目标或自身离起点超过 128 格时终止追击。

`stop` 可以取消这两类动作，结束后会清除寻路与事件监听。
`action_status` 保留攻击次数 `attacks_submitted`、当前阶段 `phase` 和结束原因 `end_reason`：
`attack_submitted`（单次攻击已提交）、`max_attacks`、`target_died`、`target_lost`、
`pursuit_limit`、`timeout`、`cancelled` 或错误状态。
达到攻击次数上限也会结束任务，但不代表击杀。`target_death_observed` 只表示收到目标死亡事件；
`target_hurt_events` 也不证明伤害来自该 agent。目标消失按丢失处理，不推断死亡。
工具不会自动收集掉落物，需自行接近掉落物并检查背包。

手动测试攻击时，可分别检查静止目标的单次攻击、移动目标的追赶、较小 `max_attacks` 限制、
追击过程中的 `stop` 与超时，以及目标离开加载范围时是否返回 `target_lost` 而非击杀成功。

采集仍使用 `find_blocks → move_to → equip → dig_blocks → observe`，确认实际拾取的物品；
合成使用 `get_recipes → craft`，需要工作台的配方先放置工作台并走近。
`get_recipes` 仅包含合成配方，目前没有烧炼配方查询；不能把查询不到合成配方理解为不能烧炼。

烧炼时先走近炉子，关闭其他窗口，再调用：

1. `open_furnace({"x": ..., "y": ..., "z": ...})`。
2. `put_furnace_input({"item": "raw_iron", "count": 1})`、`put_furnace_fuel({"item": "coal", "count": 1})`。
3. `inspect_furnace({"wait_seconds": 10})`：最多本地等待 10 秒，有任意产物即返回；已有产物时立即返回，不等待整批完成。
4. 确认 `output` 后，`take_furnace_item({"slot": "output"})` 取出当前整堆产物；`slot` 也支持 `input`、`fuel`，用于回收剩余物品。
5. 查看返回的炉子槽位和背包，再 `close_container({})`。关闭窗口不会取消服务器端烧炼。

输入数量限制为 1～64，容量、合法燃料和配方以原生 API 与服务器规则为准。
`progress_fraction`、`fuel_fraction` 以及秒数来自客户端窗口状态，未收到时为 `null`。
投料返回不代表烧炼成功；读到产物不代表已经取入背包。多人同时操作可能改变槽位。
动作返回 `running` 或 `pending=true` 时，先查询 `action_status`；失败后等 `pending=false` 并检查状态，再决定是否重试。

农作时可用 `use_on_block` 携带锄头右键泥土，再携带种子右键耕地顶面（`face="up"`），
施肥时携带骨粉右键作物。成熟后用现有挖掘工具收获，并检查掉落与背包。
`interact_entity` 使用 `observe` 返回的实体 ID，可携带食物右键动物。
两种交互工具省略 `item` 时会清空主手；不会自动走近，返回仅表示原生调用结束，
需要检查方块、实体与背包确认效果，不能自动宣称播种、繁殖或驯服成功。
实体交互不包含村民交易等专用 GUI 流程。睡觉调用返回不表示已经跳过夜晚。

工具实现遵循项目锁定的 [Mineflayer 4.39.0 API](https://github.com/PrismarineJS/mineflayer/blob/4.39.0/docs/api.md)，
熔炉状态与转移使用其 [原生炉子插件](https://github.com/PrismarineJS/mineflayer/blob/4.39.0/lib/plugins/furnace.js)。

手动验证时，先准备炉子、原料、燃料与空余背包，按上述顺序检查输入槽、燃料进度、产物槽及取出后的背包。
另检查空槽取出、原料不足、窗口已关闭时会报错；耕地与播种需要在游戏内确认方块变化。
新增工具修改的是源码，需在 E16 目录重新运行 `python3 experiment.py` 生成构建目录，再构建镜像并重建容器后生效：

```bash
cd output
docker compose up -d --build --no-deps --force-recreate alice bob carol dave eve
```

```bash
docker compose exec --user emuvista-agent alice agentctl list
docker compose exec --user emuvista-agent alice agentctl call minecraft.observe '{}'
```

`observe.connected=true` 才说明机器人已进入世界。Compose 生成成功、镜像构建成功或
进程启动都不代表已经连接 MC；LLM 是否成功运行还需查看 agent.log。

停止实验（保留日志和认证缓存）：

```bash
docker compose down
```

## Mastodon 与角色

Mastodon 内部地址为 `http://mastodon.e16.test:18443`，Docker 网络别名由 Compose 配置。
浏览器访问时在宿主机 hosts 中加入 `127.0.0.1 mastodon.e16.test`，然后打开
`http://mastodon.e16.test:18443`。默认实验账号如下：

| 角色 | 登录邮箱 | 密码 |
| --- | --- | --- |
| Alice | alice@example.com | alice123456 |
| Bob | bob@example.com | bob123456 |
| Carol | carol@example.com | carol123456 |
| Dave | dave@example.com | dave123456 |
| Eve | eve@example.com | eve123456 |
| 管理员 | admin@example.com | admin123456 |

两位 agent 均获得 `socialmedia.inbox/browse/read/post`，使用独立的只读令牌卷。
Mastodon 健康检查通过且两份令牌导出完成后，Compose 才启动 agents。
每位 agent 根据 MC 的实际观察探索，并在有值得分享的新经历时发帖；不要求每轮发帖。
角色要求区分真实观察、他人陈述和推测，不把客户端已知实体描述为视觉截图。
发帖成功以 `successful=true` 和返回的 `status.id` 为准。

## 监控

E16 的 monitor 只适配容器发现，复用 E99 的页面、日志采集、进程检测和事件解析。
在 E16 目录、具有 Docker 访问权限的宿主机终端运行：

```bash
python monitor.py
```

打开 `http://localhost:8090`。可查看 全部五个 agent 的进程状态、轮次、工具调用、回复和错误。

新增游戏状态页：`http://localhost:8090/minecraft`，也可从活动面板的「Minecraft 状态」进入。
显示每位 agent 的生命值（Health）、饱食度（Hunger）、背包物品及数量、手持物品、
坐标、维度和当前游戏动作；同名物品堆叠合并计数。页面每 2 秒刷新。
数据由 monitor 通过容器内 bridge 的只读 `/observe` 接口采集，不依赖模型是否调用观察工具。
容器未运行、游戏断线或采集失败时会显示不可用状态；保留的旧数值标注为上次记录。

E16 的监控后端独立保存在 `monitor_server.py`，页面位于 `dashboard/`；
E99 文件不作修改，仅复用其原活动页静态资源。更新后重启 E16 的 `monitor.py` 即可，
不需要重建 agent 镜像。monitor 需要当前用户具备 Docker 读取与 exec 权限。
可用 `--port` 更换端口。关闭 monitor 不会停止 agents。
此页面观察 LLM 进程；MC 连接状态通过 `minecraft.observe` 或 Compose 健康状态单独确认。

项目名由之前的 `e16-minecraft` 改为 `output`；旧项目的容器和卷不会自动迁移或删除。
同一 Docker 主机上，其他实验若也叫 `output`，会属于同一个 Compose 项目，不能作为独立 stack 同时部署。

### Mineflayer 任务工具

工具按任务封装，不要求模型猜方块/物品 ID。`find_blocks` 使用当前连接版本的
`registry.blocksByName` 解析名称，搜索半径 1–32 格、最多返回 20 个结果。
没有结果时应移动后再搜索；扩大搜索到数百格不再被允许。内部原生搜索也设置相同上限。

`move_to` 调用默认 pathfinder `goto`，处理绕行；`stop` 停止寻路并清除移动状态。
`equip`、`consume`、`place_block`、`drop_item` 使用物品名称，进食和放置会先装备。
`craft` 使用 `get_recipes` 返回的配方索引，并寻找附近工作台。
`dig_blocks` 顺序挖掘明确坐标，首个失败后停止并保留已完成结果；需要先靠近并装备工具，
不恢复旧的多站位重试。`attack` 攻击指定实体一次，不自动追击。
聊天通知与 `MC_CHAT_RADIUS` 距离限制继续保留。

异步操作保留任务 ID、超时和互斥槽，防止 HTTP 请求挂起或并发改写背包。
超时不保证底层操作结束，`pending=true` 时需继续查询 `action_status`。
原生 `stopDigging`、`clearControlStates`、`deactivateItem` 可在任务运行期间调用。
`completed` 只表示原生调用返回，不额外证明伤害、服务端方块移除或拾取成功。

聊天通过原生 `bot.chat` 发送；`read_chat` 工具已移除。bridge 的内部
`/notifications` 接口保存最近 100 条聊天、受伤、死亡、出生和断线通知；自己的
聊天不入队。`MC_CHAT_RADIUS` 默认 32 格，按收到消息时的三维直线距离过滤；
未知发送者位置及超距聊天不通知。0 表示仅接收同位置聊天，不表示无限距离。
受伤等自身事件不按聊天半径过滤。发送仍使用原生服务器聊天，并非私密或限距广播。
模型每次调用前自动读取通知，紧急事件优先，模型调用成功才推进游标，失败则重投。
成功投递的事件按原始调用位置写入轮次历史，保留发送者、事件 ID 和 epoch；
不再每次追加最近 20 条旧通知。无工具调用的轮次也保存收到的事件，历史仍只保留
最近 8 个有效轮次批次。模型调用失败不会推进游标，下次重投该批。epoch 检测 bridge 重启，
`truncated` 标记缓存溢出。通知文本属于外部数据，不作为系统指令。
`notifications_delivered` 日志表示模型调用成功接收通知，不证明回复或反击。
读取失败记为 `notification_poll_failed`，不阻断正常模型调用。
通知不打断在途动作、模型请求或轮间等待，轮数耗尽后不会自动重新启动 agent。
adapter 不注入世界观察或执行重复失败冷却；轮数、历史和单轮调用预算仍保留。

工具 HTTP 路由在 `bridge/tool_api.js`；`server.js` 管理连接、状态和动作生命周期。
修改需重新生成、构建并重建 agent 容器才会生效。

### AgentService API 迁移

生成器使用新版 `setTools` / `setPersona`，Minecraft bridge 地址放在
`tool_config.minecraft.local`，社交账号配置放在 `persona.accounts.socialmedia`。
E16 仍使用独立的 `adapter/main.py` 入口和原有按轮循环，保留自动通知及
`AGENT_ROUNDS` 等配置，不使用上游常驻框架的 ClockServer 或 checkpoint。
`agentctl run` 根据生成配置启动这个入口，monitor 同步识别该进程。

聊天规则区分发出的请求与对方确认：自己的聊天不构成他人的回复、同意或交付证据；
物品到账需查看背包。没有新信息时不重复追问或承诺，可以等待或继续其他活动。
这是上下文和提示约束，不保证模型绝不会重复说话。
