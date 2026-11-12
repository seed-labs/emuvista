# AgentService

Runs each person inside a bound SEED host with a private Python environment.
See [design.md](../../docs/agent-service/design.md) for the architecture and the
`createpeople → createworld → createagent` workflow.

```python
agents = AgentService(tools=tools, environment_file='.env')
agent = agents.createagent(person)
# Optional: agent.setFramework('langchain')  # Already the default.
# Optional: agent.setTools(['email.inbox', 'email.send'])
emu.addLayer(agents)
emu.addBinding(Binding(agent.vnode, filter=Filter(asn=171, nodeName='host_0')))
```

`createagent(config)` copies one person's structured configuration and returns an
Agent configuration object. It assigns a free virtual node name (`agent_1`,
`agent_2`, ...), available as `agent.vnode`; normal SEED binding chooses the host.
Creation does not run a model or create application accounts.

The deployment object stores the complete personal metadata once in `_persona`;
installation writes that metadata directly into the runtime configuration. The
runtime context exposes personal members to tools. Optional setters remain available:

- `setPersona(dict)`: personal information and private `accounts`, plus initial
  `knowledge` and `possessions` when required by the example.
- `setFramework(name)`: framework deployment integration; currently `langchain`.
- `setTools(list)`: select registered tool names. All registered tools are available
  by default. E99 gives every person the same tools and their own accounts.

`person['id']` is a stable identifier, independent of names and deployment slots.
Runtime memory and events use that person ID. The lower-level
`install(vnode).setPersona(person)` remains supported. Configure before render. Normal SEED binding gives each
Agent its own container.
Framework integrations under `frameworks/` generate dependencies, configuration,
application source and the startup command during installation. Containers run the
framework application directly; examples do not supply runtime adapters.

The LangChain application uses a native LangGraph resident graph, a LangChain
conversation subgraph, SQLite checkpoints, summarization and per-activity model
call budgets. One native graph execution owns observation, activity, waiting and
continuation. There is no external loop issuing new tasks. Runtime memory defaults
to `/home/emuvista-agent/state/langgraph.sqlite`; E99's `--state` preserves it.

`environment_file` is read-only mounted at startup. Only `LLM_*` and `AGENT_*`
settings are loaded; API keys are not copied into images. Set `LLM_API_KEY`,
`LLM_BASE_URL` and `LLM_MODEL` in the example's `.env`.

Configured application instances export `getAgentTools()` or supply
`ToolPackage(name, source, configuration=...)`. The export contains the tool source
and a `configuration` map keyed by instance name. Exports of the same package
merge instance settings, so two banks share one tool implementation.
The shared catalog can be passed as `tools=`; existing `addToolPackage`,
`addToolsFrom`, `addNetworkTools` and `addPkiTools` helpers also register packages
at Service level. Each package owns `tools.json`, Python handlers and dependencies.
Handlers use `handler(arguments, context)`. Personal account credentials come from
`context.accounts`; service addresses and routing data come separately
from `context.tool_config[package_name]`. Handlers combine them for protocol calls.
Bundle configuration never enters the persona or system prompt. Tool source is
framework-independent.

The framework renders a system prompt at startup from the structured profile,
initial knowledge and asset descriptions. E99 does not prebuild an `instructions`
string. Private credentials and asset delivery payloads stay out of that prompt.
Account credentials stay
in the runtime context and are redacted from observable events. Simulated email,
bank and payment clients use SMTP, IMAP and HTTP. Full business arguments/results, including mail bodies, are retained in logs. Applications still
enforce authentication and business permissions; selecting a tool is not account
authorization or a sandbox for arbitrary framework code.

Run `agentctl list`, `agentctl call NAME '{...}'` or `agentctl run` as
`emuvista-agent`. Starting containers already starts the framework; do not launch
another `agentctl run` in an active Agent. Logs are in
`/home/emuvista-agent/agent.log`. The E99 dashboard reads events and shop orders,
not checkpoint tables. See [E99](../../experiments/E99_virtual_world_with_agents/) for startup.
