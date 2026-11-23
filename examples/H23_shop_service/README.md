# Marketplace

A single-host marketplace on mini Internet, with independent email, Payment and bank systems. Customers can
open stores, publish products and buy from multiple sellers in one order.

Build the customized images from [docker_images](../../docker_images/README.md), then:

```sh
python3 shop.py
cd output
DOCKER_BUILDKIT=0 docker compose build
docker compose up -d
```

Wait for `payment-initialize`, `bank-initialize` and `email-initialize` to exit
successfully. The ShopService host runs its own database and initialization; its
health check becomes healthy after the marketplace is ready.

| Website | Host URL | Emulated URL |
| --- | --- | --- |
| Marketplace | http://localhost:8449 | http://shop.com |
| Payment | http://localhost:8443 | http://payment.com |
| Bank | http://localhost:8444 | http://southbank.com |
| Bank staff | http://localhost:8446 | http://staff.southbank.com |
| Email | http://localhost:8445/webmail/ | http://mail.com/webmail/ |

| Account | Login | Password |
| --- | --- | --- |
| Marketplace administrator | `admin` | `ShopAdminDemo123!` |
| Marketplace customers/sellers | `alice@mail.com`, `bob@mail.com`, `carol@mail.com` | `ShopDemoPass123!` |
| Payment customers | Same emails | `PaymentDemo123!` |
| Bank customers | Same emails | `BankDemoPass123!` |
| Mailboxes | Same emails | `EmailDemo123!` |
| Payment administrator | `admin@payment.com` | `PaymentAdmin123!` |
| Email administrator | `admin@mail.com` | `MailAdminDemo123!` |
| Bank staff | `mifos`, tenant `default` | `password` |

1. Open the marketplace and sign in as Alice at **My account**. Browse Carol's
   digital products and Bob's Photo Tips. Add products to the cart and checkout.
2. Choose **Payment wallet or bank card**. The browser goes to Payment's checkout.
   Sign in as Alice and select **Payment balance**, then **Confirm payment**.
   Each payment wallet starts with USD 100.
3. Return to the shop. **My account → Orders** shows the paid order;
   **Downloads** provides the purchased content. Signing in as Carol or Bob at
   `/dashboard/orders` shows only that seller's part of the order.
4. To try a bank card, sign in to Payment normally and open **Bank cards**.
   Link Alice's South Bank card `9900010000000019`, authorize it in the bank
   and read the login code in Alice's mailbox. Then create another shop order,
   open Payment checkout and choose the linked card. Its bank balance decreases;
   Alice's Payment balance stays unchanged. Sellers receive their own amounts.
5. Register another user at `/my-account/`, open a store at `/store-registration/`,
   and connect a receiving wallet under **My account → Account details**.
   Use `/dashboard/products` to publish products. The receiving Payment account
   must already exist and be approved. See [H99](../H99_virtual_world/README.md)
   for runtime email, wallet and bank registration.

`shop.json` supplies the initial users, balances, stores and digital products.
Without `--state`, recompilation creates a fresh world. To resume saved data,
use `python3 shop.py --state .runtime/world` with state outside `output`.
Stop the stack with `docker compose down` before recompiling.
H20–H23, H99 and E99 share host ports; run one at a time.
