# Tool access control

The REST and MCP tool endpoints require a unique high-entropy bearer token for
each agent. The service stores only the token's SHA-256 digest in a trusted policy
file. Missing, invalid, or unreadable policy data fails closed.

## Configure the service

1. Copy `tool-service/auth-policy.example.json` to a trusted host directory as
   `policy.json`.
2. Generate a token for each agent and store only its SHA-256 digest in
   `token_sha256`. Enable the identity after filling in its world, role, and node
   assignments. Give the raw token only to that agent's client.
3. Bind logical node IDs to full 64-character Docker container IDs. Refresh these
   bindings after rebuilding a container.
4. Set `SEEDEMU_AUTH_POLICY` to the policy file when running directly. For Compose,
   set `SEEDEMU_AUTH_POLICY_DIR` to the trusted directory containing `policy.json`.
   The directory is mounted read-only in the service container.

Create a token and its digest with:

```bash
python -c 'import secrets, hashlib; t=secrets.token_urlsafe(32); print(t); print(hashlib.sha256(t.encode()).hexdigest())'
```

Clients send `Authorization: Bearer <token>` on every REST request and every MCP
HTTP request. Use TLS outside a local isolated experiment. Never put raw tokens in
tool arguments, prompts, or version control.

## Roles and profiles

`auth/policies.py` explicitly lists role capabilities. New tools are denied until
they are added there. PKI file operations require an exact operation profile
assigned by the trusted operator. A profile binds the tool, world, and complete
validated arguments, including the authorized node and paths. The caller cannot
change a path, CA, remote target, or operation while using that profile.

`pki_operator` can use the reviewed PKI operations and profiles. `ca_operator` can
also inspect the configured CA Service. `observer` and `member` receive only the
diagnostic and read capabilities assigned to their role; node access is always
limited to the identity's node assignments. ACME requests and renewals use the
SEEDEmu CA Service configuration discovered from a specifically authorized CA
node. The CA Service itself enforces issuance policy and ACME challenges.

The `ca_service_nodes` policy field is the trusted allowlist for CA Service nodes.
Each entry must refer to a node in the same world. A CA Service source supplied to
a tool is resolved to its pinned container ID and rejected unless it is on this
allowlist.

## Domain ownership

The policy's `domains` entries record current ownership for DNS writes and nginx
deployment. The most specific matching name controls; inactive or expired child
entries do not fall back to a parent's ownership. Transfers and revocations take
effect on the next authorization check.

## Enforcement

The REST and MCP interfaces share the same registry and authorization checks. Tool
discovery filters by role and profile; invocation validates arguments and repeats
the checks before calling a handler. Source nodes are converted to pinned full
container IDs, and cross-world or unassigned nodes are rejected. Policy updates
are read for each request; malformed or missing policy never falls back to a
previous snapshot.

The policy is an operator-controlled authorization boundary, not a file-system
sandbox. Operators must protect CA, certificate, Certbot, and service configuration
paths from untrusted processes on the emulated nodes. Audit events omit tokens,
certificate material, raw arguments, and tool output.
