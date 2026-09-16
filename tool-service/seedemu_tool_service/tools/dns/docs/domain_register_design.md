# Source-owned DNS and domain-registration design

## Architecture overview

B02a demonstrates how an Agent configures authoritative DNS inside a SeedEmu network and registers `example.com` through Loom and Namingo. The system consists of the Agent tool layer, the Registrar side, the Registry side, and the parent and child DNS services.

```mermaid
%%{init: {"theme": "base", "flowchart": {"rankSpacing": 70, "nodeSpacing": 30}, "themeVariables": {"background": "#000000", "primaryColor": "#111827", "primaryTextColor": "#ffffff", "primaryBorderColor": "#9ca3af", "lineColor": "#d1d5db", "clusterBkg": "#0b0f14", "clusterBorder": "#6b7280", "edgeLabelBackground": "#000000"}}}%%
flowchart TD
    agent["Agent"]

    subgraph tool_layer["Agent tool layer"]
        tools["DNS / domain tools"]
        runtime["Docker RuntimeBackend"]
        source["Selected source<br/>network requests and local sessions"]
    end

    subgraph registrar_side["Registrar side"]
        loom["Loom HTTPS frontend<br/>customers, orders, invoices, lifecycle"]
        loom_db[("Loom MariaDB")]
        loom_epp["Loom Namingo EPP client"]
        namingo["Namingo Registrar<br/>loom backend"]
        rdds["WHOIS / RDAP"]
    end

    subgraph registry_side["Registry side"]
        registry["Namingo Registry<br/>EPP and registration objects"]
        registry_db[("Registry MariaDB")]
        writer["Registry Zone Writer"]
    end

    subgraph parent_dns[".com parent authoritative DNS"]
        hidden["Hidden Primary"]
        public_b["Public Secondary B"]
        public_c["Public Secondary C"]
    end

    subgraph child_dns["Source-owned example.com DNS"]
        child_primary["ns1 Primary"]
        child_secondary["ns2 Secondary"]
    end

    agent -->|"Invoke tools"| tools --> runtime --> source
    source -->|"HTTPS forms and session"| loom
    loom --> loom_db
    loom -->|"Paid order"| loom_epp -->|"EPP over mutual TLS"| registry
    namingo -->|"Read through loom adapter"| loom_db
    namingo --> rdds
    registry --> registry_db --> writer
    writer -->|"Publish .com zone"| hidden
    hidden -->|"NOTIFY + AXFR/IXFR"| public_b
    hidden -->|"NOTIFY + AXFR/IXFR"| public_c
    source -->|"dns.authoritative_find + dns.configure"| child_primary
    child_primary -->|"AXFR/IXFR"| child_secondary
    classDef dark fill:#111827,stroke:#9ca3af,color:#ffffff
    class agent,tools,runtime,source,loom,loom_db,loom_epp,namingo,rdds,registry,registry_db,writer,hidden,public_b,public_c,child_primary,child_secondary dark
    style tool_layer fill:#151008,stroke:#f59e0b,color:#ffffff
    style registrar_side fill:#0b1220,stroke:#60a5fa,color:#ffffff
    style registry_side fill:#17110a,stroke:#f59e0b,color:#ffffff
    style parent_dns fill:#1a0d14,stroke:#f472b6,color:#ffffff
    style child_dns fill:#071a12,stroke:#4ade80,color:#ffffff
```

Loom is the business entry point for registration. It stores customers, orders, and invoices, then uses EPP to create contact, host, and domain objects in Namingo Registry after payment. Namingo Registrar reads the same Loom data through its `loom` backend and exposes it through WHOIS and RDAP. The Registry Zone Writer publishes successful delegations to the `.com` authoritative DNS system.

The parent and child zones hold different data: `.com` contains the NS delegation and glue for `example.com`, while the source-owned DNS contains records such as `www.example.com`. Standard DNS delegation connects the two layers.

## Agent tool workflow

```mermaid
sequenceDiagram
    participant A as Agent
    participant T as tool-service
    participant S as selected source
    participant L as Loom
    participant R as Namingo Registry
    participant P as .com DNS
    participant D as example.com DNS

    A->>T: domain.registrar_find
    T-->>A: Loom origin
    A->>T: dns.authoritative_find(source)
    T-->>A: service ID, Primary, Secondary
    A->>T: dns.configure(discovered service, zone, A record)
    T->>S: Execute DNS configuration
    S->>D: Update Primary and synchronize Secondary
    D-->>A: Authoritative answers and matching SOA
    A->>T: domain.registrar_request(GET /)
    T->>S: Establish source-local session
    S->>L: HTTPS + source token
    L-->>A: HTML, session_id, CSRF form
    A->>T: domain.registrar_request(registration form)
    T->>L: Domain, contacts, NS, and glue
    L-->>A: Invoice redirect
    A->>T: domain.registrar_request(payment form)
    T->>L: Balance payment
    L->>R: EPP contact/host/domain create
    R-->>L: Registration succeeds
    R->>P: Zone Writer publishes NS/glue
    A->>T: dns.check_delegation
    T->>P: Query parent referral/glue
    T->>D: Query child NS/SOA
    A->>T: dns.lookup through both resolvers
    T-->>A: www.example.com A
```

The concrete call sequence is:

1. The Agent calls `domain.registrar_find` to discover the Loom origin published in service metadata.
2. With the selected source, it calls `dns.authoritative_find` to discover the assigned service ID and paired Primary/Secondary addresses.
3. It passes that discovered service ID to `dns.configure` to provision the `example.com` child zone and its records. The tool verifies both authorities and their SOA state.
4. It calls `domain.registrar_request` for the Loom home page. The selected source establishes an authenticated session, and the tool returns the page, `session_id`, and HTTP evidence.
5. Using the same `session_id`, the Agent reads the registration form, preserves its CSRF fields, and submits the domain, contacts, `ns1/ns2`, and glue addresses.
6. Loom creates an order and invoice. The Agent reads the payment page and submits a balance payment.
7. Loom's EPP client creates the registration objects in Namingo Registry. Zone Writer then publishes the `.com` delegation.
8. The Agent calls `dns.check_delegation` to compare parent NS/glue with both child authorities.
9. It calls `dns.lookup` through both B02a recursive resolvers to verify the final A record.

Registrar sessions and private credentials remain in the selected source. The Agent works with discoverable Loom pages and structured DNS results. Parent-zone changes go through the Registrar/Registry path, while ordinary child-zone records continue to use `dns.configure` after purchase.

## Namingo Registrar and Loom

B02a configures `NamingoRegistrarService` with the `loom` backend. Its WHOIS/RDAP reads Loom MariaDB as the Registrar business view. Namingo Registry separately exposes WHOIS/RDAP backed by Registry MariaDB as the final ledger view. The Agent selects the protocol and authority through `domain.rdds_lookup`. Namingo automation is disabled in B02a because Loom owns the order-driven lifecycle.

## DNS publication and resolution

Namingo Registry passes registration data to Zone Writer. Zone Writer publishes it to the `.com` hidden Primary, which synchronizes the two public Secondaries using NOTIFY and TSIG-protected AXFR/IXFR. Recursive resolvers obtain the `example.com` referral and glue from a public Secondary and then query the source-owned authoritative DNS.

Dynamic delegation may interact with recursive caches. The complete test therefore waits for both B02a recursive resolvers instead of validating only one, and it does not flush caches to manufacture a successful result.

## Implementation and validation

The principal implementation locations are:

- `seed-emulator/examples/internet/B02a_domain_registration/domain_registration.py`
- `seed-emulator/seedemu/services/LoomRegistrarService.py`
- `seed-emulator/seedemu/services/NamingoRegistrarService.py`
- `seed-emulator/seedemu/services/NamingoRegistryService.py`
- `seedemu-agent-tools/tool-service/seedemu_tool_service/tools/dns/`

The Docker purchase test covers the Loom session, order and payment, EPP registration, WHOIS/RDAP, parent delegation, child authoritative responses, and final resolution through both recursive resolvers.
