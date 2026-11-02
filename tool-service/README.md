# SEEDemu Agent Tool Service

FastAPI and MCP interfaces for agent-facing SEED-Emulator tools, including PKI
inspection and certificate lifecycle operations backed by the SEEDEmu CA Service.

## Configure access

REST and MCP tool calls require an agent-specific bearer token. Prepare a trusted
policy file from `auth-policy.example.json` and configure
`SEEDEMU_AUTH_POLICY=/absolute/path/policy.json`. See the
[access-control guide](../docs/tool-service/access-control.md) for token generation,
node assignments, roles, CA Service allowlisting, and PKI operation profiles.

Run the service directly with:

```bash
cd tool-service
export SEEDEMU_AUTH_POLICY=/absolute/trusted-directory/policy.json
python -m uvicorn seedemu_tool_service.main:app --reload
```

For Compose, set `SEEDEMU_AUTH_POLICY_DIR` to the host directory containing
`policy.json`, then run:

```bash
cd tool-service
export DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
export SEEDEMU_AUTH_POLICY_DIR=/absolute/trusted-directory
docker compose up --build
```

The policy directory is mounted read-only. Keep it outside agent-controlled nodes.
The tool service also needs access to the Docker Engine socket to run commands
inside assigned emulated nodes; expose the HTTP service only to trusted networks.

## Interfaces

- Health: `GET /api/v1/health`
- Runtime status: `GET /api/v1/runtime`
- REST tool discovery: `GET /api/v1/tools`
- REST invocation: `POST /api/v1/tools/{tool_name}/invoke`
- MCP Streamable HTTP: `/mcp`

Send the bearer token on each REST request and each MCP HTTP request. Tool discovery
and invocation use the same role, node, and PKI profile checks.

## PKI behavior

ACME issuance, renewal, and revocation are tied to an explicitly authorized SEEDEmu
CA Service node and its configured ACME directory. The service does not create a CA
or sign certificates itself. Certbot runs on the selected client node; private CA
keys remain in the SEEDEmu CA Service. Read [the PKI design](../docs/tool-service/pki-tools-design.md)
for the complete tool inventory and limitations.

## Development

```bash
cd tool-service
python -m pip install -e '.[dev]'
python -m pytest
```
