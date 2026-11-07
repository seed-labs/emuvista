# Payment Bundle

Deploys Komunitin on the shared [H00 mini Internet](../H00_mini_internet/) using [prebuilt images](../../bundles/PaymentBundle/README.md#images). Requires Linux AMD64, SEED Emulator's ContainerBundle API and the root [requirements.txt](../../requirements.txt). `bcrypt` hashes initial passwords.

## Configure

Edit `groups.json` to define communities, currencies, users and initial balances. For one community without exchange, keep one group and set `trustlines` to `[]`.

| Community | Login | Initial balance |
| --- | --- | --- |
| North (`NORT`, NC) | `alice@north.example` | 100 NC |
| North (`NORT`, NC) | `bob@north.example` | 50 NC |
| South (`SOUT`, SC) | `carol@south.example` | 50 SC |
| South (`SOUT`, SC) | `dave@south.example` | 20 SC |

All passwords are `payment-demo`. Each community has its own treasury and transaction history. Users are active immediately and cannot spend below zero.

`currency.rate` sets a currency's value against a common reference unit: North is `2`, South is `1`, so **1 NC = 2 SC**. Amounts support two decimal places. `trustlines` enables exchanges between communities; its `limit` is measured in the `from` community's currency and does not add money to user wallets.

## Run

Stop any previous stack with `docker compose down` in its output directory. From this example directory:

```sh
python3 payment.py
cd output
docker compose build
docker compose up -d
```

Open <https://localhost:8443/login-mail>, accept the self-signed certificate and log in as Alice. This also works from the Windows host with WSL.

Internet Map: <http://localhost:8080>. Run one mini Internet example at a time.

## Try payments

Use **Transfers → Create transfer → Send**, choose a recipient, enter a description and amount, then send and confirm. The community name above the recipient list switches the recipient's community.

Run these two payments in order from Alice's North wallet:

1. **Same currency:** select Bob in **North Community** and pay **10 NC**. Alice now has **90 NC** and Bob has **60 NC**. No conversion occurs.
2. **Cross currency:** select **South Community**, choose Carol and pay **10 NC**. The form shows **20 SC** for Carol. Alice now has **80 NC**; Carol has **70 SC**.

Log in as Bob or Carol to check the receipts. A payment of **10 SC** from Carol to Alice gives Alice **5 NC**. Use **Receive** to request a payment.

The backend permits one login to own wallets in multiple communities, but the current web app selects only the first membership and has no wallet switcher. This example uses separate users so every wallet is usable from the browser without modifying Komunitin.

Administrator: `admin@h20.example` / `seed1234`. Community accounts and transactions are available at `/groups/NORT/admin/accounts` and `/groups/NORT/admin/transactions`; replace `NORT` with `SOUT` for South.

## Network and initialization

PaymentBundle is configured after `emu.render()` and registered with the Docker compiler. Each component owns an emulated IP (`10.150.0.10`–`10.150.0.23`). Only the web gateway maps to the host at `127.0.0.1:8443`. Emulated clients use `https://10.150.0.10`, with API ports 2026 for authentication and 2025 for accounting.

The example passes `groups.json` to `payment.setInitialConfiguration(...)`. PaymentBundle handles validation, initial data generation and exchange setup automatically. An empty `trustlines` list skips exchange setup.

## Options

| Argument | Description |
| --- | --- |
| `--config PATH` | Community configuration; defaults to `groups.json` beside the script |
| `--output PATH` | Compilation directory; defaults to `output/` |
| `--state PATH` | Optional directory to save and resume payment state |
| `--host-port PORT` | Host browser HTTPS port; defaults to `8443` |
| `--images PATH` | JSON overrides for prebuilt images |
| `--initial-data PATH` | Advanced: supply a Komunitin ZIP instead of generating it from JSON |

Without `--state`, each compilation starts fresh. To save progress, use `python3 payment.py --state .runtime/payment-state` and reuse that path later. Initial balances are not replayed. Changing the JSON or network layout requires a new state directory. Keep state outside `output/` and stop containers before recompiling.
