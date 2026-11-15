# PaymentBundle

Deploys Komunitin from prebuilt images. Each component has its own container and SEED network IP. No Service layer or virtual-node binding is required.

## Usage

Create the bundle after rendering the emulator:

```python
from seedemu.compiler import Docker, Platform
from bundles.PaymentBundle import PaymentBundle

emu.render()

payment = PaymentBundle(emu)
payment.addInternalNetwork(
    asn='150', network_name='net0',
    ip_addresses=[f'10.150.0.{i}' for i in range(10, 24)],
    default_route='10.150.0.254',
)
payment.enableHostAccess(8443)
payment.setInitialConfiguration('groups.json')
# Optional: payment.setSavePath('./payment-state')

compiler = Docker(platform=Platform.AMD64)
compiler.addContainerBundle(payment)
emu.compile(compiler, './output', override=True)
```

Run `docker compose build` and `docker compose up -d` in `output/`. Compilation creates routing wrappers for the prepared images; building installs `iproute2` when absent. Startup sets each container's default route through the emulated router. No application source checkout is needed.

The network must already exist and its addresses must be free. Without an explicit network, the bundle reserves 14 free addresses on a rendered host network. To place a component elsewhere, call `payment.getContainer(role).joinInternalNetwork(network, hostname, ip_address, default_route)` before compilation. Remaining components use the default network.

Addresses are assigned in this order:

| Offset | Component |
| --- | --- |
| 0–5 | `gateway`, `app`, `auth`, `social`, `accounting`, `notifications-ts` |
| 6–9 | `db-auth`, `db-social`, `db-accounting`, `db-notifications` |
| 10–13 | `redis`, `stellar`, `files`, `initialize` |

`payment/deployment.json` records the resulting addresses and state directory. Give additional bundles distinct `name` values. See the [H20 example](../../examples/H20_payment_service/README.md) for JSON initialization and payments.

## Access

| Built-in administrator | Password |
| --- | --- |
| `admin@payment.com` | `PaymentAdmin123!` |

Administrator credentials are fixed; no credential setter is exposed.

Only the gateway publishes a host port: `127.0.0.1:8443`. It serves the web app and proxies browser API calls. Other containers have no host port mappings. A Node startup adapter translates browser-provided localhost resource links into the emulated gateway IP before the accounting backend fetches them. Component connections use emulated IPs; loopback is used only for checks and operations within one container.

Emulated clients use the gateway over HTTP: port 80 for the web app, 2026 for authentication, 2028 for communities, 2025 for accounting, 2023 for notifications and 9191 for files. `setHostname(name)` selects a canonical domain; configure its DNS record separately and supply `resolver=` to the bundle. Without a hostname, URLs use the gateway IP.

`enableHostAccess(port, url_mappings={internal_origin: host_origin})` rewrites linked application origins on the host-facing endpoint while internal clients retain their domain URLs.

## Initialization and state

`setInitialConfiguration(path_or_dict)` accepts a JSON file or a Python dictionary with `groups` and optional `trustlines`. Each group defines `code`, `name`, `currency` (`name`, `symbol`, `rate`) and `users` (`name`, `email`, `password`, `balance`). Trustlines define `from`, `to` and `limit`, measured in the source currency. Omit `users` when there are no personal wallets, and `trustlines` when no exchange is needed. See [groups.json](../../examples/H20_payment_service/groups.json) for a complete configuration.

The API validates and copies the configuration. Compilation generates the import data; first startup creates the communities, users, balances and exchange relationships automatically. The bundle includes no sample users, balances or exchange rules. It supports two decimal places for balances and amounts; exchange rates are fixed values relative to a common reference unit. `bcrypt` from the root requirements is needed when generating initial passwords.

`getInitialAccountId(group, email)` resolves an initialized wallet before compilation.

For an existing Komunitin migration ZIP, use `setInitialData(path_or_bytes)` instead. Calling either initialization setter replaces the other input. Both initialization and state paths may be set before compilation in either order.

Without `setSavePath()`, every compilation uses fresh temporary runtime storage outside `output/`. With it, all databases, ledger data, credentials and initialization records are saved together. Keep this directory outside `output/`; resume with the same addresses, administrator and initial data. State from the previous shared-network layout requires a new experiment directory.

## Application configuration

`connectBank(bank)` records a partnership and can be repeated for multiple banks.
It does not configure either application. During `configure()`, the Bundle obtains
each bank's connection, generates provider JSON, readiness dependencies and host
browser URL mappings. Bank registration uses the payment application's own
client ID and internal/host browser callbacks. PaymentBundle does not import
BankBundle or create bank containers.

Card payments require matching bank and wallet currencies. The bank returns a
recipient-bound debit receipt; the payment ledger then credits the recipient
using its existing asset issuer, without debiting another wallet or prefunding
an intermediary account. Receipts retain the actual payer wallet as business
identity, bank transaction ID and ledger hash. A saved signed transaction is
reused during recovery so another credit is not created after an uncertain reply.
Incoming credits are visible on the Bank cards page and through payment receipt
and history tools. A backend recovery loop resumes unfinished requests independently
of agents; receipt queries remain read-only. Retrying uses the same ID and body.

`configureApplication(role, environment=..., files=..., dependencies=...)`
passes settings to a deployed application. Text files are mounted read-only under
`/payment-config`; dependencies are healthy Compose service names.
No other bundle type is required.

## Registration email

`payment.connectEmail(email)` records an outbound mail partnership. Declare a
sender mailbox named `<payment-instance-name>@<first-email-domain>` in that EmailBundle,
or pass its address as `payment.connectEmail(email, 'sender@mail.com')`.
Configuration resolves SMTP credentials and waits for mailbox initialization.
Without a mail connection, outgoing messages remain local development artifacts.

Users register at `/groups/<code>/signup`, confirm the email and submit their member
profile. A community administrator accepts the request at `/groups/<code>/admin/accounts`.
New wallets have zero balance. H99 includes this mail connection and its sender.

## Images

Requires Linux AMD64 and SEED Emulator's ContainerBundle API. Build the customized `app` and `accounting` images using [docker_images](../../docker_images/README.md). The remaining payment components use the existing prepared images. To load their archive:

```sh
docker load -i /path/to/payment-images.tar
```

Override images with `PaymentBundle(emu, images={role: reference})` or `payment.setImage(role, reference)`.

| Image role | Required interface |
| --- | --- |
| `app` | nginx web app and `/docker-entrypoint.sh` with runtime API configuration |
| `auth`, `social`, `accounting`, `notifications-ts` | `/app/dist/index.mjs` and Prisma migration CLI |
| `cli` | Node 24 and `/app/shared/cli/index.ts` with dependencies |
| `database` | PostgreSQL 16, `gosu`, `init-app-db.sh`, PostGIS, pgvector and Social extensions |
| `stellar` | `/start --local --enable core,horizon` with persistent storage |
| `files` | `/s3/node_modules/s3rver/bin/s3rver.js` |
| `redis` | Redis 7 and `docker-entrypoint.sh` |
| `gateway` | nginx with `http_sub_module` and `/docker-entrypoint.sh` |

Images must support running the routing wrapper as root and provide `ip`, or an Alpine/Debian package manager to install it. Original prepared components use revision `124a87b639c37952dc9a029fc7056e523a10de5b`; customized image sources and pinned upstream bases are recorded in [sources.json](../../docker_images/sources.json).

## Agent tools

Before compilation, `payment.addUser(group_code, user)` adds an initial wallet
to a configured community. The user fields are `name`, `email`, `password` and `balance`.

Exports wallet balance/transfers, supported banks, linked cards, card-funded
payments and payment receipts, plus native wallet transfer receipt/history queries. Card payments use a linked source ID and an
idempotent operation UUID; only `completed` confirms success. The package's
`client.py` provides payment API calls for composing authorization workflows.
Bank customer login and consent remain in the bank package.

`payment.getAgentTools()` exports the package and private instance settings:
the service origin and initialized groups' email-to-wallet mappings. AgentService
stores these separately in `context.tool_config['payment']`. Personal
`accounts.payment` contains the group and password, with an optional `instance`
selector; the email defaults to the person's mailbox. Tools resolve account IDs
and API endpoints themselves. The model supplies a recipient email and amount;
service routing data never enters its persona or prompt.
