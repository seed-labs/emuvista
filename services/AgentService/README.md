# AgentService

See the [architecture](../../docs/agent-service/design.md) for the simulated world,
AgentService internals and infrastructure developer responsibilities.

Deploys an agent directly on a SEED host through normal virtual-node binding.
Each agent has its own container, Python virtual environment and process user.
Framework adapters and tool packages are copied into the image during compilation.

```python
from services.AgentService import AgentService, ToolPackage
from seedemu.core import Binding, Filter

agents = AgentService().addNetworkTools()
# Optional: agents.addPkiTools()  # container-local certificate and TLS tools
# Optional: agents.addToolsFrom(application)  # application.getAgentTools() -> ToolPackage
agent = agents.install('alice')
agent.allowTools('network.identity', 'network.resolve')
agent.setScript([{'tool': 'network.identity'}])
emu.addLayer(agents)
emu.addBinding(Binding('alice', filter=Filter(asn=150, nodeName='host_0')))
# Configure all agents before emu.render().
```

`allowTools(...)` replaces the exact-name allowlist. The default grants nothing.
Unauthorized tools are hidden from discovery and rejected before handler import
or execution, including local CLI invocations. One agent is allowed per node.
Policies and copied source belong to root; agents run as `emuvista-agent`.

Applications own their tool source and expose `getAgentTools()` or construct
`ToolPackage(name, directory)` explicitly. A directory contains `tools.json` and
Python handlers with signature `handler(arguments, context)`. `addToolsFrom(service)`
or `addToolPackage(package)` selects packages for the installed services. Packages
are copied to every agent; each agent's allowlist narrows what it may call.
Payment, bank and email components export tool packages
through `getAgentTools()`.
The optional [PKI package](tools/pki/) includes certificate and TLS tools migrated
from the former tool server. It executes as the agent user in the agent's own node.

Tool definitions contain `name`, `description`, `handler` (`module:function`) and
`input_schema`. The initial validator supports object/array/primitive types,
required properties, enums, number ranges and string lengths. Unknown schema
keywords are rejected when invoked. Tools can use `context.service(name)` for
per-agent URLs and credentials set with `setService(name, configuration)`.

For another agent framework:

```python
agent.setFramework('./my_adapter', entrypoint='adapter:run', requirements=[])
agent.setEnvironment('MODEL_NAME', 'your-model')
```

`adapter.py` defines `run(context)`. It wraps the chosen framework and passes
`context.tools.list()` and `context.tools.invoke(name, arguments)` to that framework.
Dependencies install in the agent's virtual environment. The service includes a script runner. The LangChain adapter in E99 is independent
of this service and can be replaced with another framework.
`agentctl list`, `agentctl call NAME '{...}'` and `agentctl run` use the same policy.
Run the CLI as the agent user. Logs are in `/home/emuvista-agent/agent.log`.

`agentctl run` emits timestamped JSON events with a run ID and correlated tool
start/end events, durations, complete business arguments/results and outcome summaries.
Authentication material is redacted; mail bodies remain visible for world observation. Framework adapters can report
phases and replies through `context.emit(event, **fields)` independently of any UI.
Normal `agentctl list/call` commands retain their single-result output. E99's
host-side `monitor.py` visualizes these events without changing business services.

This authorization controls the common tool entrypoint. It is not a sandbox for
arbitrary framework code: code running as the agent can use its network and read
its own files. Each world service must still enforce its account credentials and
business permissions. Do not put credentials for other identities in an agent.

Use `setEnvironmentFile(path)` to bind-mount LLM/AGENT settings and load them at
startup without copying secrets into an image. See [E99](../../experiments/E99_virtual_world/)
for five agents on the shared [H99 world](../../examples/H99_virtual_world/).
