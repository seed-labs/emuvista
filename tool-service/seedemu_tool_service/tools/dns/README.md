# DNS tools

This package exposes DNS queries, domain-registration access, authoritative-zone
configuration, and DNS diagnostics through the tool-service registry. Commands
run from a selected emulated `source` through `RuntimeBackend`; the tool-service
does not need direct routing to emulated addresses.

## Package layout

| Package | Responsibility | Registered tools |
| --- | --- | --- |
| `basic/` | Individual read-only DNS queries | `dns.lookup`, `dns.reverse_lookup` |
| `domain_registration/` | Registrar access, RDDS lookup, and authorized zone changes | `domain.registrar_find`, `domain.registrar_request`, `domain.rdds_lookup`, `dns.authoritative_find`, `dns.configure` |
| `diagnostics/` | Multi-point and delegation diagnostics | `dns.compare`, `dns.trace`, `dns.check_delegation` |
| `shared/` | Common models and `dig` parsing | None |

`models.py` and `tools.py` at the package root retain compatibility imports.
`registration.py` is the aggregate entry point:

```python
from seedemu_tool_service.tools.dns import register_dns_tools

register_dns_tools(registry, backend)
```

## Tool behavior

### Basic DNS

- `dns.lookup` queries a record with the source's default resolver or an
  explicitly selected server. Its result separates command execution, DNS
  response status, and answer presence.
- `dns.reverse_lookup` validates an IPv4 or IPv6 address, constructs its reverse
  name, and queries PTR records.

### Registrar and authoritative DNS

- `domain.registrar_find` reads only Registrar frontends explicitly published
  through `agent.exposed.registrar_url` metadata. Its reserved `filter` must
  currently be empty.
- `domain.registrar_request` sends bounded `GET` or `POST` requests from the
  selected source to a discovered Registrar origin. It accepts same-origin paths,
  reports redirects without following them, and returns HTML/HTTP evidence so an
  Agent can discover the frontend workflow by starting with `GET /`.
- `domain.rdds_lookup` selects WHOIS or RDAP with `protocol`, and selects the
  Registrar business view or Registry ledger view with `authority`. Both
  endpoints are discovered from explicit service metadata.
- `dns.authoritative_find` takes a known source and returns only the authoritative
  DNS services explicitly assigned to it, including the service ID and paired
  Primary/Secondary addresses.
- `dns.configure` provisions an authorized Primary/Secondary zone and replaces
  or deletes RRsets. It verifies authority and Primary/Secondary convergence.

Registrar sessions are scoped to the selected source and Registrar origin. With
`authentication=auto` (the default), the source uses its provisioned identity if
available; `required` rejects missing authentication and `none` remains
anonymous. Cookies and identity state stay inside the source container. A source
name is not itself a credential: callers must be authorized to select that source,
and DNS control additionally requires the private key provisioned into it.

### Diagnostics

- `dns.compare` queries the same record through several servers and compares
  statuses, answers, TTLs, latency, and timeouts.
- `dns.trace` follows the DNS delegation path and returns each observed step.
- `dns.check_delegation` compares parent referral NS/glue with the authoritative
  NS data served by child servers.

## Registration architecture

The B02a example keeps the control boundaries separate:

```text
Agent -> tool-service -> selected source
                           |-> Loom Registrar frontend
                           |      -> Namingo EPP client
                           |             -> Namingo Registry
                           |                    -> .com hidden primary
                           |                           -> public secondaries
                           |
                           `-> source-owned authoritative DNS Primary/Secondary

Namingo Registrar backend node
  |-> Registrar WHOIS/RDAP -> loom adapter -> read-only Loom MariaDB
  |-> Registry WHOIS/RDAP -> Namingo Registry MariaDB
  `-> optional automation
```

- Loom owns the customer-facing HTML, sessions, orders, invoices, and domain
  lifecycle.
- The independent Namingo Registrar backend uses its upstream `loom` adapter to
  read Loom MariaDB through a source-restricted, read-only account. It supplies
  WHOIS/RDAP. B02a leaves Namingo automation disabled because this connection is
  read-only; Loom itself performs order-driven lifecycle provisioning.
- Namingo Registry is authoritative for domain uniqueness, sponsorship,
  nameservers, and glue. Registrar-to-Registry operations use EPP over TLS.
- Registry Zone Writer publishes the TLD zone to a query-hidden Primary, which
  transfers it to public `.com` secondaries.
- The source-owned DNS pair serves the child zone. Update and transfer credentials
  are separate, and ordinary sources cannot modify the parent zone directly.

The Registrar URL is service-owned metadata. Tools must not infer an API from
container names, IP addresses, or Namingo roles, and `credential_ref` is an opaque
reference rather than a secret or an endpoint description.

Architecture documentation:

- [End-to-end architecture and Agent workflow](docs/domain_register_design.md)
- [端到端架构与 Agent 调用流程](docs/domain_register_design_zh.md)
- Namingo Registrar and Loom: [English](docs/NamingoRegistrar.md) / [中文](docs/NamingoRegistrar_zh.md)
- Namingo Registry and TLD DNS: [English](docs/NamingoRegistry.md) / [中文](docs/NamingoRegistry_zh.md)

## `example.com` workflow

The end-to-end B02a workflow is:

1. Call `domain.registrar_find` and select the exposed Loom origin.
2. Call `dns.authoritative_find` with the selected source and choose its returned
   authoritative DNS service.
3. Call `dns.configure` with the discovered service ID to provision `example.com`
   and configure records on both child authoritative servers.
4. Start with `domain.registrar_request` on `/`, retain its `session_id`, and
   follow Loom's HTML forms and CSRF fields using explicit same-origin requests.
5. Submit an order containing `ns1.example.com` and `ns2.example.com` plus their
   IPv4 glue, then pay its invoice.
6. Loom uses EPP to create the Registry objects. Zone Writer publishes the
   resulting NS/glue into `.com` and its public secondaries converge.
7. Verify the parent referral, child authority, and recursive A-record lookup.

After registration, ordinary records inside `example.com` are maintained by
calling `dns.configure`; purchasing the domain again is unnecessary. Changing
the delegated nameservers or glue remains a Registrar/Registry operation rather
than a child-zone update.

## Tests

Fake-backend tests require no Docker:

```bash
.venv/bin/python -m pytest \
  seedemu_tool_service/tools/dns/tests/fakebackend -v
```

Docker-backend tests expect an already generated and running B02a deployment:

```bash
.venv/bin/python -m pytest \
  seedemu_tool_service/tools/dns/tests/dockerbackend -v
```

The purchase test requires a fresh Registry because it intentionally registers
`example.com`. It also uses `domain.rdds_lookup` to verify both the Registrar
view backed by Loom and the Registry view backed by Namingo Registry through
the caller-selected `whois` or `rdap` protocol.
domain from Loom MariaDB and that both B02a recursive resolvers return the
configured address:

```bash
.venv/bin/python -m pytest \
  seedemu_tool_service/tools/dns/tests/dockerbackend/test_domain_purchase_workflow.py \
  -vv
```

Use `--show-dns-results` when structured tool results are needed during
debugging. Docker tests close temporary Registrar sessions, but they do not tear
down the deployment or remove purchased-domain and DNS state.
