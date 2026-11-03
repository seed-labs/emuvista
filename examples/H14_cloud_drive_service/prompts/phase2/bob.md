# Bob：先建立监听基线

完成 README 中的 [演示阶段二准备](../../README_zh.md#演示阶段二cloud-事件驱动的自主协作)，在同一个 demo profile 中启用 Claw 后使用。

在 Bob Web 中创建新会话，选择 **EmuVista Cloud Agent**。先发送以下提示词，等待工具执行完成后，再让 Alice 发送新分享。

```text
你是 Bob。必须调用工具完成以下步骤：
1. 调用 cloud_login，server_url 为 https://cloud.seedvista.test，username 为 bob，password 为 bob-password。
2. 调用 claw_world_check 建立当前 Cloud 分享基线。
3. 告诉我基线检查是否成功，然后等待数字世界事件。

只使用已有的 Claw 世界事件监听，不要创建心跳或其他定时任务。

后续收到 Claw 的新分享或文件变化事件时：
- 下载对应文件，读取参与者和 max_messages 约定。
- 如果消息数已达到上限，停止写入。
- 如果最后一条消息来自 Alice，保留完整已有内容，只追加一条以 Bob: 开头的简短回复。
- 写入前调用 cloud_stat 获得最新 ETag，用 cloud_upload 的 expected_etag 防止覆盖他人的修改。
- 如果最后一条已经是 Bob 自己写的，不再写入。
- 使用 claw_attention_update 将已处理事件标记为 done。
```

此后不要再向 Bob 输入提示词。新回合应由 Claw 产生。
