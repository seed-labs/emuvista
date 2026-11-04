# SEEDemu Agent Tool Service


FastAPI service exposing agent-facing operations for SEED-Emulator.

## Development Setup

From this directory, create and activate a virtual environment:

```bash
python -m venv .venv
```

On Linux or macOS:

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install the service and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run the Service

```bash
python -m uvicorn seedemu_tool_service.main:app --reload
```

Benchmark topology deployment resources are documented with their owning domain in
`seedemu_tool_service/tools/benchmark/README.md`; other Tool Service domains do not
depend on them.

The SEED workspace itself is **not** a tool-service setting: this service makes no assumption about where
the SEED emulator lives. `benchmark.topology.discover_python` accepts any existing trusted Python
entrypoint selected by the user, performs a bounded Python-only trial compile, parses the generated Compose,
and returns a normalized service/network/probe descriptor. `benchmark.runtime.describe` produces the equivalent
read-only descriptor input for an already running project through the Docker SDK. Clients never invoke Docker CLI;
all runtime discovery remains behind this API.
The declared `seed_root` identifies the SEED library checkout; the topology script may be elsewhere on the host.
`benchmark.topology.lifecycle` can build, start, check, and stop exactly that bound Compose artifact.
Its path must remain inside the matching artifact ID and its project name is validated.

The service is then available at:

- API: <http://127.0.0.1:8000>
- OpenAPI documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/api/v1/health>
- Runtime backend: <http://127.0.0.1:8000/api/v1/runtime>
- Tool discovery: <http://127.0.0.1:8000/api/v1/tools>
- Tool invocation: `POST /api/v1/tools/{tool_name}/invoke`

## Invoke a Tool

Invoke a registered tool by posting its normal argument object to the tool-specific REST endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tools/network.inspect_ip_address/invoke \
  -H 'Content-Type: application/json' \
  -d '{"address":"2001:0db8::1"}'
```

The response is the tool's structured result directly:

```json
{
  "address": "2001:db8::1",
  "version": 6,
  "is_private": true,
  "is_loopback": false,
  "is_multicast": false,
  "is_global": false
}
```

The request object is validated against the input schema returned by tool discovery. Invalid
arguments return HTTP `422`; an unknown tool returns HTTP `404`.

This example does not require a running Docker daemon or SEED emulation. Docker-backed tools use
the same endpoint. For example, after starting a SEED emulation and checking its container names
with `docker ps`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tools/network.ping/invoke \
  -H 'Content-Type: application/json' \
  -d '{"source":"as150h-web-10.150.0.71","target":"10.151.0.71","count":2}'
```

An unreachable destination is a successful tool observation and returns HTTP `200` with
`reachable: false`. A missing source container returns HTTP `404`; a Docker backend failure
returns HTTP `502`.

## Run Tests

```bash
python -m pytest
```

## Run with Docker Compose

The container connects to the host Docker daemon through `/var/run/docker.sock`. This gives
the tool service control over host containers, images, networks, and volumes. Only run the
service from trusted code and do not expose its API to untrusted networks.

On Linux, set `DOCKER_GID` to the group owner of the Docker socket so the non-root application
user can access it:

```bash
export DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
docker compose up --build
```

With Docker Desktop, start the service directly:

```powershell
docker compose up --build
```

Use the runtime endpoint to verify daemon access:

```bash
curl http://127.0.0.1:8000/api/v1/runtime
```

A healthy response includes `"available": true` and the host Docker daemon version. Stop and
remove the service container with:

```bash
docker compose down
```

## Tool Domains

The service is a thin tool adapter, not a benchmark planner or policy engine. Topology APIs return pure facts;
`runtime.service_capabilities` returns fixed read-only operation evidence; generic `operation.*` tools perform one
typed project/service-scoped action. LLM calls, `available_faults`, fault meaning, candidate authorization,
session policy, qualification, recovery planning, and scoring live in Benchmark Agent and its Adapter.

Tools are grouped into packages under `seedemu_tool_service/tools/`. Each domain exposes one
registration function that binds its functions or methods to the shared `ToolRegistry`.

The network-domain skeleton is organized as follows:

```text
tools/network/
|-- models.py        # Explicit argument and result models
|-- tools.py         # Tool function or bound-method implementations
`-- registration.py  # Tool metadata and registry bindings
```

The initial network tools are:

- `network.inspect_ip_address`: normalize an IPv4 or IPv6 address and inspect its properties.
- `network.ping`: execute ICMP echo requests inside a selected emulated source container and
  report whether the target host is reachable.

Both demonstrate bound methods, explicit Pydantic argument validation, domain registration,
discovery, and registry invocation. Each registration associates a handler with an argument model.
The registry derives the tool's input JSON Schema from that model, while the result model defines
the stable output contract.

The ping command is passed to Docker as an argument vector rather than through a shell. New network
tools should follow the same pattern and be added to `register_network_tools()`.

### DNS Domain

The DNS-domain skeleton follows the same structure:

```text
tools/dns/
|-- models.py        # DNS argument and result models
|-- tools.py         # DNS tool implementations
`-- registration.py  # DNS registry bindings
```

The initial `dns.lookup` tool runs `dig` inside a selected emulated container. It uses the node's
configured resolver by default or an explicitly supplied DNS server. The source container must have
the `dig` executable installed.

### BGP Domain

The BGP-domain skeleton lives under `tools/bgp/` and includes explicit argument and result models,
bound-method implementations, and registry bindings. Its reference tool is `bgp.summary`, which
runs `vtysh -c "show bgp ipv4 unicast summary"` inside a selected emulated router. The router
container must provide `vtysh` and a compatible routing daemon.

### PKI Domain

The PKI toolset is organized by category under `seedemu_tool_service/tools/pki/`:

- Certificate-file inspection and remote TLS inspection.
- Certificate-chain, trust, and revocation verification.
- Certificate expiration and version comparison.
- Read-only private-key and CSR inspection. Certbot creates and manages key and CSR material for ACME requests.
- ACME readiness, issuance, Nginx deployment, renewal, and revocation through the SEEDEmu CA Service.
- Certificate backup, installation, and restoration outside Certbot-managed paths.
- Trust-store inspection and fingerprint-checked CA removal.
- SEEDEmu CA Service state and sanitized event inspection.

The SEEDEmu `CAService` remains the only CA. The tools do not create a separate CA, sign
certificates locally, or install arbitrary CA roots. ACME operations validate the selected
directory against the provisioners configured on the explicitly selected CA Service node.
CA root distribution remains controlled by the emulator's `installCACert` filters. See
[the complete PKI design](../docs/tool-service/pki-tools-design.md).

The PKI examples demonstrate end-to-end use of these tools with the emulator's CA Service:
[H14 HTTP-01](../examples/H14_pki_http01_web/README.md) uses Certbot's Nginx authenticator;
[H15 DNS-01](../examples/H15_pki_dns01_wildcard/README.md) requests a wildcard certificate using
a TSIG-restricted RFC 2136 update policy.
