# PKI Tool Design

## Overview

The PKI tool domain provides certificate and TLS diagnostics for agents operating
SEED-Emulator environments through the Tool Service.

The current task catalog emphasizes service diagnosis, deployment, and security
response. PKI tools support those tasks when the network path and service port are
available, but HTTPS/TLS still fails because of certificate, trust-chain, or
expiration issues.

Example agent tasks that require PKI support include:

- determine why a client can reach `web1:443` but HTTPS requests fail;
- verify that a web service is presenting the expected certificate after deployment;
- detect whether DNS manipulation redirects a client to a service with an unexpected
  certificate;
- check whether an outage is caused by an expired certificate;
- verify whether a client trusts the CA that signed a service certificate.

## Design Goals

- Provide structured, agent-friendly PKI observations instead of unstructured shell
  output only.
- Constrain state-changing operations with explicit paths, order state, and verification evidence.
- Preserve useful command output for human debugging while withholding sensitive
  configuration and credential material.
- Use explicit Pydantic argument and result models for every tool.
- Execute commands through the runtime backend using argument vectors, not shell
  strings.
- Separate diagnostic tools from state-changing repair and deployment tools.

## Current State

The current PKI domain implements the tool set described below. It includes
read-only diagnostics, ACME certificate requests through the existing CA,
certificate installation helpers, and trust-store inspection/removal tools. SEEDEmu
`CAService` remains the authority: it provisions the CA and distributes its root
according to the emulator's `installCACert` filters. The tool set does not create or
install CA roots independently.

These tools use OpenSSL and standard system utilities inside a selected emulated node
container. Diagnostic tools return structured results and only the command output
needed to explain the result. Sensitive configuration and credential output is
withheld. State-changing tools require explicit paths and report created, modified,
removed, or backup paths when applicable.

The implementation is organized by PKI tool category:

```text
tools/pki/
|-- shared/                  # Shared PKI models and OpenSSL parsing helpers
|-- certificate_inspection/  # Local certificate-file inspection tools
|-- remote_tls/              # Remote TLS service inspection tools
|-- trust_verification/      # Certificate-chain and trust verification tools
|-- expiration/              # Certificate expiration checks
|-- private_key_csr/         # Private-key and CSR tools
|-- acme/                    # SeedEmu CAService ACME lifecycle tools
|-- installation/            # Certificate material installation helpers
|-- trust_store/             # Trust-store and CA management tools
|-- models.py                # Compatibility exports for PKI models
|-- tools.py                 # Compatibility aggregate for PKI tool classes
`-- registration.py          # PKI registration entry point
```

## Tool Categories

### 1. Certificate Inspection

Certificate inspection tools examine certificate files that already exist inside an
emulated node.

These tools answer questions such as:

- Who was this certificate issued to?
- Who signed this certificate?
- When does the certificate become valid and expire?
- Which DNS names or IP addresses does the certificate cover?
- What public-key and signature algorithms does it use?
- What is the certificate fingerprint?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.inspect_certificate_file` | Implemented | Inspect a certificate file and return common X.509 fields. |
| `pki.inspect_certificate_names` | Implemented | Return subject CN and SAN entries in a focused result. |
| `pki.inspect_certificate_extensions` | Implemented | Return key usage, extended key usage, basic constraints, and related extensions. |
| `pki.inspect_certificate_public_key` | Implemented | Return public-key algorithm and key size. |
| `pki.get_certificate_fingerprint` | Implemented | Return a certificate fingerprint for comparison tasks. |

### 2. Remote TLS Service Inspection

Remote TLS inspection tools connect from one emulated node to a TLS service and inspect
what the service actually presents to the client.

This is different from reading a local certificate file. A service may present a
different certificate because of SNI, reverse-proxy configuration, stale service state,
or DNS redirection.

These tools answer questions such as:

- What certificate does `web1:443` actually present?
- Does SNI change the presented certificate?
- Is the server sending a full certificate chain?
- Which TLS version and cipher were negotiated?
- Is the certificate seen by the client the same as the certificate file on the server?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.inspect_remote_tls_certificate` | Implemented | Connect to a TLS service and inspect the presented certificate. |
| `pki.inspect_remote_tls_chain` | Implemented | Return every certificate presented by the remote service. |
| `pki.inspect_tls_handshake` | Implemented | Return negotiated TLS version, cipher, peer certificate summary, and verification status. |
| `pki.check_tls_hostname` | Implemented | Check whether the presented certificate matches an expected hostname. |
| `pki.check_tls_protocols` | Implemented | Check which TLS protocol versions are accepted by a service. |
| `pki.check_tls_cipher` | Implemented | Check whether a service accepts or negotiates expected ciphers. |

Remote network probes, including certificate-expiration checks, require an explicit
task profile that pins the source node and target arguments. They are not general
purpose network-scanning permissions for observer/member roles.

### 3. Certificate Chain And Trust Verification

Trust verification tools determine whether a certificate chains to trusted CA material
from the perspective of an emulated node.

These tools answer questions such as:

- Does this certificate chain to the expected CA?
- Is the failure caused by a missing intermediate certificate?
- Is the certificate self-signed or signed by an unknown authority?
- Does a client trust the CA used by a service?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.verify_certificate_chain` | Implemented | Verify a certificate against CA files, CA directories, and optional intermediate chains. |
| `pki.verify_remote_tls_chain` | Implemented | Connect to a remote TLS service and verify the presented chain. |
| `pki.verify_certificate_against_ca` | Implemented | Focused wrapper for checking a certificate against one CA file. |
| `pki.verify_certificate_with_intermediates` | Implemented | Focused wrapper for checking a leaf certificate with supplied intermediate certificates. |
| `pki.explain_verification_failure` | Implemented | Normalize common OpenSSL verification errors into structured reasons. |

### 4. Expiration And Rotation Diagnosis

Expiration tools detect certificates that are already expired or close to expiry.

These tools answer questions such as:

- Is this certificate currently expired?
- Will it expire within a specified warning window?
- Is the remote service still presenting an old certificate after a file was replaced?
- Which certificates in a directory are near expiration?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.check_certificate_expiration` | Implemented | Check whether a certificate file is expired or expires within a warning window. |
| `pki.check_remote_certificate_expiration` | Implemented | Check expiration for the certificate presented by a remote TLS service. |
| `pki.list_expiring_certificates` | Implemented | Scan a constrained directory for certificates expiring within a window. |
| `pki.compare_certificate_versions` | Implemented | Compare fingerprints and validity periods between certificate files or remote services. |

### 5. Private Key And CSR Tools

Private-key and CSR tools are read-only diagnostics for material already present on a
node. The toolset does not expose standalone key or CSR generation: SEEDEmu
`CAService` issues certificates through ACME, and Certbot creates and manages the
corresponding private key and request.

These tools answer questions such as:

- Does a private key match a certificate?
- What subject and SANs are requested by a CSR?
- Does a CAService-managed private key match its installed certificate?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.inspect_private_key` | Implemented | Return key type and size without exposing private-key material. |
| `pki.verify_private_key_matches_certificate` | Implemented | Check whether a private key corresponds to a certificate. |
| `pki.inspect_csr` | Implemented | Inspect subject, SANs, public key, and extensions requested by a CSR. |

### 6. ACME Certificate Lifecycle

ACME tools operate a real Certbot client inside the selected emulated service node.
`pki.inspect_ca_service` reads a specifically authorized SEEDemu CA node and reports
the ACME directory URL for each configured ACME provisioner. The agent passes that
URL to the request tool. This discovery is scoped to the assigned CA node; the Tool
Service does not scan the Docker host for CA processes or alter CA configuration.
The client communicates with the HTTPS directory exposed by SEEDemu `CAService`,
and the CA validates the ACME challenge. CA private keys remain inside step-ca and
are never supplied to the requesting node, Tool Service, or agent.

The Certbot integration supports HTTP-01 through the nginx or webroot authenticator,
and DNS-01 through the named `dns-rfc2136` plugin. DNS-01 requires that plugin to be
installed on the requesting node and a credentials file under
`/etc/letsencrypt/credentials/` with mode `0400` or `0600`. The tool never reads or
returns the credentials. Wildcard names are accepted only with DNS-01. The target
authoritative DNS server must permit authenticated RFC 2136 updates; readiness checks
resolve a wildcard's base domain but cannot prove the CA's challenge will succeed.
Static zones and custom DNS/BGP challenge experiments need a separately configured
challenge provider.

`CAService` installs the Smallstep `step` CLI broadly, but this tool's issuance,
renewal, and revocation operations require Certbot. SEEDEmu installs Certbot and its
nginx plugin when a `WebService` is explicitly configured for CA-backed HTTPS; a
generic Agent node is not assumed to have Certbot. `pki.inspect_environment` and
`pki.inspect_acme_readiness` report the available client and authenticator capabilities.
ACME request, readiness, renewal, and revocation operations verify the selected
directory against the configured SEEDEmu CA Service provisioners. DNS credentials
must be regular files with mode `0400` or `0600`.

An agent may request or renew through SEEDEmu CA Service only when an exact PKI
operation profile authorizes the client node, CA node, configuration path, directory,
and operation arguments. The Tool Service verifies the directory against the selected
service's configured provisioners; the CA's issuance policy and challenge validation
decide whether to issue the certificate. CA private keys remain inside the CAService.
The trusted access policy must list CA Service node IDs in `ca_service_nodes`; calls
resolve those IDs only within the caller's world, without granting shell access to
the CA node.

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.request_acme_certificate` | Implemented | Request a certificate from the discovered SEEDEmu CAService ACME directory using HTTP-01 or RFC 2136 DNS-01. |
| `pki.deploy_acme_certificate_to_nginx` | Implemented | Add an isolated TLS site without replacing nginx's default site; conservatively refuses a matching name when TLS is configured in nginx. |
| `pki.renew_acme_certificate` | Implemented | Renew a Certbot-managed certificate using its saved ACME configuration. |
| `pki.revoke_acme_certificate` | Implemented | Revoke a certificate through its issuing ACME endpoint. |

Certificate issuance uses the existing CA through ACME. The tool service does not
create a second local CA, generate self-signed service certificates, or sign CSRs with
a CA private key on an emulated node.

### 7. Certificate Installation And Deployment

Installation tools place certificate material at application-specific paths. They are
state-changing and may affect service availability. They reject destinations inside
`/etc/letsencrypt` (including paths that resolve there through symlinks), so they cannot
replace Certbot's CAService-managed lineages. Use ACME request/renewal tools for those
lineages and verify the deployed certificate against the CAService root.

For a SEEDEmu `WebService` already configured with `setCAServer(...).enableHTTPS()`,
use its CAService-managed Certbot deployment and verify it with
`pki.verify_tls_deployment`. The explicit nginx deployment tool writes a separate site
file under `sites-available`/`sites-enabled`; it never replaces
`/etc/nginx/sites-available/default` and conservatively refuses a matching configured
name when TLS is configured in nginx.

These tools answer questions such as:

- Can the agent deploy a new certificate without overwriting unrelated files?
- Can the agent roll back certificate material after a failed repair?
- Did the service reload and begin presenting the new certificate?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.backup_certificate_material` | Implemented | Back up application-specific certificate/key/chain files outside Certbot's managed directory into a mode-0700 directory; backups are mode 0600 and rolled back if a copy fails. |
| `pki.install_certificate` | Implemented | Install a certificate file to an application path outside Certbot's managed directory. |
| `pki.install_private_key` | Implemented | Install an application private key with restrictive permissions outside Certbot's managed directory. |
| `pki.install_certificate_chain` | Implemented | Install a certificate chain bundle outside Certbot's managed directory. |
| `pki.restore_certificate_material` | Implemented | Restore backed-up material outside Certbot's managed directory. |

These tools should usually be paired with service tools:

```text
service.reload_service
service.restart_service
service.http_request
pki.inspect_remote_tls_certificate
```

### 8. Trust Store And CA Management

Trust-store tools inspect or remove CA material. SEEDEmu CA root distribution remains
under `CAService` and its `installCACert` filters; there is no tool to add a CA root or
bypass those filters.

These tools answer questions such as:

- Does a client trust the lab CA?
- Was an attacker CA installed in a client trust store?
- Is a CA certificate already trusted, and can an unexpected CA be removed?

Current tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `pki.inspect_trust_store` | Implemented | List trusted CA material in a constrained trust-store location. |
| `pki.check_ca_installed` | Implemented | Check whether a specific CA certificate is trusted. |
| `pki.remove_ca_certificate` | Implemented | Remove an installed CA only when its expected SHA-256 fingerprint matches, then update system trust. |
| `pki.update_trust_store` | Implemented | Run the fixed `update-ca-certificates` command. |

Trust-store removal and update are explicitly authorized operations. CA root
installation is exclusively handled by SEEDEmu `CAService` and its configured node
filters.

## Tool Response Envelope

The Tool Service can use a common response envelope across tool domains while allowing
each tool to define its own structured `data` payload. The envelope keeps agent-facing
responses predictable without forcing DNS, BGP, network, and PKI tools to return the
same domain-specific fields.

Example successful read-only response:

```json
{
  "tool": "pki.inspect_remote_tls_certificate",
  "source": "client1",
  "successful": true,
  "data": {
    "target": "web1",
    "port": 443,
    "server_name": "bank32.com",
    "certificate": {
      "subject": "CN=bank32.com",
      "issuer": "CN=SEED Lab CA",
      "serial": "01",
      "not_before": "Aug 01 00:00:00 2026 GMT",
      "not_after": "Aug 01 00:00:00 2027 GMT",
      "subject_alt_names": ["DNS:bank32.com"],
      "fingerprint_sha256": "AA:BB:CC"
    }
  },
  "raw_output": "openssl output, if useful for debugging",
  "error": null,
  "policy": {
    "task_id": "tls-diagnosis-001",
    "decision": "allowed",
    "matched_rule": "read-only-pki-diagnostics"
  }
}
```

Example denied response:

```json
{
  "tool": "pki.remove_ca_certificate",
  "source": "client1",
  "successful": false,
  "data": null,
  "raw_output": null,
  "error": {
    "category": "policy_denied",
    "message": "This task does not allow trust-store modification."
  },
  "policy": {
    "task_id": "tls-diagnosis-001",
    "decision": "denied",
    "matched_rule": "diagnosis-tools-only"
  }
}
```

For state-changing tools, the domain-specific `data` payload can include side-effect
fields only when they are relevant:

```json
{
  "tool": "pki.request_acme_certificate",
  "source": "web1",
  "ca_service_source": "ca1",
  "ca_service_config_path": "/root/.step/config/ca.json",
  "directory_url": "https://ca.example.test/acme/acme/directory",
  "successful": true,
  "data": {
    "action": "request",
    "cert_name": "web1.example.test",
    "created_paths": ["/etc/letsencrypt/live/web1.example.test/fullchain.pem"]
  },
  "raw_output": null,
  "error": null,
  "policy": {
    "task_id": "tls-repair-001",
    "decision": "allowed",
    "matched_rule": "ca-service-acme"
  }
}
```

Initial task-level policy support can be expressed through the envelope and enforced
before a tool handler runs:

- `tool`: the fully qualified tool name used for allow/deny checks;
- `source`: the emulated node or container used for source restrictions;
- `policy.task_id`: the task whose policy was applied;
- `policy.decision`: whether the call was allowed or denied;
- `policy.matched_rule`: the policy rule that explained the decision;
- `error.category`: a stable error category such as `policy_denied`,
  `file_not_found`, `certificate_expired`, or `unknown_error`;
- `data.created_paths`, `data.modified_paths`, `data.backup_paths`: optional fields
  returned only by tools that create or modify artifacts.

The benchmark or Tool Service can keep a more complete audit log internally. The
agent-facing response should stay compact and include only the policy and side-effect
fields that are useful for the current call.

## SEEDemu Runtime Observation And Verification

Nine additional tools observe CAService/WebService state that SEEDemu has
already installed. No identity tool is added. Only `ca_service/` is a new tool
category; the other tools extend existing categories.

| Tool | Directory | Purpose |
| --- | --- | --- |
| `pki.inspect_environment` | `acme/` | Discover node executables and whether its CA bundle loads. |
| `pki.list_managed_certificates` | `acme/` | Read Certbot renewal files and inspect public certificate metadata. |
| `pki.inspect_acme_readiness` | `acme/` | Verify HTTPS directory access with the node's CA bundle; inspect DNS/webroot/nginx prerequisites and report challenge reachability as unverified. |
| `pki.inspect_renewal_status` | `acme/` | Inspect one lineage, cron/timer observations and bounded renewal log signals. |
| `pki.inspect_ca_service` | `ca_service/` | Inspect step-ca state and return ACME directory URLs from the explicitly selected CA node. |
| `pki.inspect_ca_events` | `ca_service/` | Return bounded JSON log event metadata without raw messages or challenge URLs. |
| `pki.verify_tls_deployment` | `remote_tls/` | Verify trust, hostname, validity and expected SHA-256 leaf fingerprint in one connection. |
| `pki.test_mtls_connection` | `remote_tls/` | Compare HTTPS HEAD requests with and without a local client identity. |
| `pki.check_certificate_status` | `trust_verification/` | Verify leaf revocation against an explicitly supplied CRL. |

### Execution And Authorization

Python probes run **inside the assigned node**, requiring `python3` and GNU
`timeout`. They have a 45-second overall execution bound; individual subprocesses
and network operations also use timeouts. OpenSSL is required for certificate/CRL
inspection. Probes do not install dependencies. A missing interpreter, timeout,
malformed result or execution failure produces an unsuccessful observation.

State-changing PKI tools and remote network probes require an exact operation profile.
CA inspection and event inspection additionally require `ca_operator`. Other
inspection tools use the existing profile-read permissions, including mTLS because a
client private-key path must be explicitly authorized. No tool executes commands in
a remote target: remote TLS connections originate from the authorized source node.

Most new tools return `source`, `successful`, `data`, `exit_code` and `error`.
`successful` means the observation ran successfully;
it does **not** mean the service passed its checks. Check the specific `data`
fields described below. Probe errors use sanitized categories and never
return raw CA configuration, private keys, hook commands or unrestricted log text.

### Important Result Semantics

- `inspect_environment`: `executables` and `ca_bundle_loadable` describe local
  prerequisites. `seedemu_step_cli_available` does not mean Certbot is installed;
  `certbot_authenticators` lists detected Certbot plugins. Loading a bundle does not
  prove trust in a particular CA endpoint.
- `list_managed_certificates`: `certificates` contains Certbot lineage names,
  public certificate details, paths and selected renewal settings. Broken renewal
  files produce individual errors. `truncated` indicates the configured limit.
- `inspect_acme_readiness`: `directory_valid` requires a trusted HTTPS response
  with the ACME directory fields. DNS resolution is from the requesting node.
  `authenticator_available` describes local client prerequisites, not CA-side
  challenge success. DNS credentials are checked for owner-only permissions, never
  read or returned. `ready_for_issuance` remains unknown because only the CA can
  confirm a real challenge. This check makes no issuance request and writes no files.
- `inspect_renewal_status`: scheduler observations do not prove that a job has
  actually renewed a certificate. Bounded log signals are process-wide, not
  attributed to the requested lineage; `last_renewal_outcome` remains unknown.
  Raw logs and configured hook contents are not returned.
- `inspect_ca_service`: configured policy is separate from effective running
  policy. `/health` is checked using a configured DNS name, port and root, when
  available. ACME directory URLs are derived from configured DNS names and ACME
  provisioner names. An existing process alone is not reported as a healthy CA.
- `inspect_ca_events`: classification reflects the logged endpoint, not proof
  of successful issuance or revocation. Non-JSON lines are counted but not exposed;
  the result is not a complete CA issuance ledger.
- `verify_tls_deployment`: `deployment_verified` requires valid trust/hostname
  verification and the caller-supplied certificate fingerprint. It uses the node's
  clock and does not perform revocation checking.
- `test_mtls_connection`: connects twice and sends `HEAD /`. It distinguishes
  successful requests from evidence that a client certificate is mandatory. A
  specific certificate-required TLS alert can establish enforcement; generic
  disconnects or HTTP denials remain inconclusive. Application identity/role
  mapping is outside this check. This tool is for HTTPS, not arbitrary TLS protocols.
- `check_certificate_status`: returns `not_revoked`, `revoked`, or `unknown`.
  OpenSSL validates the provided CRL as part of chain verification. Missing,
  expired, invalid CRLs and other verification failures remain unknown. A
  `not_revoked` result means the leaf is not revoked according to that valid CRL,
  not that all possible status sources agree. No OCSP or CA database query is
  implied. SEEDemu/step-ca is not assumed to publish a CRL automatically; this tool
  is not a query of the CA's current revocation database.

### Validation

`tests/test_pki_runtime_workflows.py` exercises actual probe subprocesses, temporary
CA configs/logs, real OpenSSL certificates and CRLs, and loopback TLS/mTLS servers.
It also tests profile/node/role denials. These tests do not constitute a live
SEEDemu step-ca/Certbot integration test; that requires a running emulation with
CA, DNS, Web and Client nodes and separately provisioned access profiles.
