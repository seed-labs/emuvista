# ShopService

A native SEED Service that runs WordPress, WooCommerce, MultiVendorX and MySQL
inside one emulated host. The same container serves the storefront, seller and
administrator websites and customer APIs. Initialization runs before the website
becomes healthy. MySQL listens only on localhost.

```python
from services.ShopService import ShopService
from seedemu.core import Binding, Filter

service = ShopService(resolver=DNS_RESOLVER)
shop = service.install('shop')
shop.setHostname('shop.com')
shop.setInitialConfiguration('shop.json')
shop.connectEmail(email)
shop.connectPayment(payment, group='SEED')
shop.enableHostAccess(8449)
# Optional: shop.setSavePath('./shop-state')
emu.addLayer(service)
emu.addBinding(Binding('shop', filter=Filter(asn=154, nodeName='host_0')))
```

Configure DNS to point `shop.com` at the bound host. The standard Docker compiler
selects `handsonsecurity/emuvista-shop:1.0` through the Service's image mapping.
Build it with `docker compose -f docker_images/shop/compose.yml build` first. No separate database or initializer
container is created. Mailbox and payment APIs remain in independent systems.

The built-in administrator is `admin` / `ShopAdminDemo123!`.
Users register at `/my-account/`, open stores at `/store-registration/` and
manage products and sales at `/dashboard/`. A seller connects their receiving
Payment wallet under **My account → Account details** by signing into Payment
once. The password is not saved. Store owners can also browse and buy from
other stores.

Initial configuration accepts `currency` and `users`. A user has `id`, `name`,
`email`, `password`, optional receiving `wallet` ID and optional `store` with
`name` and `products`. Products have `title`, `description`, `priceMinor` and
optional text `content`. `addUser` adds the same metadata before rendering.
No sample customers or products are defined in the Service.

`connectPayment` records the merchant partnership; buyers authorize their own
cards in Payment. Checkout fixes the order amounts and recipients. Payment
charges the buyer's balance or linked card, then notifies the shop. The shop
independently verifies the receipt before completing the order and unlocking
downloads. Reopening a checkout retains its transfer IDs. Partial payments remain
pending for reconciliation. Refunds, shipping/fee allocation and cross-currency
checkout are not implemented.

`getAgentTools()` exports marketplace tools using `accounts.shop` credentials.
`shop.pay` also uses the resident's separate Payment identity and tool package.

Without `setSavePath`, rendering creates fresh storage outside `output`.
`setSavePath(path)` preserves the website, MySQL data and credentials. State
labels allow E99's startup script to reset temporary data before a fresh run.
The previous ShopBundle's `site`, `database` and credentials layout is retained;
stop the old deployment and regenerate its output before using saved data with ShopService.

See [H23](../../examples/H23_shop_service/) for startup, accounts and purchases.
