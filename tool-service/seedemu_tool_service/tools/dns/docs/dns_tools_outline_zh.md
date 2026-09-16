# DNS 工具设计大纲

当前 DNS 工具面保持精简，并按三个职责分类。

## 基础工具

- `dns.lookup`：使用 source 默认解析器或指定服务器查询记录，区分命令失败、DNS 状态和空答案。
- `dns.reverse_lookup`：验证 IP 地址，生成反向名称并查询 PTR。

## 域名注册及更新

- `domain.registrar_find`：只发现通过 `agent.exposed.registrar_url` 显式暴露的 Registrar origin；保留的 `filter` 当前必须为空。
- `domain.rdds_lookup`：通过 `protocol=whois|rdap` 选择协议，通过 `authority=registrar|registry` 选择 Registrar 业务视图或 Registry 最终登记视图；端点来自服务发布的元数据。
- `domain.registrar_request`：从所选 source 向已发现 origin 的同源路径发送受限 GET/POST 请求。Agent 从 `GET /` 开始理解 HTML；工具返回重定向和响应证据，不固化 Registrar API。
- `dns.authoritative_find`：输入已知 source，发现显式分配给它的权威 DNS service ID 及 Primary/Secondary 地址。
- `dns.configure`：为获授权 source 创建自有 Primary/Secondary zone，替换或删除 RRset，并验证两台权威服务器收敛。

Registrar cookie 和身份保留在所选 source 内。source 是会话和身份边界，但 source 名称本身不是凭据；入口授权和已配置的私有凭据仍然必需。

## 诊断工具

- `dns.compare`：比较多个服务器的状态、答案、TTL、延迟和超时。
- `dns.trace`：观察从指定起点开始的委派链。
- `dns.check_delegation`：比较父区 referral/glue 与子区权威 NS 数据。
