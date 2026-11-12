# Customer API

Customers and agents use the same API as the browser. Requests go to `http://10.151.0.10/api/v1` inside the emulator, or `http://localhost:8444/api/v1` on the host. Use a persistent cookie jar and one `X-Device-Fingerprint` value for the session.

From the example directory, begin a login:

```sh
curl -c cookies.txt -b cookies.txt \
  -H 'Content-Type: application/json' -H 'X-Device-Fingerprint: agent-alice-1' \
  -d '{"email":"alice@mail.com","password":"BankDemoPass123!"}' \
  http://localhost:8444/api/v1/authentication/login
```

Read the new verification email through IMAP at `10.150.0.10:143` using Alice's email credentials. Submit the returned `challengeToken` and the email code:

```sh
curl -c cookies.txt -b cookies.txt \
  -H 'Content-Type: application/json' -H 'X-Device-Fingerprint: agent-alice-1' \
  -d '{"challengeToken":"<login challenge>","token":"<email code>"}' \
  http://localhost:8444/api/v1/authentication/2fa
```

Continue with the same cookies and fingerprint. For authenticated writes, also send `Origin: http://localhost:8444` on the host, or `Origin: http://10.151.0.10` inside the emulator.

| Method and path | Purpose |
| --- | --- |
| `GET /savings` | List the customer's accounts |
| `GET /savings/{id}` | Inspect an owned account |
| `GET /loans` | List the customer's loans |
| `POST /beneficiaries/initiate` | Begin adding another customer's account |
| `POST /beneficiaries/confirm` | Confirm with its step-up token and email OTP |
| `POST /transfers/initiate` | Begin a transfer or loan repayment |
| `POST /transfers/confirm` | Confirm with a new email OTP and `Idempotency-Key` |

A transfer initiation body is:

```json
{"fromAccountId":1,"toAccountId":2,"toAccountType":"SAVINGS","amount":1.11}
```

Confirm by resending those fields with `stepUpToken` from the initiation response and `otp` from the new email. Supply a unique `Idempotency-Key`. For repayment, use `toAccountType: "LOAN"` and the loan ID. Discover IDs from the account/loan lists; the values above apply to a fresh default deployment. Do not reuse login or earlier operation codes.

Adding Bob uses `name`, `officeName`, `accountNumber` and `transferLimit` at `/beneficiaries/initiate`; confirmation repeats them with `stepUpToken` and `otp`. Account access and source-account ownership are enforced by the native bank application. Staff operations use the separate Fineract API below; browser instructions are in the [README](README.md).

## Staff API

Use `http://10.151.0.18/fineract-provider/api/v1` inside the emulator, or `http://localhost:8446/fineract-provider/api/v1` on the host. The customer gateway also retains its staff API route. Staff authenticate with native HTTP Basic credentials and a tenant header:

```sh
curl -u mifos:password \
  -H 'Fineract-Platform-TenantId: default' \
  http://localhost:8446/fineract-provider/api/v1/clients
```

Deposits and withdrawals use `POST /savingsaccounts/{id}/transactions?command=deposit` or `command=withdrawal`. Loan approval and disbursement use `POST /loans/{id}?command=approve` or `command=disburse`. The administration website uses these same endpoints.
