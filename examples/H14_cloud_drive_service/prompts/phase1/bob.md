# Bob：下载并核对分享文件

将 <SHARE_ID> 替换为 Alice 返回的实际分享 ID，再在 Bob Web 的新会话中发送以下提示词；选择 **EmuVista Cloud Agent**。

```text
你是 Bob。请通过 Cloud 工具读取 Alice 的分享，必须以真实工具结果为依据：
1. 调用 cloud_login，server_url=https://cloud.seedvista.test，username=bob，password=bob-password。
2. 调用 cloud_list_shares，direction="incoming"，找到 shareId=<SHARE_ID> 的分享，核对 owner 为 alice。没有找到就报告未找到，不猜测。
3. 使用该分享返回的 targetPath 调用 cloud_download，output="text"；不猜测下载路径。
4. 显示下载得到的实际正文，并核对正文严格为以下文本（UTF-8，不附加换行）：
Hello Bob from Alice through Cloud Drive.
5. 核对 cloud_download 返回的 sha256 等于：
f557974f46634545eb660b5b88e7cb224b1f55c198162555e82ca1aa9f4a8bfa
6. 汇报 shareId、实际下载路径、字节数、下载 SHA-256，以及内容和哈希各自的核对结果。若有不一致，明确报告失败，不修改文件来使结果一致。

仅执行下载和核对，不上传或修改文件，不调用 Claw 或 Schedule 工具，不监听事件、不创建心跳。完成后停止。
```

将 Bob 返回的 SHA-256 与 Alice 上传工具返回的 SHA-256 再核对一次。成功标准是实际内容相同、两边摘要一致；聊天中的“已完成”不能代替工具结果。
