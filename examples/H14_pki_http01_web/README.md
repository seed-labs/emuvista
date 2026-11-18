# H14: HTTPS WebService with the SEEDEmu CA Service (HTTP-01)

This example demonstrates the PKI tools requesting and deploying an HTTPS
certificate from the built-in SEED Emulator `CAService` through ACME HTTP-01.
The WebService starts as HTTP-only; the PKI tool performs the Certbot Nginx
challenge and installs the resulting TLS site. The client trusts the root
certificate installed by the CA service. No public or manually created CA is used.

## Topology and files

The scenario has one AS with a CA node, an authoritative DNS node, an HTTPS web
node, and a client. The CA and web names resolve only inside the emulation.

- `scenario.py`: creates and compiles the SEED Emulator scenario.
- `example.yaml`: TestRunner lifecycle, readiness, and reachability checks.
- `test_runtime.py`: verifies the trusted HTTPS endpoint from the emulated client.

## Requirements and generation

Set `SEEDEMU_ROOT` to a SEED Emulator checkout with its Python dependencies
installed. Docker Compose must be available.

```sh
export SEEDEMU_ROOT=/path/to/seed-emulator
python3 examples/H14_pki_http01_web/scenario.py
```

The generated Compose project is written to this example's `output-h14/` directory.
The scenario includes the SEEDEmu Internet Map; while it is running, open
`http://localhost:8080` to view the emulated topology. Start the environment
through `up` and leave it running while invoking the PKI tools:

```sh
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" clean examples/H14_pki_http01_web/example.yaml
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" compile examples/H14_pki_http01_web/example.yaml
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" build examples/H14_pki_http01_web/example.yaml
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" up examples/H14_pki_http01_web/example.yaml
```

Before certificate issuance, `http://web.pki.test/` works and
`https://web.pki.test/` does not. This makes the change caused by the PKI tools
visible. The CA must be able to resolve and reach `web.pki.test` over the
emulation network.

## PKI tool walkthrough

The PKI tools now live in
[`services/AgentService/tools/pki`](../../services/AgentService/tools/pki/).
There is no standalone tool server. The multi-node calls below describe the
library workflow and require a caller-supplied execution backend. AgentService's
local backend cannot administer the CA and web containers from another node.
This scenario does not install an AgentService or automatically issue certificates.

After the scenario is running, invoke the PKI tools directly. Set `source` to
the running web container's Docker name or ID and `ca_service_source` to the CA
container's Docker name or ID. The `docker compose ps` command in the generated
example output lists these containers. Then call:

1. `pki.inspect_acme_readiness` on the web node with
   `source=<web container name or ID>`,
   `ca_service_source=<CA container name or ID>`,
   `directory_url=https://ca.pki.test/acme/acme/directory`,
   `domains=["web.pki.test"]`, and `authenticator=nginx`.
2. `pki.request_acme_certificate` on the web node with
   `source=<web container name or ID>`,
   `ca_service_source=<CA container name or ID>`, the same directory URL and domain,
   `email=admin@pki.test`, `authenticator=nginx`, and
   `cert_name=web-pki-test`.
3. `pki.deploy_acme_certificate_to_nginx` on the web node with
   `source=<web container name or ID>`,
   `cert_name=web-pki-test` and `server_name=web.pki.test`.
4. Run the TestRunner `test` stage. It verifies the HTTPS connection from the
   emulated client, hostname validation, and the Nginx-authenticator renewal
   configuration created by the certificate request tool.

```sh
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" test \
  examples/H14_pki_http01_web/example.yaml
```

The library calls above perform the actual issuance and deployment; the
TestRunner `test` stage verifies their result. Do not use the `all` command for
this walkthrough because it runs `test` before you can make the tool calls and
then shuts the environment down.

## Cleanup

```sh
docker compose -f examples/H14_pki_http01_web/output-h14/docker-compose.yml \
  down --remove-orphans --volumes
```

Generated CA material and compiled files are local to this example's `output-h14/`
directory. Keep that directory out of source control.
