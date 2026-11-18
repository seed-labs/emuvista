# Payment application API

Use the payment user's existing OAuth bearer token. On the host, the accounting
base URL is `http://localhost:8443/accounting/SEED`; inside the emulator it is
`http://payment.com/accounting/SEED`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/bank/providers` | Available providers |
| POST | `/bank/links` | Begin user authorization: `{"bank":"south-bank","cardNumber":"9900010000000019","redirectURI":"http://localhost:8443/bank-accounts"}` |
| POST | `/bank/links/complete` | Complete authorization with callback `state` and `code` |
| GET | `/bank/sources` | List the user's linked cards and balances |
| POST | `/bank/links/remove` | Revoke and unlink one card by `id` |
| POST | `/bank/payments` | Make a bank-funded payment |
| GET | `/bank/payments` | Read outgoing and incoming card payment receipts |
| GET | `/bank/payments/{id}` | Read a receipt as its payer or recipient |

A bank-funded payment body contains `id` (a new UUID), `source` (from the sources
response), `payer` and `payee` (wallet account UUIDs), `amountMinor` (integer cents)
and `description`. Reuse the same ID and body if the response is lost; inspect
`status` before treating an operation as successful. `needs_review` requires
reconciliation, not a new payment attempt.

Card payments directly debit the card's bank account and credit the recipient
wallet. Receipts include `bankTransactionId` and `ledgerHash`; no intermediary
account or prefunded wallet is involved. The bank's own card-payment history and
core transaction note retain the actual recipient and payment platform.
The accounting backend periodically resumes unfinished requests without requiring
an agent or page read. A confirmed debit can finish after its card is unlinked. If an already signed
ledger credit expires before confirmation, it remains `needs_review` for manual
reconciliation; the backend does not create a replacement credit blindly.

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
