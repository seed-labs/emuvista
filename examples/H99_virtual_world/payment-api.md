# Payment application API

Use the payment user's existing OAuth bearer token. On the host, the accounting
base URL is `https://localhost:8443/accounting/SEED`; inside the emulator it is
`https://10.152.0.10:2025/SEED`. Accept the laboratory certificate.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/bank/providers` | Available providers |
| POST | `/bank/links` | Begin user authorization: `{"bank":"seed-bank","cardNumber":"9900010000000019","redirectURI":"https://localhost:8443/bank-accounts"}` |
| POST | `/bank/links/complete` | Complete authorization with callback `state` and `code` |
| GET | `/bank/sources` | List the user's linked cards and balances |
| POST | `/bank/links/remove` | Revoke and unlink one card by `id` |
| POST | `/bank/payments` | Make a bank-funded payment |
| GET | `/bank/payments` | Read the user's payment history |

A bank-funded payment body contains `id` (a new UUID), `source` (from the sources
response), `payer` and `payee` (wallet account UUIDs), `amountMinor` (integer cents)
and `description`. Reuse the same ID and body if the response is lost; inspect
`status` before treating an operation as successful. `needs_review` requires
reconciliation, not a new payment attempt.

Wallet-funded payments use the existing native accounting transfer API. Bank
card authorization uses the bank's OAuth flow and requires the customer to sign
in and consent initially. Provider credentials stay on the servers.

Request the `email accounting:read accounting:write` scopes when obtaining a
payment token. Binding reads the verified email claim, never a caller-supplied
owner identity. `/bank/sources` exposes only explicitly bound cards and masked
numbers. A `source` is one card binding, not a bank or account identifier.

The bank endpoints are `POST /api/v1/openbanking/account-access-consents/cards`,
`GET /api/v1/openbanking/cards/current` and
`POST /api/v1/openbanking/cards/current/revoke`. Card grants have
`openbanking:cards.read openbanking:payments` scopes. Payments specify `cardId`;
the bank resolves the debit account from its own card record and rejects another
card or account. Unlinking revokes that consent at the bank.

Card consent cannot request `openbanking:accounts.read` or other broader scopes.

For agents, the world tool `world.link_card` composes the existing payment and bank
clients, selects an owned card by bank and full card number, completes customer
login/OTP/consent, and returns the linked source ID. Agents use `payment.cards`,
`payment.card_payment` and `payment.card_payments` for funding and receipt checks.
Each bank's advertised browser origin is translated to its configured internal
address; authorization callbacks are validated and never followed across origins.
