# BankBundle

Apache Fineract with customer and Mifos staff websites, PostgreSQL databases, Redis and account initializer. Each container uses a SEED IP and the emulated router. SMTP/IMAP are supplied by an independent mailbox service.

| Built-in administrator | Password | Tenant |
| --- | --- | --- |
| `mifos` | `password` | `default` |

Administrator credentials are fixed.

```python
from bundles.BankBundle import BankBundle

emu.render()
bank = BankBundle(emu, resolver='10.150.0.54')
bank.setInitialConfiguration('bank.json')
bank.addInternalNetwork('151', 'net0',
    [f'10.151.0.{i}' for i in range(10, 10 + len(bank.getContainers()))], '10.151.0.254')
bank.connectEmail(email)
bank.enableHostAccess(8444, staff_port=8446)
# Optional: bank.setSavePath('./bank-state')
compiler.addContainerBundle(bank)
```

Here `email` is an existing EmailBundle. Add it to the compiler before BankBundle.
`connectEmail(email, username=None)` records a mail partnership; during `configure()`,
BankBundle obtains its exported SMTP/IMAP connection and initializer dependency.
Call it again to add another mail provider. The first supplies outgoing SMTP;
initial customer verification chooses IMAP by the customer's email domain. The
sender defaults to `sender` in bank initialization data, or `bank@<first domain>`.
Banks sharing a sender initialize in order automatically. BankBundle does not
import EmailBundle; mail providers export domains, mailbox access and SMTP
connections. Mail clients use authenticated SMTP on 587 and IMAP on 143.

For an external server, use `connectEmail(host, username, password, port=587,
imap_port=143, initializer=None)` with its connection settings.

`setHostname(name)` selects the customer/API domain; configure DNS separately.
Customer and staff websites use HTTP. Host-mapped browser access remains available.

`setInitialConfiguration(path_or_dict)` accepts savings products and customers with accounts, opening balances and optional loans. Omit `customers` when there are no personal accounts. Customer `email` and `password` configure bank access. `emailPassword` lets the initializer complete native registration using that customer's real IMAP mailbox. Examples supply all identities and balances; the library supplies no sample customers. Existing passwords and mail are retained on resume.

`getAPIConnection()` exports staff API access. `getInitialAccount(id)` returns account ownership and currency metadata without customer passwords.

`payment.connectBank(bank)` records both sides of a partnership, using
`bank.connectPayment(payment)` internally. During `configure()`, BankBundle
registers the client's callbacks and OAuth access. `getOpenBankingConnection()` exports the
resulting connection to the payment application; pass its client ID when there
are multiple partners. Client configurations are generated separately in
`payment-clients.json`. Card payments directly withdraw from the authorized
bank account; no destination bank account or intermediary customer is created.
The Bundle classes do not import
one another. No customer card is linked by this declaration: users still sign in
and consent through the bank website.

Multiple payment partnerships require rebuilding the customized bank consumer
image, whose bootstrap reads the generated client list. Each debit records its
actual recipient, platform and description in bank history and the core
transaction note. Customers can read `/api/v1/card-payments`; third parties can
query their own debit at `/api/v1/openbanking/payments/{id}`.

The nine component roles are `gateway`, `core`, `core-db`, `bff`, `bff-db`, `frontend`, `redis`, `initialize`, `staff`, in address order. The customer gateway and staff website publish browser ports on `127.0.0.1`; other components stay inside the emulator. Pass `staff_port=None` to omit the staff host port. Emulated clients use HTTP on the gateway IP: customer APIs at `/api/v1/` and staff APIs at `/fineract-provider/api/v1/`. The staff IP serves the management website and the same staff API.

Without `setSavePath`, recompilation creates fresh storage outside `output`. Saved state includes both databases, Redis, initialization records, database credentials, JWT signing keys. Stop the stack before recompiling, and resume with the same configuration and addresses. Existing eight-component saved deployments can add the staff address without resetting their bank data.

Build the customized customer images from [docker_images](../../docker_images/README.md): `handsonsecurity/emuvista-bank-consumer:1.0` and `handsonsecurity/emuvista-bank-frontend:1.0`. Sources use revision `ce2621c0fe76c28f58de5cf5627c49f20f5980ca`. The core image remains `apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7`.

The staff website uses the public `openmf/web-app:1.14` image, pinned by digest in `DEFAULT_IMAGES`. It connects to the bundle's Fineract through its own HTTP proxy; no external demo backend is used. PostgreSQL, Redis, nginx and Python also use public images. Override references with `BankBundle(emu, images={role: reference})`. See [H22](../../examples/H22_bank_service/README.md) for browser operations and the complete bank and email example.

Customers may include `cards`: each entry has a unique `id`, `number` (16–19 digit
simulated Luhn-valid number), `name`, `account` (one of that customer's account IDs),
`expires` (`YYYY-MM`) and optional `status` (`active` or `blocked`). Cards are
initialized in the bank database; balances remain in their linked Fineract
accounts. Multiple cards can reference separate accounts or the same account.
The bank checks holder identity, expiry, status and card-scoped consent on access
and payment. Existing configurations without cards retain basic banking. See
[H99](../../examples/H99_virtual_world/) for multi-bank, multi-card usage.

The customer website shows card numbers on Summary, Savings and account
detail pages, with a copy button. `GET /api/v1/cards` returns only the signed-in
bank customer's cards and their account numbers, balances, status and expiry.
Payment authorization APIs continue to expose masked card numbers. Account
numbers and card numbers are separate identifiers; multiple cards may share one
account.

## Agent tools

Before compilation, `bank.addCustomer(customer)` adds an initial customer using
the same fields as an entry in the initial configuration's `customers` list.

Customer tools accept an optional configured `bank` alias. The persona's
`accounts.bank` maps aliases to personal bank profiles and passwords.
`bank.getAgentTools()` exports instance URLs and the OTP sender separately;
AgentService merges these into `context.tool_config['bank']` by alias.
`tools/client.py` combines these settings with personal credentials for email-OTP login and card-specific OAuth
consent; composed callers keep authorization codes private. Loan tools are not implemented.

## Runtime registration and accounts

The customer website's **Register** page creates a new bank customer and uses the
existing email OTP flow. No customer ID or initial JSON entry is needed. After
verification and login, **Savings → Open account** opens an empty account; the
account detail page has **Apply for a debit card**. Several accounts and cards may
belong to the same customer. Existing customer identity registration remains at
`/register-existing`.

The simulation approves and activates new accounts immediately. Opening an
account or issuing a card never deposits funds. Staff use the existing Fineract
**Deposit** action with payment type **Simulation** to put money into an account.

| API | Request |
| --- | --- |
| `POST /api/v1/registration/open` | `firstName`, `lastName`, `email`, `password` |
| `POST /api/v1/registration/otp/send` | `registrationId`, `deliveryMethod: "email"` |
| `POST /api/v1/registration/otp/verify` | `registrationId`, `token` |
| `GET /api/v1/customer-accounts/products` | Authenticated customer's product list |
| `POST /api/v1/customer-accounts` | `id` (UUID), `productId` |
| `POST /api/v1/cards` | `id` (UUID), `accountId` |

Account/card requests use the customer's normal bank session and device fingerprint.
Reuse the same UUID and body after an uncertain response; another application uses
a new UUID. Ownership is checked by the backend. The corresponding Agent tools are
`bank.products`, `bank.open_account` and `bank.issue_card`; they use each Agent's own
verified customer login.
