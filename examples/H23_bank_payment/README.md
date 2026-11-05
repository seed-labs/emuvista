# Bank and payment

Independent email, bank and payment bundles on the shared [H00 mini Internet](../H00_mini_internet/) with DNSSEC.
Build the four customized [application images](../../docker_images/README.md) first.

```sh
python3 bank_payment.py
cd output
docker compose build
docker compose up -d
```

Accept the laboratory certificates. First startup creates the configured accounts.

| Website | URL | Login |
| --- | --- | --- |
| Payment | https://localhost:8443/login-mail | `alice@seed.example` / `PaymentDemo123!` |
| Bank | https://localhost:8444 | `alice@seed.example` / `BankDemoPass123!` |
| Bank administration | https://localhost:8446 | `mifos` / `password`, tenant `default` |
| Webmail | https://localhost:8445/webmail/ | `alice@seed.example` / `EmailDemo123!` |
| Internet Map | http://localhost:8080 | — |

Bob uses `bob@seed.example` with the same respective passwords. Bank login uses
email codes. There are no prelinked customer accounts.

1. Log in to Payment and open **Bank accounts** from the menu.
2. Select **Connect**. Sign in at the bank, retrieve the email code in Webmail,
   and authorize account access and payments. The browser returns to Payment.
3. Create a payment to **SEED Shop**. Choose wallet balance or a linked bank
   account on the confirmation page.
4. Check the resulting balances and transactions in Payment and Bank.

Alice starts with 100 USD in her wallet and 1,000 USD in checking. A 10 USD
wallet payment reduces her wallet to 90 USD. A subsequent 25 USD bank payment
reduces checking to 975 USD, leaving her wallet at 90 USD. The shop receives 35 USD.

Edit `scenario.json` for accounts, balances and settlement settings. The example
registers an API client at the bank and passes its connection settings to the
payment application. Each customer links their own accounts through the websites.
PaymentBundle does not import BankBundle or deploy a bank adapter.

Bank funding currently uses matching USD accounts and a prefunded settlement
wallet. Cross-currency bank funding and real card-network processing are not
implemented. Bank debits and wallet transfers commit separately; an uncertain
operation is marked `needs_review` and requires reconciliation. Do not retry it
with a new payment ID.

Without `--state`, compilation starts fresh. Use `--state ./demo-state` to save
and resume the same experiment. Keep state outside `output`. Stop the environment
with `docker compose down` before recompiling. See [api.md](api.md) for agent calls.
