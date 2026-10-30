# H13: Browser and Agent in One Container

This example includes the full H12 domain services and adds a separate `browser-agent`
container through `Docker.attachCustomContainer()`. It joins AS154/net0 at `10.154.0.80`
without replacing an existing SeedEmu host. The image includes Chromium, Playwright, Xvfb,
view-only VNC, and the source in this example's `agent/` directory. Both the agent and
browser run inside the container.

From this directory, use a Python environment with SeedEmu installed:

```bash
python browser_agent.py
cd output
docker compose build
docker compose up -d
cd ..
```

The agent UI is at <http://localhost:18089/> and includes a live browser view.
FOSSBilling remains at <http://localhost:18080/>, its admin portal at
<http://localhost:18080/admin>, and Registry at <http://localhost:18081/>.
The agent accesses application sites through simulation IPs, such as
`http://10.150.0.72:8080/`; localhost inside a container refers to that container itself.

Browser control, VNC, and noVNC static files listen only on container loopback. Only the
agent port is forwarded to host localhost on port 18089. `agent/local_tools/dns/tools.py`
runs `dig` directly in the container without a Docker socket. Agent source and dependency
requirements are in this example's `agent/` directory.

## Model API and Networking

Enter the API URL, key, and model in the UI. The build copies explicitly listed source
files and Python packages, plus `agent/model_profiles.json` if present; it does not copy
`.env` files or runtime caches. Model profiles contain API keys and are gitignored. The
build context and image may also contain these profiles and must not be publicly distributed.

Simulation traffic for `10.0.0.0/8` uses the AS154 router; the default route retains Docker's
external gateway. DNS defaults to the simulation resolver at `10.153.0.53`. Put destinations
that need Docker egress in `egress_urls.txt`, one URL, domain, or IP per line. No route or
DNS commands are needed, for example:

```text
https://api.example.com/v1
api.other-provider.com
10.13.94.198
```

At startup, the container sends listed domains to Docker DNS and adds `/32` routes through
Docker's default gateway for listed IPs within `10.0.0.0/8`, except its own `10.154.0.0/24`
network. Public IPs already use the default route. If a domain resolves to an external
`10.*` address, list that IP too. This file defines egress exceptions, not a firewall allowlist.
API keys remain in model profiles; update the egress file when a changed model endpoint
needs external access.

The first deployment requires generation, build, and startup. Afterward, apply address-file
changes from the H13 directory without rebuilding:

```bash
docker compose -f output/docker-compose.yml restart browser-agent
```

The file is mounted read-only at `/opt/network-config/egress_urls.txt`; the image also keeps
an initial copy. Restarting closes existing browser sessions. Adjust the Compose path when
using a custom output directory. For a model service on the host, use an address such as
`http://host.docker.internal:PORT/v1` and ensure the service listens on an address reachable
from containers. The environment does not automatically test model APIs or run agent tasks.

## Scripts and Data

- `browser_agent.py` generates H13 deployment files without building or starting containers.
- `container/prepare_context.py` prepares the build context after compilation.
- Cleanup: `docker compose -f output/docker-compose.yml down --remove-orphans --volumes`
  removes containers, networks, and project volumes. Adjust the path for custom output.
- Generation supports `--output` and `--platform`; domain services initialize at container startup.

H12 and H13 use the same default Compose project `output` and application ports. Run them
as alternative scenarios, not simultaneously. Before switching, the cleanup command above
can remove the old deployment, including its database data. H13 does not clean old scenarios
automatically. Host-side `agent/model_profiles.json` survives rebuilding and cleanup.

The generated browser build context is `output/browser-agent`. After changing `agent/`
source, rerun `python browser_agent.py`, then build and start manually from `output` to
update the container. Dependency versions are defined in `agent/requirements.txt`.

Model API keys come only from the web UI and host-side `agent/model_profiles.json`. The build
copies profiles to `/opt/agent/model_profiles.json`. At runtime, the host's `agent/` directory
is mounted at `/opt/agent-config`; the backend prefers
`/opt/agent-config/model_profiles.json` and saves it atomically.
Browser and DNS tools always execute in the current container; neither UI nor tools accept
a selectable execution source. Enter the configuration and use the save action on first
use; subsequent visits load the file. The backend does not read `local_config.json`,
environment variables, or browser localStorage. Unsaved inputs exist only in page memory
and are lost on refresh.

## Restarting the Agent

The container entry point starts the browser and agent automatically. To restart after a
process exits, run from the H13 directory:

```bash
python start.py
```

This invokes `docker compose restart browser-agent`, starting a stopped container or
restarting a running one without rebuilding the image or reinitializing domain services.
Use `--output` to select an existing Compose directory. Initial deployment or deployment
after cleanup still requires generation, build, and startup first. Restarting closes the
browser session but preserves saved model profiles; refresh the UI and start a new chat.

Dependencies are installed in separate layers compatible with the legacy builder and
BuildKit. Changes to installation steps rebuild affected layers; later agent source or profile
changes affect only subsequent copy layers. Retry a failed image build with
`docker compose build` from `output`, without cleanup.

Networking is configured by `container/start.sh`, installed at `/opt/browser-agent/start.sh`.
Before starting dnsmasq, the browser, and the agent, it reads `egress_urls.txt` and configures
simulation routing, IP exceptions, domain-specific DNS forwarding, and the container resolver.
It preserves Docker's default gateway and does not print model keys. Script changes require
an updated image; address-file changes require only a browser-agent restart.
