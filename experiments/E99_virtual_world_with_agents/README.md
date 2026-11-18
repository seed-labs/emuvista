# Life in the virtual world

Adds five continuously running residents to [H99](../../examples/H99_virtual_world/).
Each has their own email, wallet and bank account, with the same available tools.
[people.json](people.json) describes personalities and personal accounts, without
assigned purchases or required transactions. Carol runs a digital shop; the other
residents decide whether to buy. The framework is selected through its deployment integration.

```sh
# First run only:
cp .env.example .env
# Fill LLM_API_KEY, LLM_BASE_URL and LLM_MODEL.
python3 virtual_world_with_agents.py
cd output
DOCKER_BUILDKIT=0 docker compose build
cd ..
python3 start.py
```

The entrypoint requires `.env` in this directory and reports an error if it is missing.

`start.py` starts infrastructure, waits for initializers and healthy services,
then starts residents. It reads the generated Compose file and Bundle deployment
records directly. The main entrypoint only compiles the world. All services belong to
the default Compose project; no profile is required. Use this script for startup:
plain `docker compose up -d` skips state preparation.
For manual inspection between stages, use `--infrastructure-only`, then
`--agents-only` when ready.

By default, each `docker compose down` followed by `python3 start.py` starts a
fresh world with the configured users, initial balances and empty resident memory.
The script clears temporary application data and initialization markers before
starting new containers. Existing images and credentials are reused;
no rebuild is needed. Retrying a partial startup or running `--agents-only` does
not reset that run.

To preserve the world, choose a state directory when generating it:

```sh
python3 virtual_world_with_agents.py --state .runtime/world
```

Build this generated deployment once, then use the same `start.py` and
`docker compose down` commands. Bank, payment and email data, resident memories
and marketplace orders survive removal of the containers. Logs remain inside containers.
`start.py` supplies saved-memory mounts through `output/docker-compose.agents.yml`;
the compiled Compose file remains unchanged. Plain `docker compose down` still stops the whole project.
Reusing the same `--state` directory when regenerating also preserves application
credentials. Regeneration can change image contents; build again
after regenerating or changing code.

Stop an existing deployment before recompiling. Existing deployments need
regeneration, rebuilt agent images and recreated agent
containers to use the new behavior. Keep your existing `.env`. The model endpoint
must support Chat Completions tool calling and be reachable from the simulated
network. E99 enables H00's optional external IPv4 gateway. Set `LLM_BASE_URL`
to your model server's reachable IPv4 address, such as `http://<server-ip>:8000/v1`.
`localhost` refers to the Agent container. External model domains are not forwarded
to public DNS. API keys stay in the read-only runtime environment file. Restart
agents after changing its values.

From `experiments/E99_virtual_world_with_agents`, start the observer:

```sh
python3 monitor.py
```

Open **http://localhost:8090** to see current intentions, thinking, tool calls,
rest periods, wake times, reflections and failures. Select an agent and tool, then
a call to inspect all business arguments and full results. Email bodies have a
readable preview. Passwords, verification codes and access tokens stay hidden.
The observer reads events and business orders, not framework memory. Historical
details absent from events cannot be reconstructed. Closing the observer leaves
the world running. Use `--port 8091` if its default port is occupied. Older running
images still show their earlier behavior until rebuilt and recreated.

## Resident behavior

Residents choose their own actions from observations, memories and interests.
They can communicate, agree on exchanges, transfer money, explore services or rest.
After the initial infrastructure readiness gate, residents discover later service
changes themselves and can return after a failure. There is no repeated task prompt
or requirement to wait for every service in each waking moment.

`life.rest` lets a resident choose when to return. The native LangGraph resident
graph contains a LangChain conversation subgraph, persists state using SQLite
checkpoints, waits and continues. Framework summarization manages context growth;
no external process issues recurring tasks. Model connection failures back off,
and application failures become observations rather than blind retries.

Checkpoints live in `/home/emuvista-agent/state/langgraph.sqlite`. Memory survives
a restart of the same container; `--state` also preserves it across recreation.
Without that option, removing containers discards their memory. Legacy JSON memory
files are retained but not imported. Shop orders are business records, not memory.

| Resident | Account email | Mail password | Payment password | Bank password |
| --- | --- | --- | --- | --- |
| Alice | `alice@mail.com` | `EmailDemo123!` | `PaymentDemo123!` | `BankDemoPass123!` |
| Bob | `bob@mail.com` | `EmailDemo123!` | `PaymentDemo123!` | `BankDemoPass123!` |
| Carol | `carol@mail.com` | `EmailDemo123!` | `PaymentDemo123!` | `BankDemoPass123!` |
| Dave | `dave@mail.com` | `EmailDemo123!` | `PaymentDemo123!` | `BankDemoPass123!` |
| Erin | `erin@mail.com` | `EmailDemo123!` | `PaymentDemo123!` | `BankDemoPass123!` |

| System account | Password | Use |
| --- | --- | --- |
| `admin@payment.com` | `PaymentAdmin123!` | Payment administrator |
| `admin@mail.com` | `MailAdminDemo123!` | Mail administrator |
| `mifos` | `password` | Administrator at both banks; tenant `default` |
| `bank@mail.com` | `BankMailDemo123!` | Shared bank sender mailbox |

Internal service domains are `payment.com`, `mail.com`, `southbank.com` and
`northbank.com`. Administrator credentials are fixed by the Bundles.

Assembly keeps people and infrastructure independent:

```python
people = createpeople("people.json")
emu, systems = createworld()  # H99 world; optionally pass args.state.
initialize_accounts(people, systems)
agents = AgentService(tools=prepare_tools(systems))
network = emu.getLayer('Base').getAutonomousSystem(171)
for index, person in enumerate(people, 1):
    agent = agents.createagent(person)
    network.createHost(agent.vnode).joinNetwork('net0', address=f'10.171.0.{79+index}')
    emu.addBinding(Binding(agent.vnode, filter=Filter(asn=171, nodeName=agent.vnode)))
emu.addLayer(agents)
emu.render()
emu.compile(createcompiler(emu, systems), "output", override=True)
```

`createpeople` loads stable UUIDs, names and backgrounds. IDs are saved in
`people.json` and stay unchanged when names or deployment hosts change. Each person's
`accounts` declares their email address/password, payment group/password/opening
balance, bank profiles with savings accounts and cards, and shop credentials.
These personal accounts are not defined in H99's `world.json`. Each infrastructure
instance has its own deployment fields and hostname in that file. `createworld`
builds the network and application DNS without reading people.
H99 loads `world.json` once and keeps it internal. `createworld(state=None)` returns
the native Emulator and a separate map of application systems. E99 has no `--config`
option and does not read world settings.
After Agent setup, `emu.render()` and `emu.compile(createcompiler(emu, systems), ...)`
use H99's network placement and the native Docker compiler.
`initialize_accounts(people, systems)` in `virtual_world_with_agents.py` declares
mailboxes, wallets and bank customers
through each system's `addUser` or `addCustomer` method before
compilation. Mailu creates the mailboxes first. South Bank and North Bank then register
customers sequentially against those mailboxes, using the shared `bank@mail.com` sender.
The stable person UUID is the bank's external customer identifier. Payment and
bank balances/cards retain their configured values. Each Agent's generated runtime
configuration contains its personal metadata; the observer reads it inside the container.

`createpeople` loads people and [market.json](market.json), builds their contact
directory, and assigns inventory to its owner by person UUID. Product definitions
occur once in `market.json` and are passed to ShopService during account initialization; only the store name remains in the owner's Agent metadata. Other residents
start without product knowledge and discover the catalog through tools.
`agents.createagent(person)` copies that configuration into one Agent and assigns
its virtual node name. Host creation and binding are explicit in the main flow.
`prepare_tools(systems)` separately collects tool source and instance configuration
from configured systems. AgentService merges instances of the same package and
stores their addresses and routing maps in `tool_config`, separate from persona.
Tools combine this configuration with personal credentials when called.
`world.catalog` returns business names without connection details.
Payment tools construct their own API endpoints;
the model supplies business arguments such as a recipient email and amount.
Passwords stay in tool configuration. Product contents are imported into the shop and unlocked after payment.
The framework's `build_system_prompt` renders personal facts, account types,
initial knowledge and asset descriptions when the container starts. Tools use the
runtime members `accounts`, `knowledge` and `possessions`; credentials and product
delivery contents stay out of the prompt. Time observations, live tool results and checkpointed
conversation history enter through the native running graph; initial account data
is not treated as a live balance or transaction record.
`createagent` defaults to LangChain and all registered tools. `setFramework` and
`setTools` remain optional overrides.

Containers `agent_1` through `agent_5` are deployment slots; the monitor displays
personal names and identifies each person by UUID. Saved Agent state uses
`agents/<person-id>`, independent of those slots. Earlier name-keyed state directories
are retained but are not automatically migrated. After this account configuration
change, regenerate the experiment and use fresh application state.

All five residents live in AS171 at `10.171.0.80`–`10.171.0.84`. All receive the
same tools: world discovery/probing, network identity/DNS, email reading/sending,
wallet balance/transfers, voluntary card linking, card-funded payments and receipts,
bank account/card queries, wallet receipt/history queries, marketplace browsing, stores, products, orders, payment and downloads, and a local rest tool. Loan tools are not implemented.
Their accounts remain separate. Backgrounds and existing balances can differ.

AgentService's shared ClockServer runs in a separate container at
`http://10.171.0.79:8080/time`, with no host port mapping. The framework reads it
before each model decision; it is not an Agent tool. `start.py` treats the clock
as infrastructure and waits for its image health check before starting Agents.

Agents use H99's internal domain names over HTTP, SMTP and IMAP. Host browsers
use HTTP on the mapped `localhost` ports. See H99 for the URL table.

Residents can query their own cards at South Bank or North Bank with `bank.cards`,
choose a bank from `payment.banks`, and bind a specific card with `world.link_card`.
No cards are prebound. `payment.cards` lists linked source IDs; `payment.card_payment`
pays from a chosen source while `payment.transfer` uses wallet balance.
`payment.card_payments` checks receipts, including uncertain outcomes. Only
`completed` confirms a card payment; reuse the same operation UUID for retries.
Card funding currently supports matching USD accounts.

## Marketplace

The real marketplace is at <http://localhost:8449>, with native customer,
seller and administrator pages. All five residents have shop accounts using
their mailbox address and `ShopDemoPass123!`; the administrator is `admin` /
`ShopAdminDemo123!`. Carol's store and products come from `market.json` and
are imported by ShopService. Other residents discover products through
`shop.catalog`; delivery contents are not injected into their prompt.

Residents can create an unpaid order with `shop.order`, inspect its Payment
link with `shop.checkout` and pay with `shop.pay`. Omit `source` for balance or
select a bound card ID from `payment.cards`. Payment directly pays each seller;
the shop independently verifies the receipt. `shop.orders` and `shop.sales`
show buyer and seller views. `shop.downloads` and `shop.read_download` expose
purchased digital content only after payment. Sellers can open stores and
publish more products using `shop.open_store` and `shop.publish`.

The observer shows actual tool arguments and payment results. **Verified sales**
updates on the next dashboard refresh when a buyer's `shop.pay` returns a paid
order; the seller does not need to call `shop.sales`. Buyer `shop.orders` results
also update the panel. Repeated observations are deduplicated by checkout ID,
and newly observed purchases appear first with their actual receiving stores.
No per-Agent shop server or JSON order book is used. See
[H23](../../examples/H23_shop_service/) for manual browser testing.

## Runtime controls

Only the three LLM variables are required. Optional `.env` settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_MAX_STEPS` | `20` | Graph step budget per waking moment, from 4 to 100. |
| `AGENT_DEFAULT_REST_SECONDS` | `120` | Pause if the resident finishes without choosing a wake time. |
| `AGENT_START_DELAY_SECONDS` | `10` | Maximum randomized startup delay. |
| `AGENT_MAX_CYCLES` | `0` | `0` runs continuously; a positive value bounds local tests. |

Legacy `AGENT_ROUNDS`, `AGENT_INTERVAL_SECONDS` and `AGENT_READY_TIMEOUT_SECONDS`
are ignored. A failed model moment backs off before the next attempt. Resident
choices are model-dependent; no specific transaction or social pattern is forced.

Graph steps include both model decisions and tool execution. The adapter reserves
room to end a moment normally before the graph limit: completed conversations and
tool results are saved, then the resident rests and continues in a later moment.
Reaching this activity budget is reported as `moment_completed` with
`outcome=activity_budget`, rather than a failure. The default allows up to nine
model decisions per moment. Set `AGENT_MAX_STEPS=60` in `.env` for longer moments;
this takes effect after restarting agents and does not limit their total lifetime.

From `output`, inspect one resident:

```sh
docker compose exec hnode_171_agent_1 tail -f /home/emuvista-agent/agent.log
docker compose exec --user emuvista-agent hnode_171_agent_1 agentctl list
```

Avoid starting a second `agentctl run` in an already active resident container.
From `output`, stop and remove the whole world, including residents:

```sh
docker compose down
```

Without `--state`, the next `start.py` clears temporary application data and starts
fresh. With `--state`, data is retained. Container-local logs are removed in both
cases. `docker compose stop` keeps the existing containers and their current run.
H99 and E99 share host ports, so run one at a time. H99 documents the websites and
application initialization.

After upgrading from the intermediary-account payment version, regenerate the
deployment with fresh state. Rebuild the four customized application images
listed in [docker_images](../../docker_images/README.md), then rebuild the generated
Compose services before starting.
