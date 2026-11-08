# Life in the virtual world

Adds five continuously running residents to [H99](../../examples/H99_virtual_world/).
Each has their own email, wallet and bank account, with the same available tools.
[residents.json](residents.json) describes personalities and interests, without
assigned purchases or required transactions. Carol runs a digital shop; the other
residents decide whether to buy. LangChain is a replaceable adapter.

```sh
# First run only:
cp .env.example .env
# Fill LLM_API_KEY, LLM_BASE_URL and LLM_MODEL.
python3 experiment.py
cd output
docker compose --profile agents build
cd ..
python3 start.py --infrastructure-only
python3 start.py --agents-only
```

`start.py --infrastructure-only` returns only after initializers finish, services
are healthy, and HTTPS/SMTP/IMAP work from AS171. Residents remain stopped until
`--agents-only`. `python3 start.py` performs both stages in sequence. Plain
`docker compose up -d` starts infrastructure only; the `agents` profile is opt-in.
Do not bypass the readiness checks by starting the agent profile directly.

If building the whole world fails with `failed to receive status ... no such job`,
build one service at a time from `output` to avoid the large Bake target set:

```sh
docker compose --profile agents config --services |
while IFS= read -r service; do
    docker compose --profile agents build "$service" || exit 1
done
```

This reuses the build cache and leaves containers stopped. See the
[Buildx issue](https://github.com/docker/buildx/issues/3810).

Stop an existing deployment before recompiling. Existing deployments need
regeneration, rebuilt agent images and recreated agent
containers to use the new behavior. Keep your existing `.env`. The model endpoint
must support Chat Completions tool calling and be reachable from the simulated
network. The experiment configures model egress; API keys stay in the read-only
runtime environment file. Restart agents after changing its values.

From `experiments/E99_virtual_world`, start the observer:

```sh
python3 monitor.py
```

Open **http://localhost:8090** to see current intentions, thinking, tool calls,
rest periods, wake times, reflections and failures. Select an agent and tool, then
a call to inspect all business arguments and full results. Email bodies have a
readable preview. Passwords, verification codes and access tokens stay hidden.
Recent older call details can be recovered from matching resident memory; already
discarded or expired details cannot be reconstructed. Restart the observer for
these changes. New complete logs and Sent copies require rebuilt agent images. Closing the observer leaves
the world running. Use `--port 8091` if its default port is occupied. Older running
images still show their earlier behavior until rebuilt and recreated.

## Resident behavior

Residents choose their own actions from observations, memories and interests.
They can communicate, agree on exchanges, transfer money, explore services or rest.
After the initial infrastructure readiness gate, residents discover later service
changes themselves and can return after a failure. There is no repeated task prompt
or requirement to wait for every service in each waking moment.

- `life.remember`: retain a memory and optionally a current intention.
- `life.recall`: recall personal notes and plans.
- `life.rest`: finish the present moment and choose a wake-up in 30–1800 seconds.

The loop runs until stopped. Recent conversations, notes and attempted operations
are retained in `/home/emuvista-agent/life/`, including calls from interrupted
moments. Memory helps avoid repetition but does not guarantee exactly-once business
operations. The agent is instructed to verify uncertain outcomes before retrying.
API failures are recorded and retried after a delay without ending resident life.

Memory survives a restart of the same container, but is lost on recreation.
`--state .runtime/world` preserves H99 application state; it does not yet persist
resident memory outside the agent containers.

All five residents live in AS171 at `10.171.0.80`–`10.171.0.84`. All receive the
same 24 tools: world discovery/probing, network identity/DNS, email reading/sending,
wallet balance/transfers, voluntary card linking, card-funded payments and receipts,
bank account/card queries, wallet receipt/history queries, shop browsing/quotes/
delivery/orders, and the three life tools. Borrowing and loan tools are
not exposed.
Their accounts remain separate. Backgrounds and existing balances can differ.

Residents can query their own cards at SEED Bank or North Bank with `bank.cards`,
choose a bank from `payment.banks`, and bind a specific card with `world.link_card`.
No cards are prebound. `payment.cards` lists linked source IDs; `payment.card_payment`
pays from a chosen source while `payment.transfer` uses wallet balance.
`payment.card_payments` checks receipts, including uncertain outcomes. Only
`completed` confirms a card payment; reuse the same operation UUID for retries.
Card funding currently supports matching USD accounts.

## Digital trade

[market.json](market.json) defines Carol's recipe, photography guide and budget
worksheet, priced at 300, 500 and 400 USD cents. Public listings contain prices and
descriptions; only Carol's configuration contains the actual delivery text. This
is a resident's small business, not a separately deployed marketplace server.

Residents can ask questions by email. Carol can make an order with `shop.quote`
and send its UUID, price and payment reference to the buyer. Buyers can choose
wallet balance or a voluntarily linked bank card. `payment.receipt` and
`payment.history` read the real ledger. `shop.deliver` verifies amount, recipient,
order reference and funding source before emailing the actual product. Completed
orders appear in the observer's **Verified sales** panel. A repeated delivery does
not resend the product; an uncertain delivery requires review. No buying quota or
scheduled purchase is imposed.

Email sends now include Date/Message-ID, support `inReplyTo`, and append a copy to
the mailbox's Sent folder. If SMTP succeeds but filing fails, the result reports
`sent=true, savedToSent=false`; do not send a duplicate just to repair Sent. Old
messages are not automatically backfilled into Sent.

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
docker compose exec hnode_171_agent_alice tail -f /home/emuvista-agent/agent.log
docker compose exec --user emuvista-agent hnode_171_agent_alice agentctl list
```

Avoid starting a second `agentctl run` in an already active resident container.
Stop the world with `docker compose down`. H99 and E99 share host ports, so run
one at a time. H99 documents the websites and application initialization.
