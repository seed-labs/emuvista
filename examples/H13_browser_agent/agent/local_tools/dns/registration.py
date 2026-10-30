"""Register read-only DNS queries."""

from local_tools.dns.models import LookupArguments
from local_tools.dns.tools import lookup
from local_tools.registry import ToolDefinition


def register_dns_tools(registry):
    registry.register(ToolDefinition(
        'dns.lookup', 'dns',
        '从本容器的仿真网络查询 DNS。name 为域名，record_type 默认 A。'
        'server 留空使用 本容器默认解析器；指定 IP 可查权威 DNS，recursive=false 可关闭递归。'
        '返回 DNS 状态、answer/authority/additional 和权威标志。'
        '只读查询，不创建或修改记录；NOERROR、空回答、NXDOMAIN、超时必须区分。',
    ), lookup, LookupArguments)
