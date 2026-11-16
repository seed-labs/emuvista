# H13: Domain Agent

H13 extends H12 with an interactive domain agent at `http://localhost:18089/`.
The `domain-agent` container joins AS154/net0 at `10.154.0.80`. It provides chat,
model configuration and tool results; Chromium, Playwright and VNC are not installed.

## Generate and start

From this directory:

```bash
../../.venv/bin/python domain_agent.py
cd output
docker compose build
docker compose up -d
```

Generation supports `--output` and `--platform amd|arm`. It does not build images,
start containers or invoke the model. H12 and H13 share application ports and the
usual Compose project name `output`; stop the previous deployment before switching.
Do not use `down -v` when retaining databases and purchase journals.

The directory was renamed from `H13_browser_agent` to `H13_domain_agent`, and
`browser_agent.py` to `domain_agent.py`. Any old generated `output` was left at its
original location. Stop that deployment using its original Compose file before
starting the new one. Existing model profile files move with the agent sources.

## Tools and account

The generator calls `DomainRegistrarBundle.getAgentTools()` and copies its tool
package into the generated context. The agent reads that package's `tools.json`
and invokes the Bundle's actual handlers through H13's small JSON Schema validation
and dispatch adapter. H13 keeps its own model loop and does not use AgentService.
It does not maintain a second implementation of domain purchase tools.

Available tools:

- `domain_purchase.purchase`, `domain_purchase.status`
- `domain_purchase.set_nameservers`
- `domain_purchase.hosting_purchase`, `domain_purchase.hosting_status`
- `domain_purchase.dns_list`, `domain_purchase.dns_add`
- `domain_purchase.dns_update`, `domain_purchase.dns_delete`

All business calls use H12's customer `user@example.com` / `Aa123456`, registrar
`http://10.150.0.10:8080`, and FakePayment `http://10.160.0.71:8080`.
Connection details and credentials are private tool configuration, not model arguments.
The payment limit is expressed in USD cents. The agent requires user authorization
for purchases and uses status tools to reconcile uncertain results.
DNS record tools require the active DNS Hosting order ID and matching zone domain.
List records before selecting a record ID to update or delete. Updates preserve name
and type. A successful write means API acceptance; `records_readback` indicates
whether the resulting list was fetched, not independent DNS propagation verification.
The Bundle does not expose recursive DNS lookup, customer registration or renewal.

Purchase journals persist at `/var/lib/domain-agent/purchases` in the named Compose
volume `h13-domain-purchases`. Keep this volume across rebuilds. Conversation reset
or reconnect does not undo purchases or clear these journals. All chat sessions share
one customer account; this is a local, single-user interface.

## Model configuration and networking

Configure the model API URL, key and model through the chat page. Saved profiles
remain in `agent/model_profiles.json`, mounted at `/opt/agent-config`; profiles are
not copied into the image. Chat history is per connection and is not persisted.

Simulation traffic uses the AS154 router and DNS resolver `10.150.0.54`. Model
endpoints listed in `egress_urls.txt` use Docker DNS; listed private IPs receive
host routes through Docker's gateway. Restart `domain-agent` after changing that
file. The file is an egress routing configuration, not a firewall allowlist.

```bash
docker compose -f output/docker-compose.yml restart domain-agent
```

After changing agent or Bundle tool source, regenerate and rebuild the deployment.
Generated configuration checks do not verify a live model conversation or purchase.
