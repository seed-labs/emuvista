# Payment Service

Deploys Komunitin on the B00 mini Internet using prebuilt images. Requires Linux AMD64, SEED Emulator with `Docker.addContainerBundle()`, and the [payment images](../../services/PaymentService/README.md#images).

## Configure users

Edit `users.json` before compiling. Each entry creates an active wallet with its initial balance:

```json
[
  {"name": "Alice", "email": "alice@h20.example", "password": "payment-demo", "balance": 100},
  {"name": "Bob", "email": "bob@h20.example", "password": "payment-demo", "balance": 50}
]
```

The example automatically creates the `SEED` community, currency, approved users and initial funding records. No email verification or manual group setup is required. Ordinary wallets cannot spend below zero. The administrator's treasury wallet records the corresponding negative issued amount.

## Run

Install [requirements.txt](../../requirements.txt) once from the repository root. `bcrypt` hashes configured passwords for Komunitin's import format.

From this directory:

```sh
python3 payment.py
cd output
docker compose build
docker compose up -d
```

## Access

Open <https://localhost:8443/login-mail> from the host browser, including Windows with WSL. Accept the self-signed certificate and log in with a configured email and password.

Use **Transfers → Create transfer → Send / Receive** to pay or request payment. The default Coffee Shop wallet can receive merchant payments.

Administrator: `admin@h20.example` / `h20-experiment-admin-password`. Community accounts and transactions are available at `/groups/SEED/admin/accounts` and `/groups/SEED/admin/transactions`.

Emulated clients use `https://10.150.0.71` and API ports 2026 (authentication) and 2025 (accounting).

## Options

| Argument | Description |
| --- | --- |
| `--users PATH` | Initial users JSON; defaults to `users.json` beside the script |
| `--topology mini\|compact` | B00 network (default), or three ASes with the wallet at `10.210.0.71` |
| `--output PATH` | Compilation directory; defaults to `output/` |
| `--state PATH` | Persistent payment state, including cached initialization data |
| `--host-port PORT` | Host browser HTTPS port; defaults to `8443` |
| `--images PATH` | JSON overrides for prebuilt images |
| `--initial-data PATH` | Advanced: supply a Komunitin ZIP instead of `users.json` |

Use `python3 payment.py --state .runtime/payment-state` to preserve progress across recompilation. Restarting does not replay initial allocations. Changing `users.json` requires a new state directory; existing passwords and balances are not overwritten.

Without `--state`, overwriting `output/` removes its data. Recreate the complete Compose stack together. Initial user configuration belongs to this example; PaymentService only deploys and imports the supplied bundle.
