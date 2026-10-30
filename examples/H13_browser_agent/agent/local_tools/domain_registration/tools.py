"""Registrar discovery owned by this agent; all operations use the real browser."""


def registrar_find(filter=None):
    registrar = {
        "service_id": "registrar",
        "provider": "fossbilling",
        "registrar_url": "http://10.150.0.72:8080",
        "hosted_dns_tool": "dns.hosted_find",
        "payment_service_id": "payment",
        "payment_url": "http://10.160.0.71:8080",
        "instructions": "Open the registrar website with browser.action. Use observed links/forms. "
        "Keep the same browser context after login. Verify account identity, cart, "
        "invoice and domain service separately. Do not repeat a paid order.",
        "payment_instructions": "FakePayment serves FOSSBilling only. Follow the actual invoice "
        "payment link/form and confirmation page in the browser. "
        "Do not synthesize signatures or call internal callbacks.",
    }
    matched = all(registrar.get(key) == value for key, value in (filter or {}).items())
    return {
        "registrars": [registrar] if matched else [],
        "next_step": "Use browser.action to open the observed service; discovery is not a probe.",
    }


def hosted_dns_find(filter=None):
    """Return configured example endpoints without scanning or asserting availability."""
    service = {
        "service_id": "hosted_dns",
        "provider": "fossbilling-servicedns",
        "web_url": "http://10.150.0.72:8080",
        "nameservers": [
            {"hostname": "ns1.example.com", "address": "10.170.0.71", "role": "primary"},
            {"hostname": "ns2.example.com", "address": "10.170.0.72", "role": "secondary"},
        ],
        "product_name": "DNS Hosting",
        "product_type": "dns",
        "management_mode": "fossbilling_service_order",
        "capabilities": ["订购 DNS Hosting", "核对托管服务开通状态", "通过服务订单管理 DNS 记录"],
        "workflow": [
            "登录 FOSSBilling 客户区，先在已有服务中查找目标域名的 DNS Hosting 订单。",
            "已有订单时复用并核对状态；没有时，从 Order 商品页查找 DNS Hosting 分类或商品。",
            "按页面填写用户指定的域名并核对价格。新建的仿真产品通常免费，但已有商品价格可能不同，以实际页面为准。",
            "在用户授权范围内结算；有待付账单则按实际付款入口处理，免费订单也需确认是否成功激活。",
            "服务激活后，从 Services 中打开该订单的管理页，观察已有记录和支持的记录类型，再按用户要求修改。",
            "核对域名注册服务的 NS 委派；托管开通或记录保存不代表注册商 NS 已更新。",
        ],
        "instructions": "通过 browser.action 打开 FOSSBilling 客户区，在 DNS Hosting 服务订单中管理解析。"
        "DNS Hosting 是独立服务，不能因域名已购买就认定托管已开通。"
        "先检查服务是否激活及已有记录，再按用户授权修改，不重复下单或付款。"
        "记录类型、TTL、主机名格式等以当前管理页为准，不假定仅支持 A 记录。"
        "主从区域由 DNS Hosting 插件通过 BIND API 配置，不直接操作内部 API。"
        "不再使用旧的独立 DNS 管理页面，也不寻找管理后台或 BIND API 的账号。",
        "failure_instructions": "若商品不可见、订单 pending/failed、记录管理不可用或出现 Provider/API 错误，"
        "记录当前页面的实际错误和订单状态并报告，不反复下单、付款或猜测后台接口。"
        "插件启用、产品配置和主从 BIND API 初始化由场景维护者处理。",
        "delegation_instructions": "托管区域和注册商 NS 委派是两项独立配置。"
        "需要时通过注册商的域名管理页面，将域名 NS 设置为这里列出的主从服务器。"
        "只在用户要求配置解析时执行；缺少记录类型对应的必要值（例如 A 记录的 IPv4 地址）时先询问，不能自行猜测。",
        "verification": "页面显示保存成功只证明管理操作结果，不证明公网或递归 DNS 已生效。"
        "分别报告域名购买、DNS Hosting 订单激活、NS 委派和托管记录的实际完成情况及未核验项目。",
    }
    matched = all(service.get(key) == value for key, value in (filter or {}).items())
    return {"services": [service] if matched else [], "discovery_mode": "static",
            "health_checked": False}
