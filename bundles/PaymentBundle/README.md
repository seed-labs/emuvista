# PaymentBundle

Deploys Komunitin from prebuilt images. Each component has its own container and SEED network IP. No Service layer or virtual-node binding is required.

## Usage

Create the bundle after rendering the emulator:

```python
from seedemu.compiler import Docker, Platform
from bundles.PaymentBundle import PaymentBundle

emu.render()

payment = PaymentBundle(emu)
payment.setDefaultInternalNetwork(
    name='net_150_net0',
    ip_addresses=[f'10.150.0.{i}' for i in range(10, 24)],
    default_route='10.150.0.254',
)
payment.setAdminCredentials('admin@payment.example', 'replace-with-your-password')
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

Only the gateway publishes a host port: `127.0.0.1:8443`. It serves the web app and proxies browser API calls. Other containers have no host port mappings. A Node startup adapter translates browser-provided localhost resource links into the emulated gateway IP before the accounting backend fetches them. Component connections use emulated IPs; loopback is used only for checks and operations within one container.

Emulated clients use the gateway IP over HTTPS: port 443 for the web app, 2026 for authentication, 2028 for communities, 2025 for accounting, 2023 for notifications and 9191 for files. Accept the self-signed certificate. Backend APIs, databases and ledger services also remain reachable at their own emulated IPs.

## Initialization and state

`setInitialConfiguration(path_or_dict)` accepts a JSON file or a Python dictionary with `groups` and `trustlines`. Each group defines `code`, `name`, `currency` (`name`, `symbol`, `rate`) and `users` (`name`, `email`, `password`, `balance`). Trustlines define `from`, `to` and `limit`, measured in the source currency. Use an empty trustline list for a standalone community. See [groups.json](../../examples/H20_payment_service/groups.json) for a complete configuration.

The API validates and copies the configuration. Compilation generates the import data; first startup creates the communities, users, balances and exchange relationships automatically. The bundle includes no sample users, balances or exchange rules. It supports two decimal places for balances and amounts; exchange rates are fixed values relative to a common reference unit. `bcrypt` from the root requirements is needed when generating initial passwords.

`getInitialAccountId(group, email)` resolves an initialized wallet before compilation.

For an existing Komunitin migration ZIP, use `setInitialData(path_or_bytes)` instead. Calling either initialization setter replaces the other input. Both initialization and state paths may be set before compilation in either order.

Without `setSavePath()`, every compilation uses fresh temporary runtime storage outside `output/`. With it, all databases, ledger data, credentials and initialization records are saved together. Keep this directory outside `output/`; resume with the same addresses, administrator and initial data. State from the previous shared-network layout requires a new experiment directory.

## Application configuration

`configureApplication(role, environment=..., files=..., trusted_certificates=..., dependencies=...)`
passes settings to a deployed application. Text files are mounted read-only under
`/payment-config`; dependencies are healthy Compose service names. Certificate paths
resolve from compiler output. No other bundle type is required.

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

Exports wallet balance/transfers, supported banks, linked cards, card-funded
payments and payment receipts, plus native wallet transfer receipt/history queries. Card payments use a linked source ID and an
idempotent operation UUID; only `completed` confirms success. The package's
`client.py` provides payment API calls for composing authorization workflows.
Bank customer login and consent remain in the bank package.
