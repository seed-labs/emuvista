# H30：使用 DshAgentService 部署 Cloud Drive Agent

[English](README.md)

本例在 SEED 网络中部署 Cloud Drive、DNS、CA 和两个 DSH Agent。拓扑通过 `DshAgentService` 初始化各自的 Profile，并从 [Bundle 声明](bundles/cloud-tools.yml) 加载 Cloud 工具。两个阶段共用一个 `dshagent` Profile。

## 构建并启动

需要 Linux Docker Engine、Docker Compose v2、Python 3.10+ 和 amd64 环境。以下命令从本例目录执行。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build --platform linux/amd64 -f ../../docker-images/deepseek-harness/Dockerfile.dsh-runtime -t seedemu-dsh-runtime:0.2.0-rc.2 ../../docker-images/deepseek-harness

python CloudDriveTopology.py
cd output
docker compose -p emuvista-h30 build 072d7840db6a44d06e5c5fd4d7ea8a7d ad739b7b201eccafa592110d2bf214a7
docker compose -p emuvista-h30 build
docker compose -p emuvista-h30 up -d
docker compose -p emuvista-h30 ps
cd ..
```

前两个 Compose 服务提供 SEED 基础镜像，应先构建。等待 Cloud 显示 `healthy`。首次启动会自动创建 Cloud 测试账号，并初始化两个 Agent 的 Profile。重新生成拓扑前先关闭旧部署，再配套重建节点镜像，因为拓扑会重新生成 CA 材料。

## 打开 Agent

从本例目录打开三个终端，分别运行以下命令。转发器终端需先激活 Python 环境。

```bash
docker compose -p emuvista-h30 -f output/docker-compose.yml exec hnode_158_alice dshagent web
docker compose -p emuvista-h30 -f output/docker-compose.yml exec hnode_158_bob dshagent web
python container/web_tunnel.py
```

打开各 DSH 终端打印的认证 URL，将 Alice 的端口改为 `18311`，Bob 的改为 `18312`，保留完整认证参数。在 Web 中配置模型，然后在每个 Agent 中新建 **Resident** 会话。

## 阶段一：分享与下载核对

从已激活 Python 环境的终端运行以下脚本，在两个运行中的实例上停用默认装配的 Claw。

```bash
PYTHONPATH=../.. python - <<'PY'
from services.DshAgentService import DshAgentRuntime

runtime = DshAgentRuntime.from_compose("output/docker-compose.yml", project="emuvista-h30")
for name in ("alice", "bob"):
    print(name, runtime.agent(name).plugins.disable("claw").status)
PY
```

1. 向 Alice 发送 [上传和只读分享提示词](prompts/phase1/alice.md)，记录 share ID 和 SHA-256。
2. 把 share ID 填入 [下载提示词](prompts/phase1/bob.md)，发送给 Bob。
3. 在 Trajectory 中核对 Bob 下载的实际正文和 SHA-256。正文应是 `Hello Bob from Alice through Cloud Drive.`，摘要应与 Alice 上传时返回的一致。

Cloud 地址为 `https://cloud.h30.seedvista.test`，示例账号是 `alice / alice-password` 和 `bob / bob-password`。证书由拓扑内的 CA 签发。

## 阶段二：Cloud 事件驱动协作

在 Trajectory 中确认阶段一的两个会话都已成功调用 `cloud_logout`，避免旧会话也响应新分享。两边空闲后，用同一个 Python API 热启用 Claw，继续使用原 Profile 和 Web 进程。

```bash
PYTHONPATH=../.. python - <<'PY'
from services.DshAgentService import DshAgentRuntime

runtime = DshAgentRuntime.from_compose("output/docker-compose.yml", project="emuvista-h30")
for name in ("alice", "bob"):
    print(name, runtime.agent(name).plugins.enable("claw").status)
PY
```

两边新建 **Resident** 会话。先发送 [Bob 的监听准备提示词](prompts/phase2/bob.md)，等基线建立后，再用新的文件编号发送 [Alice 的协作提示词](prompts/phase2/alice.md)。随后只观察。核对轨迹中的 Claw 事件、`expected_etag` 和最终文件中的七条交替消息。

## 关闭

停止两个 Web 终端及转发器，然后执行：

```bash
docker compose -p emuvista-h30 -f output/docker-compose.yml down
```

Cloud 数据和 Profile 保存在 `.runtime/`。再次运行阶段一时，可以用原脚本停用 Claw。 [DshAgentService 使用指南](../../services/DshAgentService/README_zh.md)
