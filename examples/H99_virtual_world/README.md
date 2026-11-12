# Virtual world

Email, payment and two banks on the shared [H00 mini Internet](../H00_mini_internet/), with DNSSEC.
H00 supplies an empty DNS root; `createworld` registers the application A and MX
records before rendering. Network placement stays in the example through SEED's
native `addInternalNetwork()` API.
Agents are added by [E99](../../experiments/E99_virtual_world_with_agents/).
Use the application images already required by H20–H22; customized images are in [docker_images](../../docker_images/README.md).

```sh
python3 virtual_world.py
cd output
docker compose build
docker compose up -d
```

| Application | Host URL | Access |
| --- | --- | --- |
| Payment | http://localhost:8443/login-mail | Register in the Payments community |
| South Bank | http://localhost:8444 | Register a new bank profile |
| North Bank | http://localhost:8447 | Register a new bank profile |
| Bank staff | http://localhost:8446 / http://localhost:8448 | `mifos` / `password`, tenant `default` |
| Webmail | http://localhost:8445/webmail/ | `admin@mail.com` / `MailAdminDemo123!` |
| Internet Map | http://localhost:8080 | — |

| Account | Password | Use |
| --- | --- | --- |
| `admin@payment.com` | `PaymentAdmin123!` | Built-in payment administrator |
| `admin@mail.com` | `MailAdminDemo123!` | Built-in mail administrator |
| `mifos` | `password` | Built-in administrator at both banks; tenant `default` |
| `bank@mail.com` | `BankMailDemo123!` | Shared bank sender mailbox |
| `payment@mail.com` | `PaymentMailDemo123!` | Payment registration and notification sender |

Wait for initializers before logging in. H99 starts infrastructure and administrator and sender
accounts only, with no residents or personal opening balances. `world.json` defines domains, bank products, sender mailboxes.
Administrator credentials are built into each Bundle. Personal mailboxes, wallet balances, bank
accounts and cards are declared in [E99 people.json](../../experiments/E99_virtual_world_with_agents/people.json).
Run E99 to initialize those residents and their Agents. Email initialization completes first. South Bank and North Bank then initialize
customers in order because they share the sender mailbox.

Inside the town, DNSSEC-backed DNS resolves these HTTP addresses:

| Application | Internal URL |
| --- | --- |
| Payment | http://payment.com |
| South Bank | http://southbank.com |
| North Bank | http://northbank.com |
| Webmail | http://mail.com/webmail/ |
| Bank staff | http://staff.southbank.com / http://staff.northbank.com |

`world.json` contains one entry per Bundle instance (`email`, `payment`,
`south-bank`, `north-bank`). Common fields have the same meaning:

| Field | Meaning |
| --- | --- |
| `hostname` | Internal service domain |
| `asn` | Deployment autonomous system; this example uses its `net0` network |
| `port` | Host browser port |
| `configuration` | Application configuration and institutional accounts |
| `connections` | Partner instance names, grouped by `email` or `bank` |

Bank-specific deployment fields include `name` and `staffPort`. Bank initialization
contains its sender mailbox. Connections do not require intermediary accounts or prefunded wallets.
Bundle types are defined once in `virtual_world.py`; JSON only supplies their settings.
Every bundle receives its domain through `setHostname()` and its business data
through `setInitialConfiguration()`.
There is no separate hostname map or bank list. DNS records and container
placement use the same per-instance settings.
Host access keeps the mapped ports above and does not require host DNS changes.

Payment **Bank cards** supports selecting a bank, entering a card number and
completing bank login/consent. Bank **Summary** and **Savings** show full card
numbers to their owner. Choose wallet balance or a linked card when paying.
No cards are prebound. See [payment-api.md](payment-api.md) for API use.

Card payments directly debit the selected bank account and credit the recipient
wallet in the same currency. The payer's wallet is unchanged. Bank history records
the payment platform, actual recipient, description and debit transaction ID.
Cross-currency card funding is not implemented.

## Create users while the world is running

1. **Email:** open <http://localhost:8445/admin/user/signup/mail.com>, choose an address
   and password, then use <http://localhost:8445/webmail/> to read verification messages.
2. **Payment:** open <http://localhost:8443/groups/SEED/signup>. Register, follow the
   confirmation email, log in and submit your member profile. The payment administrator
   opens `/groups/SEED/admin/accounts` and **Accepts** the member request. The wallet starts at zero.
3. **Bank:** open South Bank or North Bank and select **Register**. Enter your name,
   email and a password of 15–64 characters with uppercase, lowercase, a number and a symbol.
   Verify the email code, then log in using the next email code.
4. **Account and card:** open **Savings → Open account**, choose **USD** and submit.
   Open the new account, then choose **Apply for a debit card**. Accounts and cards
   are created immediately in this simulation; the opening balance is zero.
5. **Money:** bank staff log in with `mifos` / `password`, tenant `default`. Under
   **Institution → Clients**, select the person and savings account. Choose
   **Deposit**, enter e.g. `100`, select **Simulation**, and submit. This records a
   simulated cash deposit; it does not require another account to supply the money.
6. **Spend:** register and approve another payment user as the recipient. The payer
   opens **Bank cards** in Payment, selects the bank, enters the new card number and
   completes bank authorization. Pay the recipient with that card. A USD 10 payment
   from the USD 100 account leaves USD 90 at the bank and credits USD 10 to the
   recipient wallet; the payer wallet remains zero. The recipient can then pay from
   their wallet balance.

No JSON edits, recompilation or restart are needed for these operations. Users and
cards created at runtime remain in application state. Email links use localhost
when host access is enabled; inside the emulator, use the corresponding service
URL with the same path and token. E99 remains the optional way to initialize people
and run Agents automatically.

H99 loads `world.json` once. `createworld(state=None)` returns a native, unrendered
SEED `Emulator` and a separate Bundle map. Additional services can be added before rendering:

```python
emu, bundles = createworld()
emu.render()
emu.compile(createcompiler(bundles), "output", override=True)
```

World settings remain internal to H99. `createcompiler(bundles)` attaches containers to rendered
networks and registers them with the native Docker compiler. `emu.compile()` then
calls each Bundle's `configure()` and `install()`.
E99 supplies personal accounts through `EmailBundle.addUser`, `PaymentBundle.addUser`
and `BankBundle.addCustomer` before compilation. Agent setup,
tool registration and the experimental shop are in E99.

Each instance declares its partners in `world.json`, for example:

```json
"connections": {"email": ["email"]}
```

A payment instance uses `"connections": {"bank": ["south-bank", "north-bank"]}`.
Two separate passes read these lists and call:

```python
bank.connectEmail(email)
payment.connectBank(bank)
```

These calls record references. During `configure()`, the Bundles resolve mail
access, register OAuth clients and callbacks, configure direct debit and external credit, and generate browser URL mappings and readiness dependencies. Repeating
`connectBank()` adds another bank; repeating `connectEmail()` adds another mailbox
provider. Multiple payment instances can connect to the same bank; each receives
its own client ID, secret and callbacks. Users still link their own cards through
login and consent. No concrete instance pairing is hardcoded in Python.

Without `--state`, compilation starts fresh. `--state .runtime/world` preserves
bank, email, wallet and DNS state. Stop the world with `docker compose down`
before recompiling. H99 and E99 use the same host ports; run one at a time.

After upgrading from the intermediary-account payment version, regenerate the
deployment with fresh state. Rebuild the four customized application images
listed in [docker_images](../../docker_images/README.md), then rebuild the generated
Compose services before starting.
