# H12: Domain Purchase and DNS Hosting

This example deploys Registry, FOSSBilling, primary/secondary DNS Hosting, and FakePayment
for domain purchases, simulated payments, and DNS configuration. The scenario defines host
bindings, ports, accounts, TLDs, and products; the service packages generate installation
and startup operations.

## Layout

```text
H12_domain_name_purchase/
├── domain_name_purchase.py
└── output/
```

## Startup and Initialization

Use a Python environment that can import `seedemu` and `DomainService`, with Docker Compose
available. Run from this example directory:

```bash
python domain_name_purchase.py
cd output
docker compose build
docker compose up -d
cd ..
```

The scenario always includes all four services. `domain_name_purchase.py` only generates
deployment files in `output`; build and start the containers manually from that directory.
Existing image layers may use the build cache. Uncached dependency installation requires
network access.

Services initialize locally when their containers start:

- FOSSBilling waits for its database and web server, performs the initial installation,
  configures the site URL, EPP/TLDs, demo client, and cron, then removes the installer.
- Registry registers hosting nameserver hosts after creating the registrar and reserved
  domains. Existing records are checked without being overwritten.
- FOSSBilling installs its payment adapter and enables the gateway after local initialization;
  FakePayment starts the independent checkout endpoint.

DNS Hosting also initializes automatically. The example explicitly creates the DNS API
pair with `dns.addHosting()`, registers NS hosts with `namingo_server.addNameServers()`,
and associates the registrar using `fossbilling_server.setDnsHostings(dns_hosting)`. The service provisions separate primary and
secondary API credentials into the DNS nodes and the registrar, then configures the DNS
extension and product after local FOSSBilling initialization completes. Credentials are stored
in mode-0600 files; deploy the DNS nodes and registrar from the same render.

Initialization failures are recorded in `/var/log/fossbilling-initialize.log` and
`/run/fossbilling-initialization.failed`. Fix the cause and restart the registrar to retry.
`/run/fossbilling-initialized` marks successful product configuration. Existing administrators,
clients, and product prices are preserved. Startup does not pay invoices or retry customer orders.

## Generation Options

The Python entry point generates configuration without building or starting Docker.
Generation accepts `--output PATH`, `--platform amd`, and `--platform arm`.

## Automated Tests

`example.yaml` uses the same `seedemu.testing` lifecycle runner as
`seed-emulator/examples/sample`. From the workspace containing `emuvista` and
`seed-emulator`, run:

```bash
emuvista/.venv/bin/python seed-emulator/seedemu/testing/cli.py all emuvista/examples/H12_domain_name_purchase/example.yaml --artifact-dir /tmp/h12-test-results
```

Use a Python environment with the scenario dependencies installed. `all` cleans
`output`, compiles, builds, starts containers, waits for initialization, runs probes
and custom tests, and tears down the Compose project in a final cleanup step.
Use this lifecycle on a disposable H12 deployment. Individual commands are
`compile`, `build`, `up`, `readiness`, `probe`, `test`, and `down`; replace `all`
in the command above to run a single stage. `up` also runs readiness checks.

`test_runtime.py` discovers nodes through SEED Emulator labels and checks
FOSSBilling/payment initialization, HTTP connectivity, the Registry TLS EPP greeting,
DNS API port connectivity, BIND configuration/control, primary/secondary NS answers,
and recursive resolution.

After these checks pass, the same script runs its purchase workflow inside the
registrar using the demo customer account. It registers a unique `h12-test-<random>.com` domain through
the customer API, submits the invoice's signed FakePayment form, waits for the paid
invoice and active order, sets the hosting nameservers, purchases DNS Hosting, and
adds `www` pointing to `192.0.2.123`. The runtime test then checks the Registry domain
and nameservers, COM parent delegation, both authoritative DNS answers, and recursive
resolution. Checkout and payment are submitted once; only status and DNS checks poll.

Each run creates new orders and a new domain. Test data remains in the deployment;
the test does not cancel orders or delete registrations. On failure, the purchase
result includes the domain, last stage, and known order/invoice IDs for inspection.

Failures return a nonzero exit code. The artifact directory contains command logs,
stage summaries, and `h12-custom-runtime-test.json` with individual runtime results.

## Web Endpoints

After startup and initialization, open these URLs in the Docker host's browser:

| Endpoint | URL |
| --- | --- |
| FOSSBilling client portal | <http://localhost:18080/> |
| FOSSBilling administration | <http://localhost:18080/admin> |
| Registry control panel | <http://localhost:18081/> |
| FakePayment health check | <http://localhost:18083/health> |

The demo FOSSBilling administrator is `admin@example.com` and the client is
`user@example.com`, both with password `Aa123456`. The Registry administrator is
`admin@example.com` with password `123456`. Change initial settings in the scenario entry point.

Select fakePayment on a FOSSBilling invoice to confirm a simulated payment and view its
result inside the invoice page. Refresh the invoice afterward to check payment status.
The checkout `/pay` endpoint accepts signed POST requests only; opening it in the address
bar returns 404. DNS Hosting is purchased and managed through the client portal, with no
separate management website. The [H13 example](../H13_browser_agent/README.md) provides
the browser and agent chat interface.

Configure host ports with `setPortForwarding(host_port)`; pass `None` to disable forwarding.
FOSSBilling derives its local URL from the forwarded port, preserving localhost in links
and redirects for localhost requests. FOSSBilling derives local checkout
URLs from its own and the selected payment service's forwarded ports. See the [service documentation](../../services/DomainService/README.md).

## DNS Hosting and Resolution

The default products cover `.com` and `.net`; the scenario reserves `google.com`,
`twitter.com`, and `example.com`. Hosting nameservers are `ns1.example.com` and
`ns2.example.com`, at `10.170.0.71` and `10.170.0.72`. Their BIND APIs listen on internal
port 7650 without host port forwarding.

Customer domains require registration, nameserver configuration, DNS Hosting activation,
and records such as A/AAAA separately. The Registry publisher updates parent-zone NS/glue
records, waiting 30 seconds after each cycle. Recursive caches may retain older results.
Query authoritative and recursive DNS separately to distinguish record configuration
from delegation or cache problems:

```bash
dig @10.170.0.71 www.your-domain.com A +norecurse
dig @10.153.0.53 www.your-domain.com A
```

Run these commands in a container with access to the simulation network and substitute
the actual domain. Successful initialization does not prove purchase or resolution success:
check invoices, orders, Registry registration, parent delegation, and authoritative records.

## Container Selection and Products

Service bindings determine the Registry, registrar, and DNS nodes. No host-side setup
or container selection is needed. When multiple DNS products exist, select one on the
registrar with `registrar.setDnsHostings(dns_hosting, product_id=ID)` before rendering. Existing prices are
preserved; if no product exists, startup creates a free simulation hosting product.

## Cleanup and Data

```bash
docker compose -f output/docker-compose.yml down --remove-orphans --volumes
```

This removes the project's containers, networks, and managed volumes, including orphaned
containers. Images, build caches, and generated files remain. For a custom output directory,
replace `output/docker-compose.yml` with the corresponding path. External volumes and host
bind-mount directories are not removed. Nonpersistent container data is lost on removal.

H12 and H13 both default to the Compose project `output` and use the same application ports;
deploy one at a time. Generation does not clean data automatically. Check which data must
be preserved before switching deployments. Scripts forward underlying command output and
necessary error messages.
