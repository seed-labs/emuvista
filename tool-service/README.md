# SEEDemu Agent Tool Service

FastAPI service exposing agent-facing operations for SEED-Emulator through a REST API.

## Run the service

```bash
cd tool-service
python -m pip install -e '.[dev]'
python -m uvicorn seedemu_tool_service.main:app --reload
```

The service exposes tool discovery at `GET /api/v1/tools` and tool invocation at
`POST /api/v1/tools/{tool_name}/invoke`. Send the tool's regular argument object as JSON.

The service does not authenticate callers or apply per-agent authorization. Restrict access at
the deployment boundary. The Docker backend requires access to the Docker Engine socket to run
commands inside emulated nodes.

## Docker Compose

```bash
cd tool-service
docker compose up --build
```

## PKI behavior

PKI ACME issuance, renewal, and revocation use Certbot on the selected emulated node and the
SEEDEmu CA Service's configured ACME directory. The tool service does not create a CA or sign
certificates itself. CA private keys remain in the SEEDEmu CA Service. See
[the PKI tools design](../docs/tool-service/pki-tools-design.md) for the tool inventory and
limitations.
