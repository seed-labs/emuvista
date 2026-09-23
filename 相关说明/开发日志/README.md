# 开发日志（按分类归档）

> 本目录按 **Network 域分类**（`learning/network-domain-classification-detailed.md`）将各工具的开发日志归档到 A–F 六类子目录。
> 每篇日志记录该工具从"一个想法"到"一个工具"的完整过程：需求定位 / 底层命令观察（A-1 黄金样本）/ 契约 / 实现 / 注册 / 测试 / 文档同步 / VM 验证待办。

## 目录结构

```text
开发日志/
|-- README.md
|-- A-节点状态/        # 查/改单个节点容器内部
|-- B-路由与转发/      # 查/改内核路由表
|-- C-连通性与路径/    # 节点间端到端关系
|-- D-仿真网络/        # ★emulator 特有：仿真子网与链路属性
|-- E-地址与子网计算/  # 纯计算，不碰容器
`-- F-兜底诊断/        # 抓包/防火墙原始证据
```

## 分类 ↔ 工具 ↔ 日志对照

| 类 | 工具（实装 20 个） | 开发日志 |
|---|---|---|
| **A 节点状态** | interface_inspect ✅ / neighbor_inspect ✅ / listen_sockets ✅ / neighbor_update ✅ / sysctl_update ✅（interface_update 未实装） | A-节点状态/（5 篇） |
| **B 路由与转发** | route_inspect ✅ / route_lookup ✅ / route_update ✅ | B-路由与转发/（3 篇） |
| **C 连通性与路径** | ping ✅ / path_trace ✅ / reachability_map ✅ | C-连通性与路径/（2 篇，ping 为 M0 早期无独立日志） |
| **D 仿真网络** ★特有 | link_properties_inspect ✅ / node_networks ✅ / link_update ✅ / link_properties_update ✅ | D-仿真网络/（4 篇） |
| **E 地址与子网计算** | inspect_ip_address ✅ / cidr_inspect ✅ | E-地址与子网计算/（1 篇，inspect_ip_address 为 M0 早期无独立日志） |
| **F 兜底诊断** | packet_capture ✅ / firewall_inspect ✅（条件可用）/ firewall_update ✅（条件可用） | F-兜底诊断/（3 篇） |

