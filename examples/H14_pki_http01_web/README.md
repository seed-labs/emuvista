# H14: HTTPS WebService with the SEEDEmu CA Service (HTTP-01)

This example shows the built-in SEED Emulator `CAService` issuing a certificate
for a `WebService` through ACME HTTP-01. The web server uses the emulator's
Nginx integration, and the client trusts the root certificate installed by the
CA service. No public CA or manually created signing CA is used.

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
To use the standard lifecycle runner from the SEED Emulator checkout:

```sh
python3 "$SEEDEMU_ROOT/seedemu/testing/cli.py" all \
  examples/H14_pki_http01_web/example.yaml \
  --artifact-dir /tmp/h14-pki-http01
```

Certificate issuance happens during the WebService startup. SEEDEmu's HTTPS
integration invokes Certbot with the Nginx authenticator, which performs
HTTP-01 validation on port 80. The CA must be able to resolve and reach
`web.pki.test` over the emulation network.

## PKI tool walkthrough

After the scenario is running and the Tool Service policy authorizes its CA,
web, and client nodes, use the PKI tools to inspect the CA and verify the
service. Replace the `source` values with node IDs from the policy:

1. Call `pki.inspect_ca_service` on the CA node with
   `config_path=/root/.step/config/ca.json`.
2. Call `pki.inspect_remote_tls_chain` from the client for
   `target=web.pki.test`, `port=443`, and `server_name=web.pki.test`.
3. Call `pki.check_tls_hostname` from the client for
   `expected_hostname=web.pki.test`.
4. Call `pki.check_remote_certificate_expiration` from the client for the same
   endpoint.

The hostname check should pass for `web.pki.test`. A check using an unrelated
hostname should report a mismatch. The test runner separately confirms that the
emulated client can fetch the service over trusted HTTPS.

## Cleanup

```sh
docker compose -f examples/H14_pki_http01_web/output-h14/docker-compose.yml \
  down --remove-orphans --volumes
```

Generated CA material and compiled files are local to this example's `output-h14/`
directory. Keep that directory out of source control.
