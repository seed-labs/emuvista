# Docker-backed DNS tests

These tests exercise the real `DockerRuntimeBackend` against a running B02a
SEED-Emulator deployment. They are **not** part of the default `python -m pytest`
run under `tool-service/` because they require Docker and the emulated topology.

## Prerequisites

1. A SEED-Emulator checkout is available (this repository keeps the B02a example
   under `examples/internet/B02a_domain_registration`).
2. Docker is running and accessible to the current user/group.
3. `seedemu-agent-tools/tool-service/.venv` is installed with the project's dev
   dependencies:
   ```bash
   cd seedemu-agent-tools/tool-service
   python -m pip install -e ".[dev]"
   ```

## Start B02a from current source

The checked-in `examples/.../output` may be stale (for example HTTP-only Loom).
Regenerate B02a from the current source-auth topology before running the
Registrar/Loom tests:

```bash
cd /path/to/seed-emulator

# If the venv is at repo root
.venv/bin/python examples/internet/B02a_domain_registration/domain_registration.py

# Build and start the generated Compose project
docker compose -f examples/internet/B02a_domain_registration/output/docker-compose.yml build
docker compose -f examples/internet/B02a_domain_registration/output/docker-compose.yml up -d
```

Wait until Loom is serving and the source identity is provisioned. A quick check
from outside the emulated network is not needed; the tests themselves validate
the expected container names and labels.

The end-to-end purchase test owns `example.com`. Start a fresh deployment and
do not run B02a's own `test_runtime.py` first, because that test also registers
`example.com`. Regeneration creates deployment-local TLS and SSH keys, so always
rebuild the complete Compose project; rebuilding only Loom leaves the source
container with a stale CA certificate.

## Run the tests

Run the DNS Docker-backed test suite from `seedemu-agent-tools/tool-service`:

```bash
cd /path/to/seedemu-agent-tools/tool-service
.venv/bin/python -m pytest seedemu_tool_service/tools/dns/tests/dockerbackend -v
```

To focus on the B02a Registrar/Loom source-auth login path:

```bash
.venv/bin/python -m pytest \
  seedemu_tool_service/tools/dns/tests/dockerbackend/test_domain_registrar_request.py \
  -v
```

To run the complete Agent workflow (Registrar discovery, source-owned
authoritative DNS discovery and configuration, native Loom balance purchase,
EPP/Registry delegation, and final recursive lookup):

```bash
.venv/bin/python -m pytest \
  seedemu_tool_service/tools/dns/tests/dockerbackend/test_domain_purchase_workflow.py \
  -vv
```

To print full structured DNS/Registrar results while debugging:

```bash
.venv/bin/python -m pytest \
  seedemu_tool_service/tools/dns/tests/dockerbackend/test_domain_registrar_request.py \
  --show-dns-results -v
```

## Clean up

```bash
docker compose -f /path/to/seed-emulator/examples/internet/B02a_domain_registration/output/docker-compose.yml down
```
