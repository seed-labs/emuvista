# DeepSeek Harness 公共运行时镜像

本目录是项目为 SeedEmu 节点安装 DeepSeek Harness（DSH）的统一入口。需要 DSH 时，请先在这里构建公共运行时镜像，再生成或构建拓扑。不要在各个节点中分别通过 APT 或 `npx` 安装 DSH。

## 当前版本

| 组件 | 版本 |
| --- | --- |
| 镜像标签 | `seedemu-dsh-runtime:0.2.0-rc.2` |
| DSH | `0.2.0-rc.2` |
| Node.js | `24` |
| 目标平台 | `linux/amd64` |

## 首次使用

进入本目录：

```bash
cd /path/to/project/docker-images/deepseek-harness
```

构建公共镜像：

```bash
docker build \
  --platform linux/amd64 \
  --file Dockerfile.dsh-runtime \
  --tag seedemu-dsh-runtime:0.2.0-rc.2 \
  .
```

Dockerfile 会在构建期间验证 Node.js、npm、`dsh` 命令和 `dsh --help`。构建成功后可确认镜像存在：

```bash
docker image inspect seedemu-dsh-runtime:0.2.0-rc.2 \
  --format '{{.Id}} {{.Architecture}} {{.Size}}'
```

## 通过代理构建

需要代理时，先在当前 shell 设置标准代理变量，再传入 Docker 构建。不要把个人代理地址写进 Dockerfile 或拓扑脚本。

```bash
export HTTP_PROXY='http://proxy-host:port'
export HTTPS_PROXY="$HTTP_PROXY"
export NO_PROXY='localhost,127.0.0.1'

docker build \
  --platform linux/amd64 \
  --build-arg HTTP_PROXY="$HTTP_PROXY" \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  --build-arg NO_PROXY="$NO_PROXY" \
  --file Dockerfile.dsh-runtime \
  --tag seedemu-dsh-runtime:0.2.0-rc.2 \
  .
```

## 在 SeedEmu 拓扑中使用

先构建公共镜像，然后从项目根目录运行相应的拓扑生成脚本：

```bash
cd /path/to/project
PYTHONPATH="$PWD" .venv/bin/python path/to/Topology.py
```

拓扑脚本通过 SeedEmu API 让需要 DSH 的节点从公共镜像复制运行时：

```python
DSH_RUNTIME_IMAGE = "seedemu-dsh-runtime:0.2.0-rc.2"

dsh_nodes = (...)

for node in dsh_nodes:
    node.addDockerCommand(
        f"COPY --from={DSH_RUNTIME_IMAGE} /usr/local/ /usr/local/"
    )
```

生成的节点 Dockerfile 不会分别执行 `npm install`。如果公共镜像尚未构建，Docker 在构建节点镜像时会报告找不到 `seedemu-dsh-runtime`；回到本目录完成首次构建即可。

## 构建和验证节点镜像

生成拓扑后，在生成目录构建需要 DSH 的服务：

```bash
cd /path/to/generated-output
docker compose build <service-name>
```

启动拓扑后，可以在对应容器中验证：

```bash
docker exec <container-name> node --version
docker exec <container-name> npm --version
docker exec <container-name> command -v dsh
docker exec <container-name> dsh --help
```

## 无 Web 模式

容器中的 DSH 可以使用 headless profile，不需要启动 Web 服务，也不会监听 Web 端口：

```bash
dsh --profile headless "检查当前容器中的服务状态"
```

也可以从标准输入接收任务：

```bash
printf '%s\n' '执行当前容器中的自动化任务' | dsh --profile headless
```

## 可选：离线分发

导出镜像：

```bash
docker image save \
  --output seedemu-dsh-runtime-0.2.0-rc.2.tar \
  seedemu-dsh-runtime:0.2.0-rc.2
```

在另一台机器加载：

```bash
docker image load \
  --input seedemu-dsh-runtime-0.2.0-rc.2.tar
```

镜像归档较大，不应直接提交到普通 Git 仓库。可以通过 Git LFS、项目 Release 或内部制品仓库分发。

## 升级版本

升级 Node.js 或 DSH 时，需要同时完成：

1. 修改 `Dockerfile.dsh-runtime` 中的基础镜像或 `DSH_VERSION`。
2. 修改镜像标签。
3. 修改相关拓扑脚本中的 `DSH_RUNTIME_IMAGE`。
4. 重新构建公共镜像和所有引用它的节点镜像。
5. 验证 `node --version`、`npm --version`、`command -v dsh` 和 `dsh --help`。
