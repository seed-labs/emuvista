# PaymentService

Deploys Komunitin from prebuilt images with a web wallet, HTTP APIs and a local Stellar ledger. Payment containers share the bound SEED host's network namespace through `Docker.addContainerBundle()`.

## Usage

Add to a topology containing Base, Routing and a host:

```python
from seedemu.core import Binding, Filter
from seedemu.compiler import Docker, Platform
from services.PaymentService import PaymentService

payment = PaymentService()
wallet = payment.install('wallet')
wallet.setAdminCredentials('admin@payment.example', 'replace-with-your-password')
wallet.setSavePath('./payment-state')
wallet.enableHostAccess(8443)
# Optional: wallet.setInitialData('/path/to/user-data.zip')

emu.addLayer(payment)
emu.addBinding(Binding('wallet', filter=Filter(asn=150, nodeName='host_0')))
emu.render()

compiler = Docker(platform=Platform.AMD64)
compiler.addContainerBundle(payment.getContainerBundle(emu))
emu.compile(compiler, './output', override=True)
```

Run `docker compose build` and `docker compose up -d` in the output directory. Database migrations and administrator setup run automatically. No sample accounts, balances or community rules are included.

One payment deployment is allowed per physical host. See the [H20 example](../../examples/H20_payment_service/README.md).

## Images

The default `h20-*` tags are locally prepared artifacts, not published public images. Komunitin revision: `124a87b639c37952dc9a029fc7056e523a10de5b`. Tested on Linux AMD64.

```sh
docker load -i /path/to/payment-images.tar
```

Override references with `PaymentService(images={role: reference})` or `payment.setImage(role, reference)`. Overrides must preserve these image interfaces:

| Role | Required interface |
| --- | --- |
| `app` | Built web app on port 80; runtime API URL configuration |
| `auth`, `social`, `accounting`, `notifications-ts` | `/app/dist/index.mjs` and Prisma migration CLI |
| `cli` | Node 24 and `/app/shared/cli/index.ts` with dependencies |
| `database` | PostgreSQL 16, `gosu`, `init-app-db.sh`, PostGIS, pgvector and Social extensions |
| `stellar` | Local Quickstart with `--local --enable core,horizon` and persistent storage |
| `files` | S3rver 3.7.1 CLI |
| `redis` | Redis 7 |
| `gateway` | nginx with `http_sub_module` for host browser URL rewriting |

The archive contains payment images only. SEED prepares its own network node images.

## State and initialization

Call `setInitialData(path_or_bytes)` before `emu.render()` to configure an optional Komunitin migration ZIP. Compilation writes it into the output and, when persistence is enabled, saves a copy with the state. The import runs on first startup. `setSavePath(path)` persists all databases, the local ledger, files, credentials, certificates and initialization records together.

Keep state outside the compilation output. Reusing it requires the same server address, administrator and initial data. Without `setSavePath()`, data lives under the output directory and is lost when that directory is overwritten. Recreate the entire Compose stack together because containers share a network namespace.

## Endpoints

`enableHostAccess(port=8443)` publishes `https://localhost:<port>` for a host browser, including Windows with WSL. This endpoint proxies the web app and APIs together; emulated endpoints remain unchanged. Accept the local self-signed certificate in the browser.

| HTTPS port | Endpoint |
| --- | --- |
| 443 | Web wallet |
| 2026 | Authentication |
| 2028 | Communities and members |
| 2025 | Balances and transfers |
| 2023 | Notifications |
| 9191 | Uploaded files |

Certificates are self-signed for the bound IP. Internal database and ledger ports are blocked from other SEED nodes. Public domains, external banking, production email and push delivery are not configured.
