# Virtual world

Email, payment and two banks on the shared [H00 mini Internet](../H00_mini_internet/), with DNSSEC.
Agents are added by [E99](../../experiments/E99_virtual_world/).
Use the application images already required by H20–H22; customized images are in [docker_images](../../docker_images/README.md).

```sh
python3 virtual_world.py
cd output
docker compose build
docker compose up -d
```

| Application | Host URL | Demo login |
| --- | --- | --- |
| Payment | https://localhost:8443/login-mail | `alice@seed.example` / `PaymentDemo123!` |
| SEED Bank | https://localhost:8444 | `alice@seed.example` / `BankDemoPass123!` |
| North Bank | https://localhost:8447 | Same bank credentials |
| Bank staff | https://localhost:8446 / https://localhost:8448 | `mifos` / `password`, tenant `default` |
| Webmail | https://localhost:8445/webmail/ | `alice@seed.example` / `EmailDemo123!` |
| Internet Map | http://localhost:8080 | — |

Accept laboratory certificates. Wait for initializers before logging in.
Alice, Bob, Carol, Dave and Erin have individual mailboxes, bank accounts and payment
wallets. Dave also has an initialized loan. Identities, balances and cards are in `world.json`.

Payment **Bank cards** supports selecting a bank, entering a card number and
completing bank login/consent. Bank **Summary** and **Savings** show full card
numbers to their owner. Choose wallet balance or a linked card when paying.
No cards are prebound. See [payment-api.md](payment-api.md) for API use.

Banking card funding uses matching USD balances and prefunded
settlement wallets; cross-currency card funding is not implemented.

`build_world()` returns an unrendered `VirtualWorld`. Experiments add their agents
and bindings, then call `world.compile(...)`. No world topology is copied into E99.
H99 contains no framework-specific code.

Without `--state`, compilation starts fresh. `--state .runtime/world` preserves
bank, email, wallet and DNS state. Stop the world with `docker compose down`
before recompiling. H99 and E99 use the same host ports; run one at a time.
