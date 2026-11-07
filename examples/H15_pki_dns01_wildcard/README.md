# H15: Wildcard HTTPS Certificate with RFC 2136 DNS-01

This example demonstrates a wildcard certificate issued by the built-in
SEED Emulator `CAService` using the PKI toolset's Certbot RFC 2136 authenticator.
The DNS server accepts updates only for the `_acme-challenge.svc.pki.test` TXT
record and only from a dedicated TSIG key. The certificate is then deployed to
an Nginx site with the PKI deployment tool.

Unlike H14, this scenario does not call `WebServer.enableHTTPS()`: that built-in
integration uses Certbot's Nginx authenticator and HTTP-01. Here, the PKI tools
request the certificate with `dns-rfc2136` and deploy it separately.

## Topology and files

The topology contains a CA node, an authoritative DNS server, a Certbot/Nginx
web node, and a client in one AS. The requested certificate covers
`*.svc.pki.test`; the client connects to `api.svc.pki.test`.

- `scenario.py`: creates the CA, BIND zone, restricted TSIG update policy, and
  client and web nodes.
- `example.yaml`: TestRunner compile, readiness, and HTTP reachability checks.
- `test_runtime.py`: verifies the deployed wildcard certificate and checks
  that the temporary challenge TXT record has been removed.

## Requirements and generation

Set `SEEDEMU_ROOT` to a SEED Emulator checkout with its Python dependencies
installed. Docker Compose must be available.

```sh
export SEEDEMU_ROOT=/path/to/seed-emulator
python3 examples/H15_pki_dns01_wildcard/scenario.py
```

The scenario includes the SEEDEmu Internet Map; while it is running, open
`http://localhost:8081` to view the emulated topology. H15 uses port 8081 so it
can run alongside H14, which uses port 8080.

Run the lifecycle through `up` first so the generated CA, DNS, web, and client
containers are running:

```sh
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" clean \
  examples/H15_pki_dns01_wildcard/example.yaml
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" compile \
  examples/H15_pki_dns01_wildcard/example.yaml
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" build \
  examples/H15_pki_dns01_wildcard/example.yaml
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" up \
  examples/H15_pki_dns01_wildcard/example.yaml
```

## PKI tool walkthrough

The PKI tools now live in
[`services/AgentService/tools/pki`](../../services/AgentService/tools/pki/).
There is no standalone tool server. The multi-node calls below describe the
library workflow and require a caller-supplied execution backend. AgentService's
local backend cannot administer the CA and web containers from another node.
This scenario does not install an AgentService or automatically issue certificates.

Invoke the PKI tools directly. Set `source` to the running web container's Docker
name or ID and `ca_service_source` to the CA container's Docker name or ID; the
generated `docker compose ps` output lists the container names. Use the credentials
file already installed at `/etc/letsencrypt/credentials/rfc2136.ini`; the example
generates its TSIG secret for the local simulation and does not print it.

1. Call `pki.inspect_acme_readiness` on the web node with
   `authenticator=dns-rfc2136`, `domains=["*.svc.pki.test"]`, the CA directory
   `https://ca.pki.test/acme/acme/directory`, and
   `dns_credentials_path=/etc/letsencrypt/credentials/rfc2136.ini`.
2. Call `pki.request_acme_certificate` with the same CA, directory, domain,
   authenticator, and credentials path; use `email=admin@pki.test` and
   `cert_name=wildcard-svc`.
3. Call `pki.deploy_acme_certificate_to_nginx` on the web node with
   `cert_name=wildcard-svc` and `server_name=api.svc.pki.test`.
4. Run the TestRunner `test` stage. It checks trusted TLS for
   `api.svc.pki.test` and verifies that the challenge TXT record was cleaned up.

```sh
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" test \
  examples/H15_pki_dns01_wildcard/example.yaml
```

The scenario installs `python3` on the CA node because the PKI CA inspection
tool uses it to read the SEEDEmu CA configuration. The `dns-rfc2136`
authenticator requires owner-only credentials and is required
for wildcard identifiers. The BIND update policy grants the TSIG identity only
the TXT update permission for `_acme-challenge.svc.pki.test`; it does not grant
general zone updates or permission to change A, AAAA, NS, or SOA records.

## Cleanup

```sh
docker compose -f examples/H15_pki_dns01_wildcard/output-h15/docker-compose.yml \
  down --remove-orphans --volumes
```

Generated CA material, TSIG credentials, and compiled files stay in the local
`output-h15/` directory. Keep that directory out of source control.
