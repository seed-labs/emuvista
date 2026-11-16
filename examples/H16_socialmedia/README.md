# H16: Social Media (Mastodon) with DNS and CA-issued HTTPS

This example was renamed from `H14_socialmedia`. Existing generated `output/` files may
contain absolute paths to the old directory; regenerate before the next deployment.
Legacy `h14-*` service, CA and volume identifiers are retained for data continuity.

Build a standalone AS151 network with one router and seven hosts: primary and
secondary authoritative DNS, recursive DNS, CA, Mastodon, and Alice and Bob clients.
Root, `com`, and `mastodon.com` zones are served by primary DNS at `10.151.0.2`
and secondary DNS at `10.151.0.3`.

The CA follows SeedEmu's `B25_pki/pki_with_dns.py`: `RootCAStore` initializes
Smallstep CA material, `CAService` runs the CA, and `installCACert(Filter(asn=151))`
installs its root into AS151 nodes' system trust stores. Mastodon obtains a
certificate for `mastodon.com` through ACME HTTP-01 and serves HTTPS on port 18443.
Certbot checks renewal hourly and reloads Nginx after successful renewal.

## Generate, build, start

Run from this directory with the same Python environment as H12/H13:

```bash
python socialmedia.py
cd output
docker compose build
docker compose up -d
```

Generation requires Docker to initialize the CA using `smallstep/step-cli:0.26.1`.
The CA is saved in git-ignored `runtime/h14-ca/` and reused on subsequent generation;
keep this directory private because it contains CA keys. Generation does not start
the topology. The Mastodon leaf certificate is obtained at container startup.

The initial Mastodon build downloads and compiles pinned Mastodon 4.7.3, Ruby
4.0.6 and Node.js 24.19.0, and installs locked Ruby/JavaScript dependencies.
It requires Internet access and can take substantial time and several GB of RAM/disk.
Runtime application initialization happens inside the Mastodon host. The topology
uses the local CA for certificate issuance; no public CA is contacted at runtime.

`--output PATH` and `--platform amd|arm` control generation. Both architectures are generated through
the SeedEmu compiler; runtime support must be verified on the target architecture.

## Addresses and access

| Component | Address |
| --- | --- |
| Mastodon | `https://mastodon.com:18443`, `10.151.0.9` |
| CA | `https://ca.mastodon.com`, `10.151.0.4` |
| Recursive DNS | `10.151.0.53` |
| Alice client | `10.151.0.10` |
| Bob client | `10.151.0.11` |
| Mastodon Compose service | `h14-mastodon` |

Alice and Bob are client hosts, separate from Mastodon user accounts. Both use
the recursive resolver and can access `https://mastodon.com:18443` inside the
simulation network.

AS151 nodes automatically trust the CA. Once the instance has initialized, verify
HTTPS from Alice without `-k` or a custom CA argument:

```bash
docker compose -f output/docker-compose.yml exec -T hnode_151_alice \
  curl --fail https://mastodon.com:18443/api/v2/instance
```

For a browser on the Docker host, map `mastodon.com` to `127.0.0.1` in the hosts
file and import **`runtime/h14-ca/.step/certs/root_ca.crt`** into the browser/OS
trusted root store. Then open **https://mastodon.com:18443**. Host trust is not
changed automatically. This is a private experiment CA, not a publicly trusted CA.
Use the canonical domain: the ACME certificate does not cover `localhost`.

## Accounts and API

The entrypoint declares `admin` (Owner), `alice`, and `bob` using
`server.addAccount(username, password, *, email, admin=False)`. Initialization creates them with confirmed email addresses
and the specified passwords. Existing users have their emails and passwords synchronized at startup. Read credentials
locally when needed:

```bash
docker compose -f output/docker-compose.yml exec -T h14-mastodon \
  cat /var/lib/mastodon/accounts.json
```

Public registrations are enabled at every startup. Mail uses Rails' local file delivery
instead of SMTP, so web registrations still require email confirmation and no
confirmation email reaches an external inbox. For experiments, declare confirmed
accounts in `socialmedia.py` with `server.addAccount('username', 'Example123456', email='username@example.com')`, or confirm a web
registration through the administrator interface. External email delivery requires SMTP setup.

Account declarations are stored separately from the immutable instance identity.
After adding an account, regenerate, rebuild and recreate the service; existing
users and roles are preserved, emails and passwords are synchronized, and removing a declaration does not delete a user.
`admin=True` assigns Owner only to a newly created user.

For this local example, log in with `admin@mastodon.com` / `Admin123456`,
`alice@mastodon.com` / `Alice123456`, or `bob@mastodon.com` / `Bob123456`.
These passwords are included in generated build files and are for local experiments only.
To use authenticated APIs, create an application under Preferences → Development
and use its user access token. Store tokens outside tracked source files.

## Logs, restarts and data

Initialization log: `/var/log/mastodon-initialize.log`. Application logs:
`/var/log/mastodon-web.log`, `mastodon-worker.log`, and `mastodon-streaming.log`.
If initialization fails, fix the cause and restart the
Mastodon container and inspect its logs.

Named volumes retain PostgreSQL, Redis, application secrets/account credentials,
uploaded media and the ACME account/certificates (`/etc/letsencrypt`) across container recreation.
Domain/port settings must not
change after initialization; startup rejects a changed configuration.

```bash
docker compose -f output/docker-compose.yml down
```

Adding `--volumes` deletes application data, secrets and issued certificates.
Do not run H16 alongside another topology with conflicting networks,
container names or ports. Like H12/H13, the default Compose project is `output`.

When replacing the older H16 topology, run `docker compose down --remove-orphans`
using its old generated Compose file **before** regenerating `output`. This removes
old containers and networks; do not add `--volumes` if retaining application data.
The Mastodon address, domain, port and volume names remain unchanged. The new CA container and step-cli packages are included; retain `runtime/h14-ca/` to keep the trust anchor stable.

## Runtime tests

Like H12, `example.yaml` drives compilation, build, startup, readiness checks,
`test_runtime.py`, and teardown. From `/home/hhy/seed`:

```bash
emuvista/.venv/bin/python seed-emulator/seedemu/testing/cli.py all \
  emuvista/examples/H16_socialmedia/example.yaml --artifact-dir /tmp/h14-test-results
```

For an already running H16 deployment, run only the custom checks:

```bash
emuvista/.venv/bin/python seed-emulator/seedemu/testing/cli.py test \
  emuvista/examples/H16_socialmedia/example.yaml --artifact-dir /tmp/h14-test-results
```

Results are written to `/tmp/h14-test-results/h14-custom-runtime-test.json`.
Checks cover primary/secondary/recursive DNS, CA and Mastodon HTTPS using Alice
and Bob's default trust stores, instance and public timeline APIs, application
processes, and declared accounts. They do not publish posts or exercise login,
follow, favourite, or certificate renewal. Stop conflicting H16/H17 deployments
before using `all`; keep the existing persistent volumes and `runtime/h14-ca/`.

## References

- [Mastodon bundle](../../bundles/MastodonBundle/README.md)
- [Mastodon installation](https://docs.joinmastodon.org/admin/install/)
- [Mastodon API](https://docs.joinmastodon.org/client/intro/)
- Main reference: [SeedEmu pki_with_dns.py](../../../seed-emulator/examples/internet/B25_pki/pki_with_dns.py)
- CA implementation: [CAService.py](../../../seed-emulator/seedemu/services/CAService.py)
- [Certbot webroot documentation](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot)
- SeedEmu `docs/developer_manual/11-ca-service.md`
