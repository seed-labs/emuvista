# Bank service

Apache Fineract banking on the shared [H00 mini Internet](../H00_mini_internet/), using H21 email records and H00 DNSSEC for real verification emails.

```sh
python3 bank.py
cd output
docker compose build
docker compose up -d
```

The [prepared bank images](../../services/BankService/README.md) must be available. First startup creates products, customers, accounts and loans, then verifies customer registration through SMTP/IMAP. The gateway starts after initialization completes.

| Website | Address | Login |
| --- | --- | --- |
| Customer bank | https://localhost:8444 | `alice@seed.example` / `BankDemoPass123!` |
| Bank administration | https://localhost:8446 | `mifos` / `password` (tenant `default`) |
| Webmail | https://localhost:8445/webmail/ | `alice@seed.example` / `EmailDemo123!` |
| Internet Map | http://localhost:8080 | — |

Accept the laboratory certificates. Bob uses `bob@seed.example` with the same respective passwords. Bank login and transfers require codes from the user's mailbox.

Edit [bank.json](bank.json) to configure users, mailbox passwords, products, opening balances and loans. Alice starts with USD 1,000 checking, USD 200 savings at 3% annual interest, EUR 300 checking and a disbursed USD 500 loan. Bob starts with USD 500 checking. Default loans use 12 monthly installments at 1% interest per month.

Try these customer operations:

1. Log in, read the verification email in Webmail and enter its code. Open **Savings** to inspect balances, interest rates and transaction history.
2. Open **Transfers → Transfer Money** to move USD between Alice's accounts. Confirm with the new email code.
3. Under **Beneficiaries**, add Bob using office `Head Office` and account number `000000004` in a fresh default deployment. Verify the email code, then select Bob when making a transfer.
4. Open **Loans** to inspect the loan and repayment schedule. **Make payment** repays from a savings account and requires another email code.
5. **Apply for a Loan** lets the customer select a product, preview a schedule and submit an application. Approve and disburse the application on the administration website.

Use the administration website for staff operations:

1. Log in with `mifos` / `password`, tenant `default`, and close the welcome warning. Open **Institution → Clients**, then select **Alice Example**.
2. Under **Saving Accounts**, click the checking account number. Open the action menu at the upper right of the account card and choose **Deposit** or **Withdrawal**. Enter an amount, select payment type **Simulation**, and submit. **Transactions** shows the entry and updated balance.
3. Return to Alice's client page and open the pending application under **Loan Accounts**. In its action menu, choose **Approve**, check the date and amount, and submit. Open the menu again and choose **Disburse**. **Disburse to Savings** is a separate action when the loan has a linked savings account.
4. Open an active loan to inspect its repayment schedule and transactions. Product and staff settings are available under **Admin**.

The two bank websites share the same Fineract accounts and loans. Customer access uses email codes; staff access uses the separate administrator credentials above. See [API examples](api.md) for agent access.

Agents use the internal bank gateway `10.151.0.10` and mailbox front `10.150.0.10`. The staff website uses `10.151.0.18`. Application browser ports bind to localhost; Internet Map uses port 8080. H22 includes its own full mini Internet and mailbox deployment; run it separately from the other examples to avoid duplicate node container names and ports.

Without `--state`, compiling starts fresh. From the example directory, use `python3 bank.py --state ./bank-state` to save and resume bank, email and DNS keys with the same configuration and addresses. Keep this directory outside `output` and stop containers before recompiling.

USD/EUR accounts are separate balances: native transfers require the same currency. Currency conversion, investments and payment-system integration are outside this example.
