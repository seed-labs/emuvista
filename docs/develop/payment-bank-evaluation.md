# Payment and bank runtime evaluation

Evaluated on 2026-11-04/05 using synthetic accounts and isolated state, with earlier bank evaluation evidence included below. The bank core and payment ledger are retained. H23 remains an unpublished prototype. The initial comparison below predates the custom application implementation described next.

The target is a browser wallet and HTTP API with balances, payments, receipts, multiple accounts, currency conversion, user-initiated bank linking and eventual merchant checkout. Banking must retain deposits, withdrawals, savings interest and loans. Bank linking may be implemented; its absence alone does not disqualify a candidate.

## Recommendation

For independently operated payment and bank systems, **Komunitin + the existing Fineract bank** has demonstrated native cross-currency wallet transfers and payment links. These are useful existing features, but do not provide bank FX or automatic conversion between bank and wallet currencies. Both bank FX and cross-system conversion still need customer-facing business logic. Upstream user linking, authorized bank funding and reliable merchant orders require application development; the custom linking and funding implementation is described below.

**Mifos Pay + Fineract is a strong alternative**, especially if payment and banking may share one Fineract account backend. It already supports selecting a funding account. It is not necessary to build another ledger for that arrangement. However, two websites using one backend do not demonstrate an independent wallet charging an external bank account.

With separate wallet and bank backends, Mifos remains feasible and benefits from a common account-transfer API. Both independent combinations need cross-system coordination, customer linking, bank/cross-system FX and reliable merchant orders. Mifos additionally lacks the demonstrated native cross-currency wallet transfer. Their total implementation costs have not been measured; Komunitin's wallet FX feature alone does not establish that it requires less overall development.

## Custom application implementation (2026-11-05)

The customized payment and bank applications now implement user-initiated OAuth
linking and bank-funded transfers. A browser test completed payment login, bank
login with an actual email code, consent, callback and account listing. Native
payment confirmation offered wallet balance and the authorized bank account.

A 10 USD wallet payment and 25 USD bank payment left Alice's wallet at 90 USD,
checking at 975 USD, and the merchant at 35 USD. Replay did not debit twice;
changing a replay and using another customer's link were rejected. Additional
checks covered concurrent duplicate requests, negative amounts, unauthorized
access, a forged bank-account ID and insufficient funds. These are custom
application features, not claims about unmodified upstream software.

PaymentBundle deploys no bank adapter and imports no BankBundle. H23 configures
the independent applications through public deployment APIs. Bank/card networks,
bank FX, bank-to-wallet FX, automatic reconciliation and merchant order contracts
remain outside this implementation. Uncertain transfers require review.

The final official-base accounting image also passed saved-link access, OAuth
refresh, prior-receipt replay and another bank-funded payment. Session evidence
is recorded in `/tmp/emuvista-native-payment-evidence.json`,
`/tmp/emuvista-native-security-evidence.json` and
`/tmp/emuvista-final-image-evidence.json`. The test environment was stopped.

## Results

“Prototype” means custom integration, rather than an upstream feature. “API proof” means test code coordinated real native operations; it does not imply that the consumer application implements the workflow.

### Initial evaluation coverage

| Combination or attempt | Verification depth | Outcome |
| --- | --- | --- |
| Komunitin + existing Fineract bank | Native browser FX, merchant link, H23 prototype checkout and agent payments; earlier top-up/withdrawal API proofs | Financial operations passed; native user linking and reliable merchant orders remain missing |
| Mifos Pay + shared Fineract 1.12.1 | Native customer API flows and repaired browser payments from wallet/bank accounts | Passed financial checks; one shared backend, receipt UI still needs work |
| Independent Mifos wallet + existing Fineract bank | Browser login, separate databases, operator-coordinated native financial calls, emulator routing | Passed API feasibility; no consumer bank-linking feature implemented |
| Walleto + its own demo bank | Browser login, native card saving, bank funding, wallet transfer, withdrawal and bill-payment replay | Passed basic flows; demo bank and currency model do not establish full banking requirements |
| Komunitin + LibEuFin 1.4.0 | Earlier browser registration/transfer, agent checks and cross-system bank-funded payment | Passed basic financial proof; no equivalent full savings-interest/loan coverage established |
| Mifos Pay + current bank image directly | Customer endpoint compatibility | Required `/self` APIs unavailable in that core image |
| Mifos Pay + official self-service plugin on current/alternate bank cores | Actual container startup on two core versions | Both failed with the missing class described below |
| Open Bank Project | Earlier actual startup, bank-list API and direct login | API/login passed; no completed payment pairing or full banking workflow test |
| Walleto + Fineract | Source-level connector review only | Not dynamically connected; no claim of a successful pairing |
| Mifos Pay + LibEuFin | Earlier native Mifos customer endpoint compatibility probe | HTTP 404; no translated adapter or working UI pairing implemented |
| Mojaloop / Hyperswitch approaches | Static architecture review | Not deployed as complete wallet/bank combinations |

The two plugin/core attempts are compatibility variants, not two additional complete product combinations. Startup alone is not a successful financial integration.

| Capability | Komunitin + existing bank | Mifos Pay + shared Fineract | Mifos wallet + separate existing bank | Walleto + its demo bank |
| --- | --- | --- | --- | --- |
| Browser login and account view | Passed | Passed | Passed | Passed |
| Wallet payments and receipts | Native browser/API passed | Native API and repaired browser debit passed | Native customer API passed | Native API passed |
| Select bank account for payment | H23 prototype passed | Native source-account selector passed | API proof; no consumer integration | Top up first; no equivalent direct checkout tested |
| Bank-to-wallet / wallet-to-bank | Earlier API proofs passed; full consumer flow pending | Native customer API passed | Both API proofs passed | Both native API flows passed |
| User adds external bank/card after login | Not implemented | Internal accounts are not external bindings | Not implemented | Native saved-card record passed |
| One-time authority for later bank debits | Not implemented | Not needed for owned accounts within one core | Not implemented | Saved card is not a mandate; top-up requires PIN |
| Multiple currencies | Native cross-currency browser/API passed | Accounts available; native conversion rejected | Accounts available; native conversion rejected | Single wallet balance; currency model requires development |
| Deposits, withdrawals, interest and loans | Existing bank passed | Fineract capabilities; full bank UI pairing not retested on 1.12.1 | Existing bank retained; active loan verified | Demo bank is not an equivalent full banking application |
| External merchant payment handoff | Native payment link and merchant verification passed | No complete hosted-order workflow demonstrated | No complete hosted-order workflow demonstrated | Native bill payment passed; no complete hosted-order workflow |
| Paid-order replay protection | Native link paid twice | Not implemented as merchant-order contract | Not implemented as merchant-order contract | Same request key charged twice |

## Versions and compatibility

- Existing bank core: `apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7`, digest `sha256:e89e1e3108f3c8e692afbac30146a73fd04596e20058eb340c050e6cbebc9241`; existing customer/staff applications retained.
- Mifos-compatible wallet core: `apache/fineract:1.12.1`, digest `sha256:a83cf1980609c984281a4741344bfe1c6df8a0c2dcc0ae6cee337cded1dc53fe`. Its native customer API works after setting `FINERACT_MODULE_SELF_SERVICE_ENABLED=true` and enabling/configuring the scoped self-service role. No bank-core source change was needed.
- Mifos Pay: `main` source archive SHA-256 `a5d82e27aa7494639dddcaf6c196839b3d78f1d9a1f8a9e0c82421b21dc3154f`. The release source built and rendered without the development branch repairs.
- Komunitin: H20/H23 pinned application images; local source inspection snapshot `124a87b639c37952dc9a029fc7056e523a10de5b`. Existing experimental source files were not treated as unmodified upstream features.
- Walleto: local research source snapshot manifest SHA-256 `561a1ccae684fa4fb4b325437a094e63985d33edfd076bd14e6fa7e725d028b5`; original application sources, host-built artifacts packaged into local images. This is not a claim that an upstream prebuilt image was used.

The existing bank image does not expose the `/self` APIs required by Mifos Pay. Installing the evaluated official self-service plugin failed at startup with a missing `BccrExchangeRateService` class on both the current bank core and the additional `8e80aa6e85445c2a1e248152b4aa1c4d3072e541` core tested. This is a version compatibility failure, not evidence that all Mifos combinations are incompatible. Fineract 1.12.1 with its native module passed.

## What actually moved money

### Mifos Pay with one account backend

Normal customer credentials, without staff privileges, successfully performed:

1. Bank account to wallet: wallet `100 -> 110`, bank `1000 -> 990`.
2. Wallet payment of 5: wallet `110 -> 105`, merchant `0 -> 5`.
3. Bank-funded payment of 7: bank `990 -> 983`, merchant `5 -> 12`, wallet unchanged.
4. Wallet to bank: wallet `105 -> 102`, bank `983 -> 986`.

The customer could read only their own accounts; another customer's accounts were denied, as were staff APIs.

The release browser exposed a recipient-ID bug: beneficiary record ID `1` was used as destination account ID, although the merchant account ID was `6`. A temporary **13-line addition in one source file**, `TransferConfirmViewModel.kt`, resolved destination metadata using the native transfer template and account number. After rebuilding, browser wallet payment of 1 produced wallet `101`, bank `986`, merchant `13`; choosing bank account as the next payment source produced wallet `101`, bank `985`, merchant `14`. Both backend transactions returned HTTP 200 and were independently read back.

This measures a successful debit, not a polished release: after payment, the tested page retained its form and stale balance rather than showing a verified receipt. Additional presentation work remains. The browser also initially submitted the next calendar day relative to the core and was correctly rejected. Matching the test browser to the core's UTC date resolved that without another source change.

### Mifos wallet with an independent bank

A fresh `mini_internet.py` deployment used H21 email in AS150, the unchanged H22 bank in AS151, and an independent Mifos wallet core/database in AS152. Only browser gateways were published. An agent container in AS154 reached both systems through their emulator IPs.

Real native calls demonstrated wallet-only payment, bank-funded merchant payment, top-up and withdrawal with independent balances. For example, a bank-funded payment of 3 changed bank balance `1000 -> 997` and merchant wallet `2 -> 5`; the payer's wallet stayed at `98`. Settlement accounts recorded the opposite legs. Insufficient bank funds prevented wallet credit. The bank's initialized loan remained active with principal disbursed `500`; customer registration completed through H21 SMTP/IMAP.

These operations were coordinated by an **operator test program using privileged backend access**. They do not implement user binding, a reusable debit authority, crash recovery or atomic commitment across databases. Bank and wallet client IDs are local to each backend and must not be equated.

Both the current bank and the 1.12.1 wallet rejected direct transfers between different currencies with `error.msg.accounttransfer.different.currencies`. The current bank did support a quoted conversion expressed as two same-currency transfers in a native enclosing transaction; a failing second leg rolled back the first. That provides useful backend primitives, but does not supply a customer FX product or interface.

### Komunitin and merchant checkout

Native H20 browser payment transferred `1 NC` from Alice to Carol and credited `2 SC`. Same-currency and reverse cross-currency API transfers also passed, with converted value conserved. No application source changes were required for these features.

The H23 prototype passed wallet payment, bank-funded payment, duplicate-key handling, changed-body rejection, other-customer card denial and insufficient funds. An agent paid across AS154 -> payment AS152 -> bank AS151. Its predefined card mapping and custom checkout are **not native user enrollment** and must be replaced to meet that requirement.

A test merchant created a domain-registration order for 250 minor units, generated a native `/pay?c=...&a=250&m=order-reference` link, and opened it in the real wallet browser. After user confirmation, the merchant read the committed transfer under its own OAuth identity and verified recipient, amount and reference. However, reopening the already-paid link produced a second committed transfer. The native link is a useful handoff mechanism, not a reliable order database.

### Walleto

Original sources successfully registered a fresh user, saved a card, debited its demo bank to top up the wallet by 20, sent 5 to another wallet, and withdrew 5 to the bank. Bank database balances independently confirmed the funding legs. Browser login displayed the resulting balance of 10 after its balance animation completed. A wrong card PIN was rejected without crediting the wallet.

Native bill payment worked. Sending the same bill request twice with the same `Idempotency-Key` debited the wallet twice (`10 -> 8`). Currency conversion, multiple currency wallets, direct bank-funded checkout, reusable bank authorization and an external merchant order contract remain development work. Replacing its demo bank with Fineract additionally requires a bank connector. It therefore saves less of the required work than the other two wallet foundations.

### Earlier LibEuFin and bank comparisons

LibEuFin `1.4.0-0+noble` was actually deployed with PostgreSQL and its web UI. Browser registration and a transfer of 10 EUR changed Alice/Bob from `100/100` to `90/110`. An agent transfer also passed, along with duplicate-request deduplication, changed-request rejection, account ownership isolation and insufficient funds checks.

Komunitin + LibEuFin then passed a real cross-system funding proof: at an explicitly programmed simulation quote of `2 EUR = 1 NC`, Alice's bank account changed `93 -> 73 EUR`, Bob's wallet changed `60 -> 70 NC`, and Alice's own wallet remained `105 NC`. This was a native-API prototype with settlement accounts, not native card linking, automatic bank FX or a packaged checkout. Equivalent savings-interest and lending workflows were not established, so this proof does not justify replacing the fuller Fineract bank.

Earlier Komunitin + Fineract records also include successful API top-up and withdrawal, beyond the recent H23 checkout tests. Those were operator-driven proofs with no native customer binding UI.

Open Bank Project was started and returned HTTP 200 for its root/bank-list APIs and HTTP 201 for native direct login. No full payment combination was completed. Its [upstream project](https://github.com/OpenBankProject/OBP-API) describes a banking API platform; a successful startup does not demonstrate a complete replacement bank application.

## Application work still required

For either independent-wallet choice, implement these features in application source and build our own images. Bundles should supply addresses, trust and startup configuration; they should not own a separate payment business implementation.

1. **User linking:** the wallet starts a link request; the bank verifies account ownership once; the wallet stores a revocable, scoped bank-issued reference. Users may add several accounts later. No initial JSON card mapping and no stored bank administrator credentials in the browser.
2. **Authorized funding:** the bank accepts uniquely identified debit/refund requests under that reference and exposes operation status. The wallet records both transaction IDs, retries safely, and resolves partial or uncertain outcomes. This permits later payment without a fresh bank login for every purchase.
3. **Merchant orders:** an authenticated merchant creates an order with fixed recipient, amount and currency; the wallet returns a payment URL; the user selects balance or linked bank; the merchant queries authoritative paid status. A unique order may be paid once. A callback with retries can be added; a browser return URL alone is not proof of payment.
4. **FX in each scope:** distinguish wallet-to-wallet conversion, bank account conversion, and conversion during bank-to-wallet funding or bank-funded payment. Komunitin already demonstrates the first scope. Both combinations still need bank and cross-system quotes, conversion execution, settlement rules and user presentation; Mifos also needs cross-currency wallet transfer behavior. A fixed rate in test code is not a complete FX product. The chosen quote must determine the bank debit and wallet credit consistently, including any fee and expiry rules.

These are proposed contracts, not claims about existing endpoints. A simplified simulation authorization model is possible; implementing a full commercial card network is unnecessary for this evaluation.

## Other infrastructure considered

[Mojaloop's linking protocol](https://docs.mojaloop.io/technical/api/thirdparty/transaction-patterns-linking.html) is relevant to one-time consent and later third-party payments, but it is switch infrastructure requiring participating provider implementations. It does not supply this complete wallet/bank UI pair. It was reviewed statically rather than deployed as a substitute consumer application.

Hyperswitch provides processor orchestration and saved-payment-method mechanisms. It does not replace the required consumer balance wallet and full bank, and the simulated bank would still need a connector. It was not selected for another runtime deployment. Neither infrastructure option was rejected solely for lacking a particular consent screen.

## Evidence and scope

Raw scripts, screenshots, builds, the temporary source patch, logs and preserved trial state are under `/tmp/payment-bank-validation-20261104`. Key records: `core-evidence.json`, `legacy-customer-evidence.json`, `mifos-browser-ledger.json`, `independent-evidence.json`, `independent-agent-evidence.json`, `komunitin-fx-evidence.json`, `merchant-order-first-payment.json`, `merchant-replayed-link.log`, `walleto-evidence.json` and `walleto-order-evidence.json`. Temporary files are session evidence, not a committed reproducibility package. Evaluation containers were stopped after testing; state was preserved.

Earlier evidence is under `/tmp/bank-evaluation`: `libeufin-trial/transfer-evidence.json`, `libeufin-trial/agent-evidence.json`, `libeufin-trial/bridge-evidence.json`, `consumer-trial/bridge-evidence.json` and `obp-trial/startup-evidence.json`. These are earlier tests, not additional deployments in the November 4/5 run.

This evaluation establishes feasibility and remaining work. It does not deliver production user linking or an order service, prove lowest total future source changes, or test real card networks. No existing example was switched to Mifos, and no H23 content was pushed.

Upstream references: [Mifos Pay](https://github.com/openMF/mifos-pay), [Fineract Consumer Facing](https://github.com/apache/fineract-consumer-facing), [self-service plugin](https://github.com/openMF/selfservice-plugin), [Komunitin](https://github.com/community-exchange-network/komunitin), [Walleto](https://github.com/JayeshSuryavanshi/Walleto).
