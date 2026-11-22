# H24: Live Stock Market Trade

H24 runs an LLM-driven order and settlement cycle through Stock Service and QuantReplay. Alice, Bob, and Carol each run as an independent agent process on their own SeedEmu node and use a separate Stock account:

1. Alice owns one `AMZ` share and rests a sell limit order at **$11.00**.
2. Bob owns one `AMZ` share and rests a cheaper sell limit order at **$10.00**.
3. Carol has **$50.00** in her Stock cash account and submits a buy limit order at **$10.50**.

Carol's buy crosses both asks. QuantReplay matches Bob's lower-priced ask first, at Bob's resting price of **$10.00**. Bob's share moves to Carol, Bob receives $10.00, Carol's cash falls by $10.00, and Alice's $11.00 order remains open. The browser dashboard reads the live order book, fills, and ownership from Stock Service; it is not a replay fixture.

The dashboard and `GET /api/v1/market/AMZ` show the best bid, best ask, and latest trade price from the simulated market. Prices appear as agents post orders and execute trades.

At startup, H24 deploys BankBundle and EmailBundle alongside Stock Service. The private setup controller creates and verifies each Stock account, signs each agent in to its matching bank account, completes card-scoped consent, and links the debit card. It then provisions each account key to that agent's own SeedEmu node and discards its in-memory copy. An account without an active bank link cannot submit orders. Carol's $50 demo buying power is debited from her bank card into her Stock cash account; it is not minted by the controller. The dashboard shows both linked bank balance and Stock cash balance. **No agent submits an order until you click “Start agent actions.”** After your click, the controller signals Alice's VM, Bob's VM, and Carol's VM in that order. Each VM reads its own account and market state, asks the LLM for a decision, and submits through Stock Service using its own account key. The model receives only the assigned task and observations; an order is accepted only if it matches the scenario's side, quantity, and price limits. Stock Service routes accepted orders to QuantReplay over FIX.

The LLM endpoint must support OpenAI-compatible Chat Completions tool calls and be reachable from the Docker runner. Configure it in `examples/H24_stock_market/.env` using [.env.example](.env.example). Keep the API key out of source control. The AMZ instrument is part of QuantReplay's bundled demo market data. H24 disables QuantReplay's random order generator for AMZ so only Alice, Bob, and Carol affect this demonstration's AMZ order book; the other bundled instruments retain their generated activity. Carol's opening Stock cash is funded by a direct debit from her linked BankBundle card.

## Build and run

Docker Desktop must be running. QuantReplay's published Market Simulator image targets AMD64. On an ARM Mac, Docker Desktop may run the AMD64 containers through emulation.

From the repository root, install the published SeedEmu 2.0.0 package into an H24 virtual environment:

```sh
python3 -m venv examples/H24_stock_market/.venv
examples/H24_stock_market/.venv/bin/python -m pip install seedemu==2.0.0 -r requirements.txt
```

Build the Stock Service image from the repository root:

```sh
docker build -t emuvista/stock-api:0.1.0 services/StockService
```

Compile the SEED deployment using that environment:

```sh
examples/H24_stock_market/.venv/bin/python -E examples/H24_stock_market/scenario.py
```

Copy the sample model configuration and fill in your provider's key and model name:

```sh
cp examples/H24_stock_market/.env.example examples/H24_stock_market/.env
```

Build and start the generated deployment:

```sh
cd examples/H24_stock_market/output
docker compose up -d --build
docker compose logs -f h24-demo-runner
```

The setup controller waits for the FIX session and BankBundle, verifies the three Stock accounts, links each account to its agent's debit card, deposits Carol's $50 opening cash from her bank card, seeds Alice and Bob's shares, provisions each VM with its owner's account key, and waits for your approval. Open the live market dashboard at <http://localhost:8765/?live=1&symbol=AMZ>. Confirm the empty AMZ order book and each agent's bank and Stock cash balances, then click **Start agent actions** to let the three VM-hosted agents begin. The page refreshes the order book, holdings, balances, and action progress. Open the SEED Internet Map at <http://localhost:8080/> to inspect the running topology, including Alice, Bob, and Carol's nodes. Stop the deployment with `docker compose down` from the output directory.

To restore the same initial market before another presentation, run the H24-specific reset script:

```sh
bash examples/H24_stock_market/reset-demo.sh
docker compose -f examples/H24_stock_market/output/docker-compose.yml logs -f h24-demo-runner
```

The reset removes Stock and QuantReplay demo state and reinitializes H24 Bank's customer/transaction databases and Redis from the seeded balances. It retains the Bank configuration and credentials plus Email mailbox data, refreshes and rebuilds only the H24 controller and agent images, then starts the deployment without rebuilding BankBundle or Mailu. This gives Carol the same starting bank balance and a fresh, account-scoped deposit request on each run. Wait for the runner to report `Ready`, then use **Start agent actions** on the dashboard.

To choose another QuantReplay image tag, pass `--quantreplay-tag TAG` to `scenario.py`. Use `--output PATH` or `--host-port PORT` to change the generated directory or dashboard port. Recompile H24 to start with a fresh temporary Stock database.

## Topology

H24 uses one emulated network, `AS250/net0` (`10.250.0.0/24`). Alice's agent VM (`10.250.0.90`), Bob's agent VM (`10.250.0.91`), Carol's agent VM (`10.250.0.92`), Stock Service, QuantReplay, BankBundle, EmailBundle, the private setup controller, the dashboard, and the Internet Map container (`10.250.0.82`) share that network. The Internet Map displays the three agent VMs as separate nodes. Only the dashboard (`8765`) and Internet Map (`8080`) are exposed on localhost; the agent control endpoints, runner, Stock API, Bank API, and mailbox stay on the emulated network.

The setup controller uses the Stock Service API and BankBundle's existing customer-card APIs only to prepare the demonstration. Each agent VM then uses its own verified account key to read its account and place orders. Bank card balances are read through scoped Open Banking consent. A bank debit funds Stock cash; Stock Service then reserves the buyer's Stock cash or seller's shares before sending each order to QuantReplay. A confirmed fill debits/credits the Stock cash ledger, while cancellation or rejection releases any remaining Stock-side reserve. BankBundle currently provides direct debit, not bank-account holds: the order reserve is held in the Stock cash ledger. The FIX initiator uses the bundled FIXT.1.1 and FIX 5.0 SP2 dictionaries to decode QuantReplay's contra-party group in execution reports.
