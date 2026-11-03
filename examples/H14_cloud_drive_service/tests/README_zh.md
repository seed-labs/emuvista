# H14 工具级验证

先按 [主文档](../README_zh.md) 启动拓扑并等待账户自动初始化完成。以下命令从 H14 目录执行，不要求 DSH Web 正在运行。本页验证 Cloud 工具与服务，不代替演示阶段中的真实 Agent 提示词验证。

```bash
cd /path/to/emuvista/examples/H14_cloud_drive_service
export COMPOSE_PROJECT_NAME=emuvista-h14
export COMPOSE_FILE="$PWD/output/docker-compose.yml"
set -o pipefail
```


测试文件只承载一次 ToolRuntime 调用，不负责容器生命周期、配置、账户创建或跨容器编排。下面每条命令手动在指定容器执行当前仓库测试源码；密码通过标准输入传入。该验证不调用模型。

```bash
printf '%s\n' '{"action":"inventory","username":"alice"}' \
  | docker compose exec -T hnode_154_alice node --input-type=module --eval "$(cat tests/cloud-worker.mjs)"
printf '%s\n' '{"action":"inventory","username":"bob"}' \
  | docker compose exec -T hnode_154_bob node --input-type=module --eval "$(cat tests/cloud-worker.mjs)"
```

两边应各返回 23 个工具；程序同时断言未登录时 cloud_account 被拒绝。为本次检查选择唯一目录，显式执行 Alice 上传并分享，然后 Bob 接收并下载：

```bash
remote="/h14-manual-$(date +%s)-$$/message.txt"
content='Hello from Alice'
jq -nc --arg remote "$remote" --arg content "$content" \
  '{action:"send",username:"alice",password:"alice-password",remote:$remote,content:$content,recipient:"bob"}' \
  | docker compose exec -T hnode_154_alice node --input-type=module --eval "$(cat tests/cloud-worker.mjs)" \
  | tee .runtime/alice-share.json
share_id="$(jq -er '.shareId' .runtime/alice-share.json)"
jq -nc --arg id "$share_id" \
  '{action:"receive",username:"bob",password:"bob-password",share_id:$id}' \
  | docker compose exec -T hnode_154_bob node --input-type=module --eval "$(cat tests/cloud-worker.mjs)" \
  | tee .runtime/bob-received.json
printf '%s' "$content" | sha256sum
jq -r '.sha256' .runtime/bob-received.json
```

手动对比两行 SHA-256，必须相同。记录结果后撤销分享并删除本次文件目录：

```bash
jq -nc --arg remote "$remote" --arg id "$share_id" \
  '{action:"cleanup",username:"alice",password:"alice-password",remote:$remote,share_id:$id}' \
  | docker compose exec -T hnode_154_alice node --input-type=module --eval "$(cat tests/cloud-worker.mjs)"
```

再显式执行反方向，验证 Bob 上传、Alice 下载：

```bash
remote="/h14-manual-reverse-$(date +%s)-$$/message.txt"
content='Hello from Bob'
jq -nc --arg remote "$remote" --arg content "$content" \
  '{action:"send",username:"bob",password:"bob-password",remote:$remote,content:$content,recipient:"alice"}' \
  | docker compose exec -T hnode_154_bob node --input-type=module --eval "$(cat tests/cloud-worker.mjs)" \
  | tee .runtime/bob-share.json
share_id="$(jq -er '.shareId' .runtime/bob-share.json)"
jq -nc --arg id "$share_id" \
  '{action:"receive",username:"alice",password:"alice-password",share_id:$id}' \
  | docker compose exec -T hnode_154_alice node --input-type=module --eval "$(cat tests/cloud-worker.mjs)" \
  | tee .runtime/alice-received.json
printf '%s' "$content" | sha256sum
jq -r '.sha256' .runtime/alice-received.json
jq -nc --arg remote "$remote" --arg id "$share_id" \
  '{action:"cleanup",username:"bob",password:"bob-password",remote:$remote,share_id:$id}' \
  | docker compose exec -T hnode_154_bob node --input-type=module --eval "$(cat tests/cloud-worker.mjs)"
```

同样手动核对哈希。任一步失败时先查看错误并处理，不要继续假定测试成功；若已上传但尚未记录分享 ID，可在 Cloud Web 或 cloud_list_shares 中查找并清理这次测试的唯一目录和分享。
