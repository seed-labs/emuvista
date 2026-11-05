# Payment application API

Use the payment user's existing OAuth bearer token. On the host, the accounting
base URL is `https://localhost:8443/accounting/SEED`; inside the emulator it is
`https://10.152.0.10:2025/SEED`. Accept the laboratory certificate.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/bank/providers` | Available providers |
| POST | `/bank/links` | Begin user authorization: `{"bank":"seed-bank","redirectURI":"https://localhost:8443/bank-accounts"}` |
| POST | `/bank/links/complete` | Complete authorization with callback `state` and `code` |
| GET | `/bank/sources` | List the user's linked accounts and balances |
| POST | `/bank/links/remove` | Disconnect a link by `id` |
| POST | `/bank/payments` | Make a bank-funded payment |
| GET | `/bank/payments` | Read the user's payment history |

A bank-funded payment body contains `id` (a new UUID), `source` (from the sources
response), `payer` and `payee` (wallet account UUIDs), `amountMinor` (integer cents)
and `description`. Reuse the same ID and body if the response is lost; inspect
`status` before treating an operation as successful. `needs_review` requires
reconciliation, not a new payment attempt.

Wallet-funded payments use the existing native accounting transfer API. Bank
account authorization uses the bank's OAuth flow and requires the customer to
sign in and consent initially. Provider credentials stay on the servers.
