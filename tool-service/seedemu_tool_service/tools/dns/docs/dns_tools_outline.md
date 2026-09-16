# DNS Tool Design Outline

The implemented DNS surface is intentionally small and split into three categories.

## Basic tools

- `dns.lookup`: query a record through the source's default resolver or an explicit server; distinguish command failure, DNS status, and an empty answer.
- `dns.reverse_lookup`: validate an IP address, construct its reverse name, and query PTR records.

## Domain registration and update

- `domain.registrar_find`: discover only Registrar origins explicitly exposed through `agent.exposed.registrar_url`. The reserved `filter` must be empty.
- `domain.rdds_lookup`: select `protocol=whois|rdap` and `authority=registrar|registry`; endpoints come from service-published metadata rather than tool-side addresses.
- `domain.registrar_request`: send bounded GET/POST requests from the selected source to a discovered same-origin path. Start with `GET /`; redirects and HTML are returned as evidence rather than interpreted as a fixed API.
- `dns.authoritative_find`: discover the authoritative DNS service IDs and Primary/Secondary addresses explicitly assigned to a known source.
- `dns.configure`: provision an authorized source-owned Primary/Secondary zone, replace or delete RRsets, and verify authoritative convergence.

Registrar cookies and identities remain inside the selected source. The source is the session/identity boundary, but its name is not a credential; ingress authorization and provisioned private credentials are still required.

## Diagnostic tools

- `dns.compare`: compare statuses, answers, TTLs, latency, and timeouts across servers.
- `dns.trace`: observe the delegation path from a selected starting point.
- `dns.check_delegation`: compare parent referral/glue with authoritative child NS data.
