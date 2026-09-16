# source 自有 DNS 与域名注册设计

## 设计概览

B02a 展示 Agent 如何在 SeedEmu 网络内配置自有权威 DNS，并通过 Loom 和 Namingo 注册 `example.com`。总体架构由 Agent、Registrar、Registry，以及父区和子区 DNS 组成。

```mermaid
%%{init: {"theme": "base", "flowchart": {"useMaxWidth": true, "rankSpacing": 38, "nodeSpacing": 12}, "themeVariables": {"fontSize": "20px", "background": "#000000", "primaryColor": "#111827", "primaryTextColor": "#ffffff", "primaryBorderColor": "#9ca3af", "lineColor": "#d1d5db", "clusterBkg": "#0b0f14", "clusterBorder": "#6b7280", "edgeLabelBackground": "#000000"}}}%%
flowchart TB
    agent["Agent"]
    source["selected source<br/>私有凭据与本地 session"]

    subgraph registrar_side["Registrar 侧"]
        direction TB
        loom["Loom HTTPS 前端<br/>订单、支付与 EPP client"]
        loom_db[("Loom MariaDB")]
        namingo["Namingo Registrar<br/>只读 Loom 数据的 WHOIS / RDAP"]
    end

    subgraph registry_side["Registry 侧"]
        direction TB
        registry["Namingo Registry<br/>EPP 与 Registry WHOIS / RDAP"]
        registry_db[("Registry MariaDB")]
        writer["Registry Zone Writer"]
    end

    subgraph parent_dns[".com 父区权威 DNS"]
        direction TB
        hidden["隐藏 Primary"]
        public_dns["公共 Secondary B / C"]
    end

    subgraph child_dns["source 自有 example.com DNS"]
        direction TB
        child_primary["ns1 Primary"]
        child_secondary["ns2 Secondary"]
    end

    %% Invisible layout spine: keep the architecture regions stacked vertically.
    source ~~~ loom
    namingo ~~~ registry
    writer ~~~ hidden
    public_dns ~~~ child_primary

    agent -->|"发起操作"| source
    source -->|"HTTPS 表单与 session"| loom
    loom -->|"读写业务数据"| loom_db
    loom -->|"mTLS EPP"| registry
    namingo -->|"loom adapter 只读查询"| loom_db

    registry <-->|"注册与 RDDS 数据"| registry_db
    writer -->|"读取有效域名"| registry_db
    writer -->|"发布 .com zone"| hidden
    hidden -->|"NOTIFY + AXFR/IXFR"| public_dns
    source -->|"SSH 配置、更新、验证"| child_primary
    source -->|"SSH 配置、验证"| child_secondary
    child_primary -->|"AXFR/IXFR"| child_secondary
    classDef dark fill:#111827,stroke:#9ca3af,color:#ffffff
    class agent,source,loom,loom_db,namingo,registry,registry_db,writer,hidden,public_dns,child_primary,child_secondary dark
    style registrar_side fill:#0b1220,stroke:#60a5fa,color:#ffffff
    style registry_side fill:#17110a,stroke:#f59e0b,color:#ffffff
    style parent_dns fill:#1a0d14,stroke:#f472b6,color:#ffffff
    style child_dns fill:#071a12,stroke:#4ade80,color:#ffffff
```

Loom 是购买流程的业务入口。它保存客户、订单和账单，在付款成功后通过 EPP 向 Namingo Registry 创建 contact、host 和 domain 对象。Namingo Registrar 使用 `loom` backend 读取同一份 Loom 数据，为注册结果提供 WHOIS 和 RDAP 查询。Registry 的 Zone Writer 再把有效委派发布到 `.com` 权威 DNS。

工具服务通过 Docker metadata 发现 source 所持有的权威 DNS；真正的 Registrar 请求、RDDS 查询和 DNS 配置则由 RuntimeBackend 在所选 source 内执行。Namingo Registrar 提供 Loom 业务视图，Namingo Registry 另行提供最终登记视图。

父区和子区分别管理不同的数据：`.com` 保存 `example.com` 的 NS 与 glue；source 自有 DNS 保存 `www.example.com` 等域内记录。两者通过正常 DNS 委派连接。

## Agent 工具调用流程

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as tool-service
    participant S as selected source
    participant L as Loom
    participant R as Namingo Registry
    participant P as .com DNS
    participant D as example.com DNS

    A->>T: domain.registrar_find
    T-->>A: Loom origin
    A->>T: dns.authoritative_find(source)
    T-->>A: service ID、Primary、Secondary
    A->>T: dns.configure(已发现 service, zone, A record)
    T->>S: 执行 DNS 配置
    S->>D: 更新 Primary 并同步 Secondary
    D-->>A: 权威响应与 SOA 收敛
    A->>T: domain.registrar_request(GET /)
    T->>S: 建立 source-local session
    S->>L: HTTPS + source token
    L-->>A: HTML、session_id、CSRF 表单
    A->>T: domain.registrar_request(注册表单)
    T->>L: 域名、联系人、NS 与 glue
    L-->>A: invoice 跳转
    A->>T: domain.registrar_request(支付表单)
    T->>L: 余额付款
    L->>R: EPP contact/host/domain create
    R-->>L: 注册成功
    R->>P: Zone Writer 发布 NS/glue
    A->>T: dns.check_delegation
    T->>P: 查询父区 referral/glue
    T->>D: 查询子区 NS/SOA
    A->>T: dns.lookup（两台递归解析器）
    T-->>A: www.example.com A
```

实际调用步骤如下：

1. Agent 调用 `domain.registrar_find`，从显式发布的 metadata 中发现 Loom origin。
2. Agent 使用所选 source 调用 `dns.authoritative_find`，发现分配给它的 service ID 以及 Primary/Secondary 地址。
3. Agent 将发现的 service ID 传给 `dns.configure`，创建 `example.com` 子区并写入 `www` 等记录；工具同时验证 Primary、Secondary 和 SOA。
4. Agent 调用 `domain.registrar_request` 请求 Loom 首页。工具从所选 source 建立认证 session，并返回页面、`session_id` 和 HTTP 证据。
5. Agent继续用同一 `session_id` 读取注册表单，保留 CSRF 字段，再提交域名、联系人、`ns1/ns2` 和 glue 地址。
6. Loom 创建订单和账单；Agent读取支付页面并提交余额付款。
7. Loom 的 EPP client 向 Namingo Registry 创建注册对象。Registry 成功提交后，Zone Writer 发布 `.com` 委派。
8. Agent 调用 `dns.check_delegation`，确认父区 NS/glue 与两台子区权威服务器一致。
9. Agent 调用 `dns.lookup`，分别通过 B02a 的两台递归解析器验证最终 A 记录。

Registrar session 和私有凭据保留在所选 source 内；Agent 通过工具看到的是可发现的 Loom 页面和结构化 DNS 结果。父区变更经 Registrar/Registry 完成，而购买后的普通子区记录继续使用 `dns.configure` 更新。

## Namingo Registrar 与 Loom

B02a 将 `NamingoRegistrarService` 配置为 `loom` backend。Namingo Registrar 通过专用只读账号连接 Loom MariaDB，因此 Registrar WHOIS/RDAP 与 Loom 订单展示的是同一份业务数据。Namingo Registry 另行提供直接读取 Registry MariaDB 的 WHOIS/RDAP 最终登记视图。Agent 使用 `domain.rdds_lookup` 的 `protocol` 和 `authority` 参数选择协议与视图。B02a 不启用 Namingo automation，订单驱动的域名生命周期由 Loom 负责。

## DNS 发布与解析

Namingo Registry 将注册数据交给 Zone Writer，Zone Writer 发布到 `.com` 隐藏 Primary，再通过 NOTIFY 和 TSIG 保护的 AXFR/IXFR 同步两台公共 Secondary。递归解析器从公共 Secondary 获得 `example.com` 的 referral 和 glue，随后查询 source 自有权威 DNS。

动态委派可能受到递归缓存影响，因此完整测试分别等待两台递归解析器收敛，而不是只验证其中一台，也不会通过清空缓存伪造成功。

## 实现与验证

主要实现位于：

- `seed-emulator/examples/internet/B02a_domain_registration/domain_registration.py`
- `seed-emulator/seedemu/services/LoomRegistrarService.py`
- `seed-emulator/seedemu/services/NamingoRegistrarService.py`
- `seed-emulator/seedemu/services/NamingoRegistryService.py`
- `seedemu-agent-tools/tool-service/seedemu_tool_service/tools/dns/`

Docker 购买测试覆盖 Loom session、下单付款、EPP 注册、WHOIS/RDAP、父区委派、子区权威响应，以及两台递归解析器的最终解析。
