# H17: Social media agent using Tool Service

This example was renamed from `H15_socialmedia_agent`. Existing generated `output/` files may
contain absolute paths to the old directory; regenerate before the next deployment.
Legacy `h14-*` service, CA and volume identifiers are retained for data continuity.

> Historical example: the standalone `tool-service` has been removed. This
> generator and its commands are no longer runnable from the current checkout.
> The migrated [socialmedia package](../../bundles/MastodonBundle/tools/)
> supports AgentService. E15 registers this package from MastodonBundle. The remainder documents the old design.

H17 reuses H16's Mastodon, DNS, Alice and Bob topology and adds two containers:

| Component | Address | Role |
| --- | --- | --- |
| Social media agent | `10.151.0.80`, UI `http://127.0.0.1:18089` | Model conversation and HTTP tool calls |
| Tool Service | `10.151.0.81:8000` | Tool discovery, validation and execution |
| Mastodon | `https://mastodon.com:18443` | H16 service, unchanged |

Like H13, the agent has a chat UI and configurable model endpoint. It contains no
local tool implementations, Playwright, Chromium, desktop or VNC components. The
agent fetches `GET /api/v1/tools`, uses all advertised tools, converts input
schemas to model function definitions, and includes output contracts in model
context. Calls go to `POST /api/v1/tools/{name}/invoke`; returned data is appended
as `role=tool` before the next model request.

Of the two added containers, only Tool Service mounts the Docker socket. For tools with a `source` parameter, it executes from the agent container, whose
source ID is fixed by the agent application.
The model supplies the target and probe parameters but cannot override the source.
The agent image includes `iputils-ping`; tool execution still belongs to Tool Service.

The first exercise verifies the remote tool loop with ping; this is a usage example,
not a discovery filter. Other advertised tools remain visible to the model and may
require additional setup. Mastodon authentication will be added later; no token or
certificate preparation is required for the ping exercise.

## Generate and start

Run from this directory with the same Python environment used for H16:

```bash
cp .env.example .env
# Fill in .env before starting the agent.
../../.venv/bin/python socialmedia_agent.py
docker compose -f output/docker-compose.yml build
docker compose -f output/docker-compose.yml up -d
```

The generator reads the local Docker socket group and records it as the default
`group_add` value. `DOCKER_GID` can override it during generation or Compose startup.
When generating without a local socket, Compose requires `DOCKER_GID` explicitly
instead of silently using group 0. If deploying on another host, set it to that
host's socket group (`stat -c '%g' /var/run/docker.sock`).

Generation copies the current tool-service source into its build context. After
editing tool-service or agent code, regenerate and rebuild the affected service.
`--output PATH` and `--platform amd|arm` are supported. The Mastodon build is as
large as H16's; generation alone does not build or start it.

Do not run H16 and H17 simultaneously: they share topology addresses, generated
node names and the Mastodon port. Stop the previous scenario first without deleting
its persistent volumes. See [H16](../H16_socialmedia/README.md) for instance startup,
accounts, certificates, logs and persistence details.

## Use the agent

Set `EMUVISTA_LLM_BASE_URL`, `EMUVISTA_LLM_API_KEY` and `EMUVISTA_LLM_MODEL`
in this directory's `.env`, following the AgentSociety DNS experiment's naming.
Use the actual model identifier served by your OpenAI-compatible endpoint. The API
key may be empty for endpoints that do not require authentication. For a host-side
model, use `http://host.docker.internal:PORT/v1` and allow container connections.

The generated Compose file mounts this local file read-only into the agent; it is
not copied into the image. The backend loads it at startup, with process environment
variables taking precedence. Restart the agent after changing `.env`; when moving
the scenario to another host, regenerate to update the mount path. Credentials are
not sent to the browser. Open **http://127.0.0.1:18089** and send a message.
External model domains resolve through Docker DNS; `mastodon.com` resolves through
H16's recursive DNS.

Examples:

- `请 ping 10.151.0.9 三次，并说明结果。`
- `请 ping mastodon.com 三次，每次等待两秒。`

The UI omits the tool catalog and accumulates tool responses grouped by chat turn.

Social media tools include timelines, posting/replies,
`account_lookup`, `account_statuses`, `status_read`, `status_context`,
`status_favourite`, `status_reblog`, and `account_follow` (all under `socialmedia.`).
The last three accept `enabled=false` to undo the action. Replies use
`status_create.in_reply_to_id`; account lookup supplies the ID for reading posts
or following. A follow result with `requested=true` means approval is pending.

Generation copies H16's public CA root into the agent build context; the image
installs it into the system trust store with `update-ca-certificates`. Regenerate,
rebuild and recreate the agent after this change or after replacing the H16 CA.

For Mastodon calls, supply `instance_url=https://mastodon.com:18443`; HTTPS
verification uses the system trust store. Authenticated operations still need
a `credential_file` inside the agent container containing `{"instance_url":"https://mastodon.com:18443","access_token":"..."}`.
Provision this credential file separately; the LLM `.env` does not supply Mastodon credentials.
Use token scopes `read:accounts`, `read:statuses`, `write:statuses`,
`write:favourites`, and `write:follows` for the corresponding operations.
Endpoint definitions follow the Mastodon [accounts](https://docs.joinmastodon.org/methods/accounts/)
and [statuses](https://docs.joinmastodon.org/methods/statuses/) APIs.

Starting a new conversation clears the displayed records; page reloads also clear
the browser view. The agent still discovers all advertised tools internally. Sessions
are held in memory and disappear on restart. A session executes one turn at a time;
model/tool calls are bounded by timeouts and a round limit. HTTP/tool transport
failures stop the turn. A valid ping result with `reachable=false` is passed back
to the model for explanation. Check `exit_code`, `stdout` and `stderr`: failed
execution and unanswered probes are different observations. ICMP reachability does
not establish that the Mastodon application is ready.

The UI is published only on host loopback. Tool Service is not published to a host
port, but remains reachable within the trusted simulation network. This example
does not add authentication or multi-user isolation to Tool Service.

## Verification boundary

Source generation, YAML inspection, syntax/static checks and mocked model/tool
exchanges have been checked. Docker Compose validation, image builds and live
execution have not been performed because Docker is unavailable in the development
environment. A live ping exercise requires running containers and a reachable
model endpoint, but no Mastodon login. An IP-address probe does not require DNS;
a hostname probe also requires the scenario's DNS services. Inspect the returned
ping result rather than treating a model's final message as independent evidence.
