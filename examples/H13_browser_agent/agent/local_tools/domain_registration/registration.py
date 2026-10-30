"""Register the standalone browser purchase tools."""

from local_tools.domain_registration.models import RegistrarFindArguments, HostedDNSFindArguments
from local_tools.domain_registration.tools import registrar_find, hosted_dns_find
from local_tools.registry import ToolDefinition


def register_purchase_tools(registry):
    registry.register(
        ToolDefinition(
            "domain.registrar_find",
            "domain",
            "Discover configured registrar and payment origins. This is not a health check. "
            "Use browser.action to read and operate the real website.",
        ),
        registrar_find,
        RegistrarFindArguments,
    )
    registry.register(
        ToolDefinition(
            "dns.hosted_find",
            "dns",
            "查询 FOSSBilling DNS Hosting 静态目录，返回客户区入口、订购和激活流程、主从 NS 信息。"
            "通过客户区服务订单管理 DNS 记录，与域名注册和 NS 委派分别核验；不是健康检查。",
        ),
        hosted_dns_find,
        HostedDNSFindArguments,
    )
