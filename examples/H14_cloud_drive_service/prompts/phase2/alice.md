# Alice：发起 Cloud 文件对话

完成 README 中的 [演示阶段二准备](../../README_zh.md#演示阶段二cloud-事件驱动的自主协作)，在同一个 demo profile 中启用 Claw 后使用。

先确认 Bob 已登录并完成 claw_world_check。Alice 也使用新会话，选择 **EmuVista Cloud Agent**。用一个本次演示专用的新文件名，避免把历史 share 当作新事件。

```text
你是 Alice。必须调用工具完成：
1. 调用 cloud_login，server_url 为 https://cloud.seedvista.test，username 为 alice，password 为 alice-password。
2. 调用 claw_world_check 建立基线。
3. 创建本次演示专用的唯一文件 /h14-demo/chat-<本次唯一编号>.md，
   内容包括以下约定：
   participants: alice, bob
   max_messages: 7
   每行消息以 Alice: 或 Bob: 开头。
   只有最后一条消息来自对方时才追加一条回复。
   达到 7 条消息立即停止。
   第一条消息为 Alice: 你好 Bob，请介绍你在 Cloud 中可以做什么。
4. 调用 cloud_share，以 user 类型分享给 bob，权限为 read 和 update。
5. 返回 share ID 和完整 remote path。

只使用已有的 Claw 世界事件监听，不要创建心跳或其他定时任务。

后续 Claw 通知文件变化时：
- 下载完整文件并检查消息数与最后发言者。
- 未达 7 条且最后一条是 Bob 时，只追加一条 Alice: 回复。
- 写入前获取最新 ETag，通过 expected_etag 安全覆盖上传。
- 如果最后一条是 Alice 自己写的，不再写入。
- 标记已处理 Claw 事件为 done。
```

此后不再向双方发送新提示词。展示 Bob 的自动回合、Alice 的自动回合以及 Cloud 文件，不要仅以模型声称“已唤醒”作为证据。

结束时可让 Alice 撤销该分享、删除本次文件，让双方 cloud_logout。
