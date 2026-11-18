# DshAgentService

[中文](README_zh.md)

DshAgentService deploys DeepSeek Harness (DSH) agents in SEED Emulator containers. You can choose which plugin bundles each agent starts with, then use a Python script to inspect, enable, or disable installed bundles while DSH is running.

Install SEED Emulator, Python, and Docker Compose, then build the shared DSH runtime image before building the topology. [Shared runtime image guide](../../docker-images/deepseek-harness/README.md)

## Common APIs

| Call | Purpose |
| --- | --- |
| `DshAgentService()` | Create a service layer to add to a SEED topology. |
| `agents.install(name, *, bundles=(), config=None)` | Declare an agent with optional bundle paths and a per-instance YAML configuration file. |
| `DshAgentRuntime.from_compose(compose_file, *, project=None)` | Connect to a deployed Compose project. |
| `runtime.agent(name)` | Select an agent by the name used in the topology. |
| `agent.plugins.list()` / `agent.plugins.get(name)` | List installed bundles or inspect a specific bundle. |
| `agent.plugins.enable(name)` / `agent.plugins.disable(name)` | Enable or disable an installed bundle. Both calls wait for the change to take effect by default. |

## Choose plugins for each agent

Add the service to an existing SEED topology. Use `install()` to declare agents and `Binding` to assign them to hosts. This example assumes that the topology already defines the `alice` and `bob` hosts in AS150.

```python
from pathlib import Path

from seedemu.core import Binding, Filter
from services.DshAgentService import DshAgentService

here = Path(__file__).resolve().parent
agents = DshAgentService()
agents.install("alice", bundles=[here / "bundles/chat-tools.yml"])
agents.install("bob")

emu.addLayer(agents)
emu.addBinding(Binding("alice", filter=Filter(asn=150, nodeName="^alice$")))
emu.addBinding(Binding("bob", filter=Filter(asn=150, nodeName="^bob$")))
```

A bundle can be a native DSH Bundle directory or a YAML file. To add a single plugin, declare a bundle with one entry. Save this example as `bundles/chat-tools.yml` next to the topology script.

```yaml
name: chat-tools
plugins:
  - id: chat
    package: ../plugins/chat-client
    preset: resident
    config:
      endpoint: ws://chat.example.test:6060
      apiKey: "<public Tinode application key>"
      username: alice
```

The `package` path is relative to the bundle YAML file. Set it to the actual plugin directory and fill in the Chat endpoint and public application key for your deployment. `preset: resident` makes the plugin available to the default agent preset. If you omit it, the DSH host loads the plugin. You can also pass a YAML file through `install(config=...)` for per-agent settings such as a Chat username.

Run the topology's `render()` and `compile()` steps to generate deployment files, then build and start the containers with Docker Compose. The shared image provides the DSH runtime. To start DSH Web, run `dshagent web` inside the container. Set `profile.startup: auto` in the instance YAML to start it automatically. Configure model credentials at runtime.

## Enable and disable bundles with Python

Once DSH Web is running, point a separate Python script at the generated Compose file and select the agent using its declared name.

```python
from pathlib import Path

from services.DshAgentService import DshAgentRuntime

here = Path(__file__).resolve().parent
runtime = DshAgentRuntime.from_compose(here / "output/docker-compose.yml")
alice = runtime.agent("alice")

for bundle in alice.plugins.list():
    print(bundle.name, bundle.enabled, bundle.status)

alice.plugins.disable("chat-tools")
alice.plugins.enable("chat-tools")
print(alice.plugins.get("chat-tools").status)
```

If you started Compose with an explicit project name, pass the same name as `project` to `from_compose()`. Enable and disable operations report failures to the caller. Reuse the instance's persistent state directory to keep bundle selections across restarts.
