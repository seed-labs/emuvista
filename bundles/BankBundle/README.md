# BankBundle

Apache Fineract with customer and Mifos staff websites, PostgreSQL databases, Redis and account initializer. Each container uses a SEED IP and the emulated router. SMTP/IMAP are supplied by an independent mailbox service.

```python
from bundles.BankBundle import BankBundle

emu.render()
bank = BankBundle(emu, resolver='10.150.0.54')
bank.setInitialConfiguration('bank.json')
bank.addInternalNetwork('151', 'net0',
    [f'10.151.0.{i}' for i in range(10, 10 + len(bank.getContainers()))], '10.151.0.254')
bank.setEmailServer('mail.seed.example', 'bank@seed.example',
    'replace-with-your-password', 'email/config/cert.pem')
bank.enableHostAccess(8444, staff_port=8446)
# Optional: bank.setSavePath('./bank-state')
compiler.addContainerBundle(bank)
```

When using EmailBundle in the same compilation, add it to the compiler before BankBundle. Relative certificate paths resolve in the compiler output directory. The mail certificate is trusted explicitly by both Java SMTP and Python IMAP clients; certificate and hostname verification remain enabled.

`setInitialConfiguration(path_or_dict)` accepts savings products and customers with accounts, opening balances and optional loans. Customer `email` and `password` configure bank access. `emailPassword` lets the initializer complete native registration using that customer's real IMAP mailbox. Examples supply all identities and balances; the library supplies no sample customers. Existing passwords and mail are retained on resume.

`getAPIConnection()` exports staff API access. `getInitialAccount(id)` returns account ownership and currency metadata without customer passwords.

`registerAPIClient(client_id, redirect_uris, settlement_account)` enables an OAuth client for customer-authorized account access and payments. Call it after configuring initial accounts. `getOpenBankingConnection()` exports its server-side connection settings, certificate reference and readiness dependencies after network and state configuration. Registration does not link customer accounts. Customers sign in and consent through the bank website. BankBundle has no dependency on a payment bundle.

The nine component roles are `gateway`, `core`, `core-db`, `bff`, `bff-db`, `frontend`, `redis`, `initialize`, `staff`, in address order. The customer gateway and staff website publish browser ports on `127.0.0.1`; other components stay inside the emulator. Pass `staff_port=None` to omit the staff host port. Emulated clients use HTTPS on the gateway IP: customer APIs at `/api/v1/` and staff APIs at `/fineract-provider/api/v1/`. The staff IP serves the management website and the same staff API.

Without `setSavePath`, recompilation creates fresh storage outside `output`. Saved state includes both databases, Redis, initialization records, database credentials, JWT keys and TLS certificates. Stop the stack before recompiling, and resume with the same configuration and addresses. Existing eight-component saved deployments can add the staff address without resetting their bank data.

Build the customized customer images from [docker_images](../../docker_images/README.md): `handsonsecurity/emuvista-bank-consumer:1.0` and `handsonsecurity/emuvista-bank-frontend:1.0`. Sources use revision `ce2621c0fe76c28f58de5cf5627c49f20f5980ca`. The core image remains `apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7`.

The staff website uses the public `openmf/web-app:1.14` image, pinned by digest in `DEFAULT_IMAGES`. It connects to the bundle's Fineract through its own HTTPS proxy; no external demo backend is used. PostgreSQL, Redis, nginx and Python also use public images. Override references with `BankBundle(emu, images={role: reference})`. See [H22](../../examples/H22_bank_service/README.md) for browser operations and the complete bank and email example.

Customers may include `cards`: each entry has a unique `id`, `number` (16–19 digit
simulated Luhn-valid number), `name`, `account` (one of that customer's account IDs),
`expires` (`YYYY-MM`) and optional `status` (`active` or `blocked`). Cards are
initialized in the bank database; balances remain in their linked Fineract
accounts. Multiple cards can reference separate accounts or the same account.
The bank checks holder identity, expiry, status and card-scoped consent on access
and payment. Existing configurations without cards retain basic banking. See
[H99](../../examples/H99_virtual_world/) for multi-bank, multi-card usage.

The customer website shows configured card numbers on Summary, Savings and account
detail pages, with a copy button. `GET /api/v1/cards` returns only the signed-in
bank customer's cards and their account numbers, balances, status and expiry.
Payment authorization APIs continue to expose masked card numbers. Account
numbers and card numbers are separate identifiers; multiple cards may share one
account.
