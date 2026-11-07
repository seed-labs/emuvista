# Five agents in the virtual world

Reuses [H99](../../examples/H99_virtual_world/) and adds five separate AgentService
nodes. LangChain `create_agent` is the initial framework; its adapter lives here,
not in AgentService. Other frameworks can supply another `run(context)` adapter.

```sh
# First run only:
cp .env.example .env
# Fill LLM_API_KEY, LLM_BASE_URL and LLM_MODEL in .env.
python3 experiment.py
cd output
docker compose build
docker compose up -d
```

In a second terminal, from `experiments/E99_virtual_world`:

```sh
python3 monitor.py
```

Open **http://localhost:8090** for agent states, active tools, call durations,
outcome summaries, tasks, permissions and model replies. Select an agent or a call
to inspect it. The page refreshes every two seconds. The host observer uses fixed,
read-only Docker commands; it does not start agents, call models or execute tools.
Closing it leaves the experiment running. Use `--output PATH` or `--port PORT`
for another generated output directory or browser port.

Existing images work with their legacy logs, showing completed calls. Recompile
and rebuild agent images from the updated source to include live tool-start events
and timing. The dashboard labels legacy logs explicitly. Container state and agent
process state are separate: an `Up` container can contain a completed agent.
Only retained log events are displayed; mailbox bodies and full bank records are
not included in event summaries. Readiness probes are marked with a `readiness`
source in call details. Manual `agentctl call` commands return their result directly
and do not append to the agent-run timeline. The dashboard is available on localhost only.
For running containers, tasks and permissions come from their actual image
configuration, so an older image is not mistaken for newly edited experiment code.

The API must support standard Chat Completions tool calling. `.env` is mounted
read-only and loaded at startup; API keys are not copied into images or generated
configuration. The file is ignored by Git. Change a key/model and restart the agent
containers to reload it. Changing the API hostname also requires recompilation.

The experiment adds SEED's native real-world router for LLM egress. The private
world keeps DNSSEC; only the configured external model hostname is forwarded to
public DNS. Use a hostname or IP reachable from the simulation, not `127.0.0.1`.

| Agent | Address | Granted business tools |
| --- | --- | --- |
| Alice | `10.171.0.80` | Wallet balance/payment; own email |
| Bob | `10.171.0.81` | Wallet balance; own email |
| Carol | `10.171.0.82` | Wallet balance; own email |
| Dave | `10.171.0.83` | Own bank accounts/cards/loans; own email |
| Erin | `10.171.0.84` | World observation |

All agents can inspect the public directory, probe service readiness and resolve
DNS. Tool source is copied from installed components. Discovery exposes only the
agent's allowlist, and every dispatch checks it again. Business APIs separately
check the agent's service credentials.

Logs and local tool discovery:

```sh
docker compose exec hnode_171_agent_alice tail -f /home/emuvista-agent/agent.log
docker compose exec --user emuvista-agent hnode_171_agent_bob agentctl list
docker compose exec --user emuvista-agent hnode_171_agent_bob agentctl call payment.transfer '{}'
```

The last call must fail as unauthorized. Replace the name in the service key to
inspect another agent. All five use `agent_<name>` on AS171.

The default run uses three rounds, at most 20 graph steps each. After a startup
delay, each agent waits up to 600 seconds for its required services. Set limits
in `.env`. Calls may observe services still initializing; the
adapter records failures without claiming success. No real LLM call is possible
until a key and model are supplied. Inspect model usage with your provider.

H99 documents websites, accounts and current payment limitations. Use
`--state .runtime/world` for the same persistence scope. H99 and E99 share host
ports, so stop one before starting the other.
