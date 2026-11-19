# H23 Minecraft

在 seed-emulator 的 `B02_mini_internet_with_dns` 上额外添加一个 Minecraft Java 服务器容器节点。
直接复用 B02 的 `build_emulator()`，不复制拓扑。选用 B02 的主要原因是 InternetMap 接口兼容性：
H00 编译入口仍使用当前 Docker 编译器不支持的 `internetMapEnabled` 参数，
B02 和本示例均通过 `InternetMap` ContainerBundle 显式注册地图服务，同时保留 DNS 基础设施。
这一接口差异与构建阶段的 BuildKit `no such job` 错误是两个不同问题。
仓库布局要求 emuvista 与 seed-emulator 为同级目录。
复用公共 `MinecraftBundle`，不依赖 E16 Minecraft 伐木交易实验，不添加 agent、Mastodon 或支付服务。

| 配置 | 默认值 |
| --- | --- |
| 模拟网络地址 | AS170 / net0，10.170.0.10 |
| 模拟 DNS | minecraft.com |
| 宿主机端口 | 25565 |
| 服务端 | Vanilla 26.1，itzg/minecraft-server:java25 |
| Java 内存 | 4G |
| 存档卷 | minecraft-example-data |

## 生成和启动

在 emuvista 仓库根目录执行：

```bash
.venv/bin/python examples/H23_minecraft/minecraft.py
cd examples/H23_minecraft/output
```

先构建 SEED 的基础镜像包装层，再构建所有节点，避免并行构建时查找尚未生成的本地镜像：

```bash
for image in dummies/*; do
  docker build -f "$image" -t "${image##*/}" . || break
done
```

确认基础镜像构建成功后：

```bash
docker compose --progress=plain build
docker compose up -d
docker compose logs -f minecraft
```

配置中 `EULA=TRUE` 表示接受 [Minecraft EULA](https://www.minecraft.net/eula)。
首次启动会下载游戏服务端，需要联网。默认离线模式 `ONLINE_MODE=FALSE`，沿用 E16 Minecraft 伐木交易实验 的实验设置。
需要正版认证时在生成器中改为 `TRUE` 后重新生成和重建。

使用 Minecraft Java 26.1 客户端连接 `Docker宿主机IP:25565`；同机可用 `localhost:25565`。
模拟网络内通过 B02 的 DNS 访问 `minecraft.com:25565`（AS170 的解析器为 `10.152.0.53`）。
服务器自身沿用 Docker DNS 解析公网下载域名；示例额外添加 AS99999 公网出口。这个示例不创建机器人。
B02 构建函数会在其源码目录生成 `base_internet.bin` 和 `dns_component.bin`。

E16 Minecraft 伐木交易实验 默认也占用 25565；运行本示例前停止其他占用端口或同名容器的 SEED 实验。
如只需更换 Minecraft 宿主机端口，可生成时传入 `--host-port 25566`；内部端口仍为 25565。
仅改游戏端口不能消除 B02 路由器、网络地图等共享容器名称和端口冲突。

## 检查和停止

```bash
docker compose ps minecraft
docker compose exec minecraft rcon-cli list
docker compose down
```

普通停止和重新生成 output 保留 `minecraft-example-data` 卷，独立于 E16 Minecraft 伐木交易实验 的世界存档。
`docker compose down -v` 会删除该卷及世界数据。
生成配置成功不代表服务器已就绪；需检查健康状态、服务端日志和客户端连接。
