# DomainService

DomainService provides composable domain registration, customer purchases, DNS hosting,
and simulated payments for the emulation network.

| Service | Purpose |
| --- | --- |
| `NamingoRegistryService` | Registry, TLDs, EPP registrar access, and parent-zone delegation publication |
| `FossBillingRegistrarService` | Client portal, domain products, orders, and invoices |
| `DnsService` | Primary/secondary authoritative DNS, dynamic update authorization, hosting APIs, and DNS products |
| `FakePaymentService` | Independent simulated checkout endpoint |

[H12](../../examples/H12_domain_name_purchase/README.md) provides the complete purchase
environment. [H13](../../examples/H13_browser_agent/README.md) adds a browser and agent in
one container. H12 uses `domain_name_purchase.py`; H13 uses `browser_agent.py`. These generate
deployment files. Build and start manually from `output`; services initialize automatically. See each example for cleanup instructions.

## DNS Extension

DNS hosting and update authorization are implemented together in
`DnsService/DnsService.py`. `DnsService` inherits SeedEmu's native
`DomainNameService`. Its zone lookup override matches the parent except for changing
`zone.getName() == domain` to `zone == domain`; the parent is unchanged.

After building the base DNS topology, H12 uses the native `Emulator.merge()` with `DnsServiceMerger`
to preserve existing zones, nodes, and bindings in the subclass. H13 reuses H12. Merge before
creating authorizations. The subclass retains the layer name `DomainNameService`, so Registry
render dependencies and `emu.getLayer('DomainNameService')` remain valid.

```python
from seedemu.core import Emulator
from DomainService import DnsService, DnsServiceMerger

dns_extension = Emulator()
dns_extension.addLayer(DnsService())
emu = emu.merge(dns_extension, [DnsServiceMerger()])
```

`authorizeZoneUpdates()` validates zones and DNS virtual nodes and returns an independent
`DnsUpdateAuthorization`. During rendering, native `getMasterIp()` identifies the configured
primary and TSIG credentials are populated. Publishers read them through `getZones()` and
`getCredentials(zone)`. Reading credentials before DNS rendering raises an error; publishers
must declare a render dependency on the DNS layer.

Update authorization neither stores publisher objects nor calls Registry interfaces.
`dns.addHosting()` explicitly enables APIs on a DNS pair. The returned object exposes
addresses and credentials; it does not configure a registrar or register Registry hosts.
`hosting.addRegistrarToRateLimitWhitelist()` optionally exempts a bound registrar from API rate limits while
retaining authentication. `registry_server.addNameServers()` separately schedules local
Registry host registration. `registrar.setDnsHostings(hosting)` only selects the existing
pair for the registrar's own extension and product. Each service installs its own nodes;
no cross-service installation Hook is used.

Python source changes do not update existing images or containers. Follow the selected
[H12](../../examples/H12_domain_name_purchase/README.md) or
[H13](../../examples/H13_browser_agent/README.md) workflow to regenerate output, build,
and start. Each render generates new TSIG keys: deploy Registry and the relevant
TLD DNS containers from the same generation, rather than rebuilding only one side.
Interface checks establish code availability; live publication still requires verification
of parent delegation and primary/secondary synchronization after deployment.

## Usage

Use a Python environment that can import `DomainService` and `seedemu`. On an existing
emulator `emu`, configure the service:

```python
from DomainService import NamingoRegistryService
from seedemu.core import Binding, Filter

registry = NamingoRegistryService()
server = registry.install('registry')
server.setTlds(['com', 'net'])
server.setAdminAccount('admin@example.com', '123456')
server.setDatabasePassword('registry-demo-password')
server.setPortForwarding(18081)
emu.addLayer(registry)
emu.addBinding(Binding('registry', filter=Filter(asn=151, nodeName='host_1')))
# Finally call emu.render() and emu.compile(...).
```

The target host must exist and must not run conflicting applications. Rendering writes
installation, configuration, and startup operations. `setEppPort(port)` sets the EPP port,
defaulting to 700. The web panel listens on 8080; configure its host port with
`setPortForwarding(host_port)`. Use the inherited `setDisplayName()` to change display names.

Registry uses a pinned upstream commit, PHP 8.5, `.com`/`.net` initialization, local MariaDB
and Redis, the control panel, EPP TLS, DAS, and lifecycle jobs every five minutes. Defaults
are in `NamingoRegistryService/NamingoRegistryService.py`; each Server can override credentials.
`setAdminAccount(email, password)` and `setDatabasePassword(password)` configure initial
installation, not password rotation on a running database.

`setTlds()` defines the initial TLD list; `getTlds()` returns a copy. Names such as `com` and
`.com` are normalized to lowercase and deduplicated. Only single-label ASCII names are
accepted; use Punycode for internationalized names. The upstream database limits labels to
31 characters, and the list must not be empty. Each TLD receives the pinned upstream defaults
for registration, renewal, transfer, and restore prices. Unselected upstream example TLDs
are excluded. Existing databases are not migrated.

## Port Forwarding and Web Access

Registry and FOSSBilling listen on container port `8080`; FakePayment's internal port is
configured with `setPort()`. Set host ports using `setPortForwarding(host_port)`, or pass
`None` to disable forwarding. Default host ports are Registry `18081`, FOSSBilling `18080`,
and FakePayment `18083`. Registry and FOSSBilling can share an internal port because they
run in different containers, but their host ports must differ on the same Docker host.

H12 configures these mappings in its entry point:

```python
# Registry: forward host port 18081 to port 8080 in the Registry container.
registry_server.setPortForwarding(18081)

# FOSSBilling: forward host port 18080 to port 8080 in the FOSSBilling container.
registrar.setPortForwarding(18080)
```

Mappings are added to each instance's actual bound host during installation. After generating,
building, starting, and waiting for initialization, use the Docker host's browser:

| Endpoint | URL | Purpose |
| --- | --- | --- |
| Registry control panel | <http://localhost:18081/> | Manage the registry, TLDs, and registrars |
| FOSSBilling client portal | <http://localhost:18080/> | Client login, purchases, orders, and invoices |
| FOSSBilling administration | <http://localhost:18080/admin> | Manage clients, TLD products, prices, and registrar settings |

FOSSBilling client and admin portals share port `18080` and differ by URL path; no extra
admin port is required. A Registry-only deployment provides only its control panel.
Initial demo accounts are listed below. Scenario overrides take precedence, and changing
defaults does not automatically update existing accounts.

| Account | Email | Demo password |
| --- | --- | --- |
| Registry administrator | `admin@example.com` | `123456` |
| FOSSBilling client | `user@example.com` | `Aa123456` |
| FOSSBilling administrator | `admin@example.com` | `Aa123456` |

FOSSBilling's `setPortForwarding(port)` configures both forwarding and the corresponding
local site URL. Requests through `localhost:port` or `127.0.0.1:port` retain that origin in
links and redirects; internal access and CLI use the bound host's internal address.
Passing `None` disables forwarding and the local URL override. Startup applies the URL
configuration after regeneration, build, and container startup.

Registry's EPP port `700` serves registrar protocol traffic, not a website. Generated Docker
configuration does not mean the websites are running; wait for initialization.

## DNS Authorization

Registry can run independently without DNS publication. When `DomainNameService` exists,
it renders first. Configure authorization before rendering:

```python
dns = emu.getLayer('DomainNameService')
authorization = dns.authorizeZoneUpdates(
    ['com', 'net'],
)
server.setDnsAuthorization(authorization)
```

`zones` contains zone names only, either TLDs or subdomains, optionally with trailing dots.
DNS discovers hosting nodes through `getZoneServerNames()`. A single node is the primary;
with multiple nodes, rendering uses `getMasterIp()` to identify exactly one primary and
uses the remaining nodes as secondaries. This normally follows `setMaster()` and the default
NS/SOA configuration. Virtual node names need not be repeated.

Each node must already host the relevant zone, and all zones on selected nodes must be
included in the authorization. Registry's `setDnsAuthorization(authorization)` validates that
authorized zones belong to its managed TLDs; a subset is allowed. Installation validates
again in case TLD settings changed. This method does not create DNS nodes, zones, or root
delegations; the scenario must configure those when adding a TLD.

DNS owns update authorization and primary/secondary configuration, populating targets and
keys in the authorization object. Registry reads credentials during installation and writes
them to its bound host, without repeating AS or host names. Authorization allows only
NS/A/AAAA delegation updates below the zone, protecting its apex and nameserver records;
it does not grant arbitrary record-type writes.

Each TLD has separate publication and zone-transfer TSIG keys. Transfers are disabled for
a primary without secondaries; otherwise transfers and notifications are signed. Every
render creates new credentials, so update Registry and the relevant DNS nodes together.
Publisher settings are written to `/opt/registry/dns-publication-<tld>.json`; the combined
manifest is `/opt/registry/dns-publications.json`, keyed by zone names such as `com.`.

Authorization alone does not start the publisher. Call
`enableDnsPublication(['com', 'net'])` on Registry to enable periodic publication for the
authorized TLDs, with a default interval of 30 seconds.

## File Organization

Service classes resolve virtual-node links and coordinate layer dependencies. Server
instances own their settings and install only on their bound nodes. Their `install()`
methods order private installation steps for software, configuration, and optional features.
DNS Hosting follows the same ownership rule through its primary/secondary pair object;
it resolves hosting after native DNS rendering, when NS records are available.
FakePayment keeps its short installation sequence together.
Each service stores templates directly in `templates/` and defines an on-demand
`load_template(filename)` loader in its service file. For example:

```text
DomainService/
└── NamingoRegistryService/
    ├── NamingoRegistryService.py  # Interfaces, defaults, and installation
    └── templates/             # SQL, PHP, shell, and Nginx templates
```

Templates use named `__PLACEHOLDER__` markers; Server instances supply account settings. PHP and SQL
strings are escaped separately, and web database passwords are written as quoted dotenv
values. `DomainService` exports classes such as `NamingoRegistryService` and `NamingoRegistryServer`;
DNS authorization is provided by the emuvista subclass's
`DnsService.authorizeZoneUpdates()`.

Substantial PHP, SQL, shell, and Nginx files live in `templates/`, with names describing
what they configure, initialize, or start. Short startup wrappers, INI settings, cron
entries, and small SQL/PHP snippets are written directly in the corresponding installation
method. For example, `create-nameserver-hosts.php` creates Registry host objects,
`configure-dns-hosting-product.php` configures the registrar product, and
`fake-payment-adapter.php` supplies FOSSBilling's required `FakePayment.php` adapter.
`NamingoRegistryService.py` loads the templates, substitutes instance parameters with
appropriate escaping, writes files, and schedules build/startup commands. JSON configuration
is serialized with `json.dumps()`; resolved DNS keys are supplied by the authorization object.

## FOSSBilling Registrar Service

Like Registry, this service keeps installation methods on `FossBillingRegistrarServer`,
with instance defaults in `__init__()` and separate `templates/`. It pins FOSSBilling 0.8.7 and the EPP installer.

```python
from DomainService import FossBillingRegistrarService

registrar_service = FossBillingRegistrarService()
registrar = registrar_service.install('fossbilling')
registrar.setRegistry('registry')
registrar.setTlds(['com', 'net'])
registrar.setTldPrice('com', registration='11.99', renewal='11.99', transfer='11.99')
registrar.setAdminAccount('admin@example.com', 'Aa123456')
registrar.setClientAccount('user@example.com', 'Aa123456')
registrar.setReservedDomains(['google.com', 'twitter.com', 'example.com'])
emu.addLayer(registrar_service)
emu.addBinding(Binding('fossbilling', filter=Filter(asn=150, nodeName='host_1')))
registrar.setPortForwarding(18080)
```

`setRegistry()` accepts a Registry virtual node and optional `username`, `password`, and
`prefix`. Rendering derives addresses from bindings and the EPP port from Registry to
configure the connection and source-IP allowlist. Registry and FOSSBilling require distinct
hosts; multiple registrars need distinct accounts and prefixes. Omitting `setTlds()` inherits
Registry's TLDs; an explicit list must be a subset. Initial prices default to 11.99; existing
prices and products are preserved. `setClientAccount(..., profile={...})` overrides default
contact data; see `FossBillingRegistrarServer.__init__()` for fields.

After database initialization and before EPP starts, Registry creates registrar accounts,
allowlists, and reserved domains. FOSSBilling connects to that Registry EPP process; no
second EPP service is needed. Existing account password/prefix mismatches and reserved domains
owned by another registrar are rejected. This is not a runtime password-rotation interface.
Changed bound IPs require regeneration and deployment. EPP uses simulation self-signed
certificates and the corresponding adapter verification settings.

The generated `initialize-fossbilling.py` runs at container startup. It waits for the local
database and web server, reads `setup-config.json` and `epp-connection.json`, then handles
initial installation, URLs, TLD bindings, client creation, installer removal, and cron.
Success creates `/run/fossbilling-initialized`; failure creates
`/run/fossbilling-initialization.failed`. Logs are in `/var/log/fossbilling-initialize.log`.
Existing administrators and prices are preserved. An existing demo client's password must
match; only missing contact data is filled. Checkout activates orders after committing the
transaction.

Generated initialization settings contain simulation credentials and are restricted to
root. Build directories and emulator snapshots also contain these settings. See
[H12](../../examples/H12_domain_name_purchase/README.md) for runtime commands.

## Rebuild and Initialize

From `examples/H12_domain_name_purchase`, use the virtual environment with SeedEmu dependencies:

```bash
python domain_name_purchase.py
cd output
docker compose build
docker compose up -d
cd ..
```

The entry point always includes Registry, FOSSBilling, DNS Hosting, and FakePayment and only
generates deployment files. Build and start manually inside `output`. Services initialize
at startup, including DNS Hosting product configuration. For initialization failures, inspect
logs, fix the issue, and restart the affected container. The Python entry point does not
invoke Docker build or startup. See the [startup guide](../../examples/H12_domain_name_purchase/README.md).

## DNS Hosting and Registry Delegation Publication

`DnsService` integrates pinned BIND API and FOSSBilling DNS Hosting releases. The
entry point is [`domain_name_purchase.py`](../../examples/H12_domain_name_purchase/domain_name_purchase.py).
Run the generation, build, and startup sequence above from the H12 directory.

The scenario retains the `.com`/`.net` Registry and FOSSBilling services and uses two existing
AS170 hosts: `host_0` for primary DNS and `host_1` for secondary DNS. The hosting API shares
the primary host. Web endpoints retain ports 18080/18081. DNS Hosting is purchased and managed
inside the FOSSBilling client portal, without a separate port-18082 website. BIND APIs listen
on each node's internal IPv4 address at port 7650, with no host port forwarding.

### Scenario Configuration

Install the primary and secondary in order on the merged `DnsService`, binding them
to distinct existing hosts:

```python
dns = emu.getLayer('DomainNameService')

# Install the primary first so ns1/ns2 match primary/secondary addresses.
dns.install('hosted-dns-primary').addZone('example.com.').setMaster()
dns.install('hosted-dns-secondary').addZone('example.com.')
emu.addBinding(Binding('hosted-dns-primary', filter=Filter(asn=170, nodeName='host_0')))
emu.addBinding(Binding('hosted-dns-secondary', filter=Filter(asn=170, nodeName='host_1')))

hosting = dns.addHosting('hosted-dns-primary', 'hosted-dns-secondary', domain='example.com')
hosting.addRegistrarToRateLimitWhitelist('fossbilling')
registry_server.addNameServers(hosting, epp_username=registrar.getEppUsername())
registrar.setDnsHostings(hosting)
```

Each pair hosts only the selected static service domain, without other custom includes.
Customer zones created through BIND API are managed separately. Primary/secondary addresses,
authorized client IPs and product nameservers come from actual bindings, not fixed
`10.170.0.71/72` addresses. Each FOSSBilling instance selects one existing hosting pair. Distinct hosting pairs
cannot overlap DNS nodes. `domain` accepts a second-level ASCII domain, which must first be
reserved using FOSSBilling's `setReservedDomains()`. The example reserves `google.com`,
`twitter.com`, and `example.com` in the registrar configuration.

On the Registry instance:

```python
registry_server.enableDnsPublication(['com', 'net'], interval=30)
```

Only managed and authorized TLDs can be published. The publisher reads the existing EPP
database configuration and each `dns-publication-<tld>.json`, then sends signed NS/glue updates
to the corresponding parent zone. Each TLD uses a separate state file and process lock.
Failed updates do not save successful state and are retried in later cycles. Domains without
nameservers, under clientHold/serverHold, or outside their validity period are not published.
The publisher handles only nameservers and in-domain glue, not customer website A/AAAA records.

### Initialization and Data Boundaries

The service generates separate API credentials for the primary and secondary DNS nodes
at render time and provisions matching copies to the registrar. Credential files are mode
0600. Deploy all three containers from the same render; existing API accounts reject
mismatched credentials rather than being silently overwritten.

At startup, Registry creates its nameserver host records. The registrar waits for local
FOSSBilling initialization, then activates the DNS extension and configures
the Bind product and category. Product configuration runs once per startup; customer orders
and payments are never retried. Inspect `/var/log/fossbilling-initialize.log` on failure.

Existing Registry hosts are checked for ownership, parent domain, addresses, and status;
conflicts roll back rather than overwrite data. Registering host objects does not set domain
NS delegation or alter website records in the static zone. Existing product prices remain;
if no product exists, initialization creates a free simulation product. Select among multiple
products with `registrar.setDnsHostings(hosting, product_id=ID)` before rendering. Credentials are not printed or
passed on command lines.

A domain purchase still requires separate nameserver configuration, DNS Hosting activation,
and website record configuration. Verify Registry domain/nameserver state, parent delegation,
primary/secondary authoritative zones, and recursive resolution separately. Static service
domains, configured products, or successful API authentication do not prove customer-domain
resolution.

## FakePayment

`FakePaymentService` provides an independent checkout for simulation only, without real funds.
`FossBillingRegistrarService` owns its payment adapter, configuration, and gateway initialization. Its scenario entry point is
`examples/H12_domain_name_purchase/domain_name_purchase.py`.

Selecting fakePayment displays confirmation and results in an embedded area of the invoice
page. The browser stays on FOSSBilling. On confirmation, checkout verifies the signature and
calls back to FOSSBilling. Refresh the invoice to check payment status; verify order activation
and domain registration separately.

Use the H12 generation, build, and startup sequence above. DNS Hosting and the payment
gateway initialize automatically. No host-side setup script is required.

| Service | Host URL | Usage |
| --- | --- | --- |
| FOSSBilling client portal | `http://localhost:18080/` | Log in, purchase services, and open invoices |
| FOSSBilling administration | `http://localhost:18080/admin` | Manage products, invoices, and gateways |
| Registry control panel | `http://localhost:18081/` | Manage registry data |
| FakePayment health check | `http://localhost:18083/health` | Returns `ok` when ready |
| FakePayment checkout | `http://localhost:18083/pay` | Signed POST endpoint for the embedded invoice form |

`/pay` accepts POST only; opening it in the address bar returns 404. DNS Hosting is managed
inside the client portal. A submitted payment or successful initialization does not establish that
the invoice is paid, the order is active, the domain is registered, or DNS is published.
Check each outcome separately.

### Custom Bindings and Ports

```python
from DomainService import FakePaymentService

fake_payment_service = FakePaymentService()
checkout = fake_payment_service.install('fake-payment')
checkout.setPort(8080)
# registrar is the FossBillingRegistrarServer instance.
registrar.setPaymentService('fake-payment')
emu.addLayer(fake_payment_service)
emu.addBinding(Binding('fake-payment', filter=Filter(asn=160, nodeName='host_1')))
checkout.setPortForwarding(18083)
```

Internal payment and callback URLs come from bound nodes rather than fixed topology IPs.
Each registrar selects one checkout; each checkout authorizes one callback origin.
Checkout and registrar require separate
hosts. `initialize-payment-gateway.sh` enables the gateway after local FOSSBilling initialization, logging
to `/var/log/fake-payment-initialize.log`.

`setPort()` sets the container port; `setPortForwarding()` sets the host mapping.
FOSSBilling derives localhost and 127.0.0.1 checkout URLs from the selected checkout's
forwarded port and its own forwarded port. Unmatched Hosts use the
simulation payment URL. If either service disables forwarding, only internal payment
addresses are configured. Custom external domains and HTTPS proxies are not inferred.

`checkout.setSharedSecret()` sets the signing secret. Each service writes its own copy
to its own container during installation. Do not commit secrets. The default is for simulation only. Address, port, or
secret changes require regeneration and rebuilding.

If deployed containers lack DNS Hosting components, regenerate and rebuild the scenario.

To clean the current example's containers, networks, and data volumes, run from H12:

```bash
docker compose -f output/docker-compose.yml down --remove-orphans --volumes
```

This removes the same Compose project's containers, including orphans, networks, writable
container layers, and managed volumes. Images, generated files, external volumes, and host
bind-mount directories remain. Adjust the Compose path for custom output. Cleanup does not
build or initialize services automatically.

## H13: Browser and Agent in One Container

[H13](../../examples/H13_browser_agent/README.md) combines the complete domain services with
browser-agent. It joins AS154/net0 through `Docker.attachCustomContainer()` without consuming
an existing host. The agent UI is at `http://localhost:18089/`; the agent and Chromium are
installed in that container image.

List egress destinations in H13's `egress_urls.txt`, one URL, domain, or IP per line. Startup
configures DNS and routes automatically. After initial generation, build, and startup, address
changes require only restarting browser-agent, not editing network scripts or rebuilding.
From H13, run `python browser_agent.py`, then build and start inside `output`. Cleanup uses
`docker compose -f output/docker-compose.yml down --remove-orphans --volumes`; adjust the
path for custom output. H12 and H13 share the default project name and application ports,
so run them as alternatives.

## Build Caches and Installation Failures

Dependency installation uses ordinary Docker layers compatible with the legacy builder
and BuildKit. Registry, FOSSBilling, and DNS Hosting
install base packages, the PHP repository, system services, PHP extensions, source downloads,
and Composer dependencies in separate layers. Each apt layer refreshes indexes before
installing its packages, avoiding stale indexes for newly requested packages.

apt uses its native retries and connection timeouts. Repository setup and Composer run directly and
return a nonzero status on failure, preserving the tools' original output.

H13 separates system dependencies, desktop components, Python
packages, Chromium system dependencies, and browser installation. Agent source and model
profiles are copied afterward; source changes do not themselves reinstall dependencies.

New Dockerfile instructions rebuild affected layers. Successful layers are reused when
instructions and base images are unchanged. Failed installation layers may download
dependencies again on retry. Compose cleanup does not remove images or build caches.
The compiler generates base software layers, whose cache behavior remains managed by Docker.
