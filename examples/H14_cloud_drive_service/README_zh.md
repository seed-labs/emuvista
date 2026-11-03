# H14：Agent 使用 Cloud Drive

本例使用同一套 Cloud 服务、Alice/Bob 容器和 demo profile，分两个演示阶段展示 Agent 与 Cloud 的交互：先完成登录、上传、分享和下载核对，再启用 Claw 演示 Cloud 事件驱动的自主协作。

## 环境准备

需要 Linux Docker Engine、Docker Compose v2+、Python 3.10+ 和 linux/amd64 环境，建议至少 4 vCPU、8 GB 可用内存。在仓库的 examples/H14_cloud_drive_service 目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build --platform linux/amd64 -f ../../docker-images/deepseek-harness/Dockerfile.dsh-runtime -t seedemu-dsh-runtime:0.2.0-rc.2 ../../docker-images/deepseek-harness
```

requirements.txt 以 editable 方式安装固定 SEED 源码提交，保留运行时必需的服务模板。公共镜像只需首次构建或升级时重建；构建代理见 [公共镜像说明](../../docker-images/deepseek-harness/README.md)。完成后继续以下启动步骤。

各终端中的命令均从本例目录执行；新终端需要使用 Python 时，先执行 source .venv/bin/activate。

## 启动

完成环境准备后，从本例目录执行：

```bash
python CloudDriveTopology.py
cd output
docker compose -p emuvista-h14 build 072d7840db6a44d06e5c5fd4d7ea8a7d ad739b7b201eccafa592110d2bf214a7
docker compose -p emuvista-h14 build
docker compose -p emuvista-h14 up -d
docker compose -p emuvista-h14 ps
cd ..
```

前两个哈希名称是当前 SEED 版本生成的基础镜像服务，先构建它们可避免首次构建时找不到基础镜像。拓扑文件只生成部署配置，构建和启动均由上述命令手动执行；插件源码和依赖在镜像构建时准备。

容器启动时自动创建 Cloud 账户及 DSH profile，安装本地 bundle 并应用默认 preset；已有账户、密码和 profile 保持原样。在 ps 中确认 Cloud、Alice、Bob 均为 healthy 后，直接手动启动 DSH；若仍为 starting，稍后再次查看状态。初始化失败时见 [状态检查与排障](#状态检查与排障)。

## 打开 Agent

在本例目录分别打开两个终端，手动启动 Alice 和 Bob：

Alice：

```bash
docker compose -p emuvista-h14 -f output/docker-compose.yml exec hnode_154_alice dsh --profile demo --no-open
```

Bob：

```bash
docker compose -p emuvista-h14 -f output/docker-compose.yml exec hnode_154_bob dsh --profile demo --no-open
```

第三个终端在 Docker 主机上提供容器 Web 转发。这是本例的通用访问步骤，因为 DSH 监听容器内部的 loopback 地址：

```bash
python container/web_tunnel.py
```

| Agent | Docker 主机上的访问地址 |
| --- | --- |
| Alice | http://127.0.0.1:18081 |
| Bob | http://127.0.0.1:18082 |

使用各自 DSH 终端打印的认证 URL，将端口 3080 分别替换为 18081、18082，保留 token 后打开。模型 API 地址、密钥和模型在 Web 设置中填写。浏览器也在 Docker 主机上时可直接访问；跨主机访问还需 SSH 转发。通用配置见 [可选网络配置](#可选网络配置)。

## 登录、上传、分享和下载

在两个 Web 中新建会话，选择 **EmuVista Cloud Agent**：

1. 向 Alice 发送 [上传与分享提示词](prompts/phase1/alice.md)。等待上传和只读分享完成，记录返回的 shareId 和 SHA-256。
2. 将 shareId 填入 [下载与核对提示词](prompts/phase1/bob.md)，再发送给 Bob。
3. 查看 Trajectory 中的真实工具结果：Bob 下载的正文应为 Hello Bob from Alice through Cloud Drive.，下载 SHA-256 应与 Alice 上传返回值一致。

| Agent | 应观察到的 Cloud 交互 |
| --- | --- |
| Alice | cloud_login → cloud_upload → cloud_share，接收者为 bob，权限为 read |
| Bob | cloud_login → cloud_list_shares → cloud_download，找到对应分享并核对正文、摘要 |

账户为 alice / alice-password 和 bob / bob-password，Cloud 地址为 https://cloud.seedvista.test。新建的 demo profile 先安装 Cloud bundle，双方各执行一次用户任务后停止。已有旧版 profile 保持原样，需要重新进行阶段一时，按 [已有数据与重新运行](#已有数据与重新运行) 处理。

## Cloud 事件驱动的自主协作

阶段一完成后，停止两个 DSH，保留 Cloud 容器和 Web 转发器。在同一个 demo profile 中安装 Claw bundle：

```bash
docker compose -p emuvista-h14 -f output/docker-compose.yml exec hnode_154_alice dsh plugin --profile demo add /opt/emuvista/agent-plugins/claw-bundle
docker compose -p emuvista-h14 -f output/docker-compose.yml exec hnode_154_bob dsh plugin --profile demo add /opt/emuvista/agent-plugins/claw-bundle
```

镜像已包含 Claw，无需重建拓扑或镜像，也不创建另一个 profile。已有 bundle 时跳过安装；若此前停用了它，在 Web Plugins 中重新启用。按“打开 Agent”中的相同命令重新启动 DSH，新建会话并选择 **EmuVista Cloud Agent**：

1. 向 Bob 发送 [阶段二准备提示词](prompts/phase2/bob.md)，等待登录及分享基线检查完成。
2. 向 Alice 发送 [阶段二发起提示词](prompts/phase2/alice.md)，创建新的聊天文件并以 read/update 权限分享。
3. 此后不再追加人工提示词，观察双方被 Cloud 分享及文件变化唤醒，形成 7 条交替消息后停止。

阶段二使用不同于阶段一的新文件。每次回复须通过 expected_etag 安全更新；在 Trajectory 中核对 emuvista-claw 事件来源、工具调用和最终文件。两阶段共同体现 Agent 对 Cloud 的实际使用，第二阶段进一步展示服务事件如何驱动后续行动。

## 关闭

在两个 DSH 终端和转发器终端按 Ctrl+C，然后执行：

```bash
docker compose -p emuvista-h14 -f output/docker-compose.yml down --remove-orphans
```

Cloud 数据和 DSH profile 保留在 .runtime 中。再次启动容器后，手动启动两个 Agent 和转发器即可。
