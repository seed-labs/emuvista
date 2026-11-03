# Alice：上传并分享文件

在 Alice Web 新建会话并选择 **EmuVista Cloud Agent**，发送以下提示词：

```text
你是 Alice。请通过 Cloud 工具完成一次文件上传和分享，必须以真实工具结果为依据：
1. 调用 cloud_login，server_url=https://cloud.seedvista.test，username=alice，password=alice-password。
2. 为本次操作生成唯一编号，将文件上传到 /h14-basic/<唯一编号>/message.txt。调用 cloud_upload，create_parents=true，正文严格为下面这一行 UTF-8 文本，不附加换行：
Hello Bob from Alice through Cloud Drive.
3. 若路径已存在，换一个编号；不覆盖旧文件。
4. 调用 cloud_share，把本次文件以 user 类型分享给 bob，permissions=["read"]。
5. 汇报工具返回的 remotePath、shareId、recipient、权限、文件大小和上传 SHA-256，供 Bob 定位及核对。

仅执行本次任务。不调用 Claw 或 Schedule 工具，不监听事件、不创建心跳、不与 Bob 交替聊天。完成后停止，保留文件及分享供 Bob 下载。
```

复制返回的 shareId，填入 [Bob 提示词](bob.md) 的 <SHARE_ID>，再发送给 Bob。
