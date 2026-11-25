# H24: Live Stock Market Trade

H24 demonstrates both ways agents can buy simulated AMZ shares. Alice, Bob, and Carol each run on their own SeedEmu node and use separate Stock accounts linked to their H24 Bank debit cards.

1. Each demo Bank account starts with $20,000. The runner verifies each Stock account and deposits $10,000 from its linked Bank card, leaving $10,000 in the Bank account. The one-share order limits stay within the buyer's demo budget. The three agents start with zero shares. The runner waits for you to click **Start agent actions**.
2. Alice's VM buys one AMZ share directly from Stock Service at the latest AMZN market trade price. Alice's LLM chooses a virtual sell limit.
3. Bob's VM buys one AMZ share the same way. Bob's LLM chooses a different virtual sell limit.
4. Carol's LLM inspects both asks and chooses a one-share bid high enough for both. QuantReplay matches the cheaper ask at its resting price. The higher ask remains open, the winning seller receives cash, and Carol receives the share.

The dashboard's latest trade, best bid, best ask, and spread come from Alpaca. The order book, trade tape, and holdings show the simulation. H24 maps QuantReplay's bundled `AMZ` instrument to `AMZN` and disables random orders for `AMZ`. The agents' virtual order limits are chosen in each run.

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

Configure the OpenAI-compatible model in `examples/H24_stock_market/.env`, using [the example file](.env.example) if needed. Stock Service reads Alpaca credentials from `examples/H24_stock_market/.env.market`, which is ignored by Git. Create that file with these values:

```dotenv
STOCK_ALPACA_API_KEY=your-key-id
STOCK_ALPACA_API_SECRET=your-secret
STOCK_ALPACA_FEED=iex
```

Alpaca's IEX feed covers one exchange. Set `STOCK_ALPACA_FEED=sip` when your account has access to real-time consolidated US quotes. To run the complete demonstration, the Stock API must receive a usable AMZN trade price from Alpaca. When trades are infrequent or the market is closed, the service uses the last reported trade and shows its original timestamp. The default 120-second window applies to the last successful provider check.

Build and start the generated deployment:

```sh
cd examples/H24_stock_market/output
docker compose up -d --build
docker compose logs -f h24-demo-runner
```

Wait until the runner reports `Ready`, then open the [market dashboard](http://localhost:8765/?live=1&symbol=AMZ). Confirm that it shows an AMZN price, a recent provider check, and an empty virtual book. Open the [SEED Internet Map](http://localhost:8080/pro/map) to inspect the three agent nodes, then click **Start agent actions** on the dashboard. The action log shows the system purchases and chosen limits. The trade tape shows the final virtual execution. Stop the deployment with `docker compose down` from the output directory.

To restore the same initial market before another presentation, run the H24-specific reset script:

```sh
bash examples/H24_stock_market/reset-demo.sh
docker compose -f examples/H24_stock_market/output/docker-compose.yml logs -f h24-demo-runner
```

The reset removes Stock and QuantReplay demo state and reinitializes H24 Bank's customer/transaction databases and Redis from the seeded balances. It retains the Bank configuration and credentials plus Email mailbox data, refreshes and rebuilds only the H24 controller and agent images, then starts the deployment without rebuilding BankBundle or Mailu. This restores the same starting cash and zero holdings for each agent. Live prices and LLM-selected limits can differ between runs. Wait for the runner to report `Ready`, then use **Start agent actions** on the dashboard.

To choose another QuantReplay image tag, pass `--quantreplay-tag TAG` to `scenario.py`. Use `--output PATH` or `--host-port PORT` to change the generated directory or dashboard port. Recompile H24 to start with a fresh temporary Stock database.

## Optional direct Alpaca route on macOS

The Stock Service image uses its normal network by default. The macOS relay is useful on Docker Desktop when the host's VPN or TUN proxy interferes with the Alpaca connection.

From the repository root, start the relay in a terminal:

```sh
python3 examples/H24_stock_market/alpaca_relay.py --interface en0
```

The relay listens on Mac loopback at port `18790` and accepts HTTPS tunnels to `data.alpaca.markets:443`. Change `--interface` if your physical network uses another interface. The relay queries the interface's IPv4 gateway for DNS by default. Supply `--dns-server` if that gateway does not provide DNS.

Add this optional setting to your local `.env.market` alongside your Alpaca credentials:

```dotenv
STOCK_ALPACA_HTTPS_PROXY=http://host.docker.internal:18790
```

If the H24 deployment is already running, recreate its Stock API to pick up this setting:

```sh
cd examples/H24_stock_market/output
docker compose up -d --no-deps --force-recreate h24-stock-api
```

Keep the relay running while using this setting. Stock Service uses it only for Alpaca. TLS remains end-to-end between Stock Service and Alpaca. Deployments that can already reach Alpaca can leave the proxy setting blank.

## Topology

H24 uses one emulated network, `AS250/net0` (`10.250.0.0/24`). Alice's agent VM (`10.250.0.90`), Bob's agent VM (`10.250.0.91`), Carol's agent VM (`10.250.0.92`), Stock Service, QuantReplay, BankBundle, EmailBundle, the private setup controller, the dashboard, and the Internet Map container (`10.250.0.82`) share that network. The Internet Map displays the three agent VMs as separate nodes. Only the dashboard (`8765`) and Internet Map (`8080`) are exposed on localhost; the agent control endpoints, runner, Stock API, Bank API, and mailbox stay on the emulated network.

The setup controller uses the Stock Service API and BankBundle's existing customer-card APIs only to prepare the demonstration. Each agent VM then uses its own verified account key to read its account and place orders. Bank card balances are read through scoped Open Banking consent. A bank debit funds Stock cash; Stock Service then reserves the buyer's Stock cash or seller's shares before sending each order to QuantReplay. A confirmed fill debits/credits the Stock cash ledger, while cancellation or rejection releases any remaining Stock-side reserve. BankBundle currently provides direct debit, not bank-account holds: the order reserve is held in the Stock cash ledger. The FIX initiator uses the bundled FIXT.1.1 and FIX 5.0 SP2 dictionaries to decode QuantReplay's contra-party group in execution reports.
