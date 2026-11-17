# H30: Cloud Drive agents with DshAgentService

[中文](README_zh.md)

This example runs Cloud Drive, DNS, a CA, and two DeepSeek Harness agents on a SEED network. `DshAgentService` initializes each agent's profile and loads Cloud tools from the [bundle declaration](bundles/cloud-tools.yml). Both stages use the same `dshagent` profile.

## Build and start

Use Linux Docker Engine, Docker Compose v2, Python 3.10+, and amd64. Run these commands from this example directory.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build --platform linux/amd64 -f ../../docker-images/deepseek-harness/Dockerfile.dsh-runtime -t seedemu-dsh-runtime:0.2.0-rc.2 ../../docker-images/deepseek-harness

python CloudDriveTopology.py
cd output
docker compose -p emuvista-h30 build 072d7840db6a44d06e5c5fd4d7ea8a7d ad739b7b201eccafa592110d2bf214a7
docker compose -p emuvista-h30 build
docker compose -p emuvista-h30 up -d
docker compose -p emuvista-h30 ps
cd ..
```

Build the two SEED base image services first. Wait for Cloud to report `healthy`. The first startup creates the Cloud accounts and initializes both agent profiles. Stop the previous deployment before regenerating the topology and rebuild the node images together because regeneration creates new CA material.

## Open the agents

Run the following in three separate terminals from this example directory. Activate the Python environment in the tunnel terminal.

```bash
docker compose -p emuvista-h30 -f output/docker-compose.yml exec hnode_158_alice dshagent web
docker compose -p emuvista-h30 -f output/docker-compose.yml exec hnode_158_bob dshagent web
python container/web_tunnel.py
```

Open the authentication URL printed by each DSH process. Change the port to `18311` for Alice or `18312` for Bob and keep the authentication parameters. Configure the model in Web settings and select **Resident** in new sessions.

## Stage one: Share and verify a file

In a terminal with the Python environment activated, disable the default Claw bundle on both running agents.

```bash
PYTHONPATH=../.. python - <<'PY'
from services.DshAgentService import DshAgentRuntime

runtime = DshAgentRuntime.from_compose("output/docker-compose.yml", project="emuvista-h30")
for name in ("alice", "bob"):
    print(name, runtime.agent(name).plugins.disable("claw").status)
PY
```

1. Send Alice the [upload and read-only share prompt](prompts/phase1/alice.md). Record the share ID and SHA-256.
2. Insert the share ID in the [download prompt](prompts/phase1/bob.md) and send it to Bob.
3. Check the actual tool results in Trajectory. Bob should download `Hello Bob from Alice through Cloud Drive.` with the same SHA-256 as Alice's upload.

Cloud Drive is at `https://cloud.h30.seedvista.test`. The sample accounts are `alice / alice-password` and `bob / bob-password`. The topology's CA issues the TLS certificate. The prompt files are in Chinese.

## Stage two: Collaborate through Cloud events

Confirm in Trajectory that both stage-one sessions have successfully called `cloud_logout`. This prevents those sessions from reacting to the new share. When both agents are idle, enable Claw through the same API, keeping both profiles and Web processes running.

```bash
PYTHONPATH=../.. python - <<'PY'
from services.DshAgentService import DshAgentRuntime

runtime = DshAgentRuntime.from_compose("output/docker-compose.yml", project="emuvista-h30")
for name in ("alice", "bob"):
    print(name, runtime.agent(name).plugins.enable("claw").status)
PY
```

Start new **Resident** sessions. Send Bob the [observer setup prompt](prompts/phase2/bob.md) first. After the baseline is established, send Alice the [collaboration prompt](prompts/phase2/alice.md) with a fresh file identifier. Observe the Claw events and `expected_etag` in Trajectory. The final file should contain seven alternating messages.

## Stop

Stop both Web processes and the tunnel, then run:

```bash
docker compose -p emuvista-h30 -f output/docker-compose.yml down
```

Cloud data and profiles persist in `.runtime/`. Run the stage-one script to disable Claw again when repeating the example. [DshAgentService guide](../../services/DshAgentService/README.md)
