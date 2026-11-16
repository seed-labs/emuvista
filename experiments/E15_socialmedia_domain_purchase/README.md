# E15: Mastodon and domain purchase

E15 uses the shared H00 topology with Mastodon, CAService, Registry,
FOSSBilling, DNS hosting and FakePayment. Alice, Bob, Carol, Dave and Eve use AgentService with
AgentService's native LangChain framework. No Tinode, EmailBundle or separate tool-service is deployed.

## Generate and start

Before replacing an existing deployment, stop it using its old generated Compose
file. Keep volumes; do not add `-v`:

```bash
docker compose -f output/docker-compose.yml down
```

Keep `.env` with `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` configured.
Run from this directory:

```bash
../../.venv/bin/python experiment.py
cd output
docker compose build
docker compose up -d
```

`--output`, `--env-file` and `--platform amd|arm` select generation settings.
There is no Tinode archive argument. Old Tinode packages and database volumes
are not deleted by generation. CA state is retained in `.runtime/ca.com`.
Creating a new CA requires Docker; an existing saved CA is restored.
Do not delete the CA state when reusing the deployment.

## Services and credentials

| Component                 | Internal address                                    | Host access                     |
| ------------------------- | --------------------------------------------------- | ------------------------------- |
| Mastodon                  | `mastodon.com:18443` / `10.161.0.9`             | `https://mastodon.com:18443/` |
| CA                        | `ca.com:443` / `10.161.0.4`                     | Internal ACME CA                |
| FOSSBilling               | `10.150.0.71:8080`                                | `http://localhost:18080/`     |
| Registry                  | `10.151.0.71:8080`                                | `http://localhost:18081/`     |
| FakePayment               | `10.160.0.71:8080`                                | `http://localhost:18083/`     |
| Alice / Bob agents        | `10.161.0.80` / `10.161.0.81`                   | Monitor below                   |
| Carol / Dave / Eve agents | `10.161.0.82` / `10.161.0.83` / `10.161.0.84` | Monitor below                   |
| Recursive DNS             | `10.150.0.54`                                     | Internal                        |

For browser access, map `mastodon.com` to `127.0.0.1` in the host's hosts file,
and trust `.runtime/ca.com/.step/certs/root_ca.crt` in the browser/host trust store.
CAService installs trust on AS161 nodes for agent HTTPS requests.
Mastodon obtains its certificate from `https://ca.com/acme/acme/directory`.
No separate DNSSEC extension is required.

Demo accounts are initialized when the services start:

| Agent | Mastodon email         | FOSSBilling email                     | Password for both agent accounts                   |
| ----- | ---------------------- | ------------------------------------- | -------------------------------------------------- |
| Alice | `alice@mastodon.com` | `alice@example.com` (customer)      | `alice123456`                                    |
| Bob   | `bob@mastodon.com`   | `admin@example.com` (administrator) | Mastodon: `bob123456`; FOSSBilling: `Aa123456` |
| Carol | `carol@mastodon.com` | `carol@example.com` (customer)      | `carol123456`                                    |
| Dave  | `dave@mastodon.com`  | `dave@example.com` (customer)       | `dave123456`                                     |
| Eve   | `eve@mastodon.com`   | `eve@example.com` (customer)        | `eve123456`                                      |

Mastodon's separate administrator is `admin@mastodon.com` / `admin123456`.
Bob has no configured FOSSBilling customer account. Existing database accounts
are retained; switching Alice from `user@example.com` does not migrate old orders
or delete that old account. Existing customer passwords must match the configured
values; initialization refuses to silently change them.
E15 does not import example domain, customer or DNS data from YAML.

## Agents and tools

Socialmedia tools live in
[MastodonBundle/tools](../../bundles/MastodonBundle/tools/).
The old AgentService chat tool package has been removed.
Each agent is allowed:

- `network.identity`, `network.resolve`, `world.catalog`, `world.probe`
- `socialmedia.inbox`, `socialmedia.browse`, `socialmedia.profile`, `socialmedia.posts`,
  `socialmedia.read`, `socialmedia.post`, `socialmedia.like`, `socialmedia.boost`, `socialmedia.follow`
- `dns.lookup`, `domain_purchase.purchase`, `domain_purchase.status`
- `domain_purchase.set_nameservers`, `domain_purchase.hosting_purchase`, `domain_purchase.hosting_status`

Alice, Carol, Dave and Eve are ordinary Mastodon users; Bob is a FOSSBilling domain sales employee.
Each agent has a separate role-level task, without a fixed business goal or
operation sequence. Shared system instructions require role consistency, factual
claims grounded in tool results, explicit uncertainty, result verification and
concise communication. These are prompt instructions, not runtime guarantees.
Tool descriptions define operation-specific rules and limits.

Domain purchase/hosting tools are available to Alice, Carol, Dave and Eve. Bob receives the
`fossbilling_admin` service configuration for future admin tools; no admin login
or query tool is implemented yet. His system prompt does not supply prices or
nameservers as business facts.

During Mastodon startup, MastodonBundle creates/reuses a limited token
for each account, including `read:notifications` for `socialmedia.inbox`,
`write:favourites` for `socialmedia.like` and `write:follows` for `socialmedia.follow`.
After adding this scope, regenerate and rebuild/recreate Mastodon as well as all five
agents so startup exports credentials with the new permissions.
Each agent receives only its own credential directory through
a read-only named volume (`e15-socialmedia-<name>`).
Token files are owned by the agent UID 10001 with mode 0600 and are not baked
into images. Tools may report missing credentials until Mastodon initialization
finishes. Check `/var/log/mastodon-initialize.log` in the Mastodon container if needed.

From `output/`, test without invoking the model:

```bash
docker compose exec --user emuvista-agent hnode_161_agent_alice agentctl call socialmedia.profile '{"acct":"bob"}'
docker compose exec --user emuvista-agent hnode_161_agent_bob agentctl call socialmedia.browse '{"limit":5}'
docker compose exec --user emuvista-agent hnode_161_agent_alice agentctl call socialmedia.inbox '{}'
```

`inbox` returns incoming @mentions with their posts. Process a successful page,
then use its `next_min_id` as the next call's `min_id`; repeat until the page is
empty. Use each notification's `status.id` for conversation reads and replies.
This is a polling tool, not an automatic per-round notification injection.

Check `successful` and `outcome_unknown`. Do not blindly repeat an uncertain
write; inspect your own posts first and reuse the same idempotency key for the
same submission. Model `.env` stays mounted read-only, outside the images.

From the E15 directory, start the monitor:

```bash
../../.venv/bin/python monitor.py
# http://localhost:8090/
```

Validation is limited to generation and configuration checks unless explicitly
reported otherwise. A successful build does not establish live messaging or purchase success.

## Domain purchase and DNS lookup

The [domain_purchase package](../../bundles/DomainRegistrarBundle/tools/README.md)
uses each ordinary agent's own FOSSBilling customer account configured in `experiment.py`.
It creates a one-year domain order and confirms only FakePayment
simulation payments within the specified maximum. Domain registration itself does
not create DNS hosting or records; DNS Hosting has separate tools.
Neither agent is assigned a purchase task or a mandatory purchase outcome.

Each ordinary agent has a separate `e15-domain-purchases-<name>` volume storing
purchase progress. Bob has no purchase journal. Retain these volumes
when rebuilding. Repeated purchase calls for the same account/domain return the
journal rather than submitting again. Use `domain_purchase.status` after a timeout;
if no order ID was obtained, reconcile through the portal. An over-limit invoice
remains unpaid and is not automatically retried when you raise the limit.

Examples from `output/` (the purchase command creates an order and submits a
simulated payment; replace the domain with your intended unregistered name):

```bash
docker compose exec --user emuvista-agent hnode_161_agent_alice agentctl call dns.lookup '{"name":"mastodon.com","record_type":"A"}'
docker compose exec --user emuvista-agent hnode_161_agent_alice agentctl call domain_purchase.purchase '{"domain":"alice-tool-demo.com","max_amount_minor":1500}'
docker compose exec --user emuvista-agent hnode_161_agent_alice agentctl call domain_purchase.status '{"domain":"alice-tool-demo.com"}'
```

The [DNS tool](../../services/AgentService/tools/dns/README.md) uses the agent's
resolver unless a server IP is specified. NXDOMAIN, empty NOERROR and timeout are
different results. A newly purchased domain does not necessarily have an A record.

Validation for these additions: mocked customer checkout/payment/status, payment
limit, lost checkout acknowledgement, duplicate suppression, DNS response parsing
and authorization checks; temporary deployment generation and agent-volume
inspection. No live purchase or DNS resolution was performed by this change.
No AgentService runtime or repository test files were modified.

### AgentService API migration

Agents use `setTools` and `setPersona`; per-person social/domain credentials reside in
`persona.accounts`, while public provider URLs reside in `ToolPackage.configuration`.
The environment file is configured on `AgentService`. A separate ClockServer at
`10.161.0.79:8080` supplies the native resident framework's time. H00 already supplies
the real-world egress router; E15 does not create a second AS99999.

E15 now uses the upstream checkpointed LangChain framework, not the removed E99
adapter. In an existing `.env`, replace `AGENT_ROUNDS` with `AGENT_MAX_CYCLES`
(e.g. `3`; `0` means unlimited) and `AGENT_INTERVAL_SECONDS` with
`AGENT_DEFAULT_REST_SECONDS` (30–1800, default 120). `AGENT_READY_TIMEOUT_SECONDS`
is no longer used by this framework. Existing `.env` files are not rewritten.
These settings do not apply to E16's independent loop.
