# BankBundle

Apache Fineract with customer and Mifos staff websites, PostgreSQL databases, Redis and account initializer. Each container uses a SEED IP and the emulated router. SMTP/IMAP are supplied by an independent mailbox service.

```python
from services.BankService import BankBundle

emu.render()
bank = BankBundle(emu, resolver='10.150.0.54')
bank.setInitialConfiguration('bank.json')
bank.setDefaultInternalNetwork('net_151_net0',
    [f'10.151.0.{i}' for i in range(10, 10 + len(bank.getContainers()))], '10.151.0.254')
bank.setEmailServer('mail.seed.example', 'bank@seed.example',
    'replace-with-your-password', 'email/config/cert.pem')
bank.enableHostAccess(8444, staff_port=8446)
# Optional: bank.setSavePath('./bank-state')
compiler.addContainerBundle(bank)
```

When using EmailBundle in the same compilation, add it to the compiler before BankBundle. Relative certificate paths resolve in the compiler output directory. The mail certificate is trusted explicitly by both Java SMTP and Python IMAP clients; certificate and hostname verification remain enabled.

`setInitialConfiguration(path_or_dict)` accepts savings products and customers with accounts, opening balances and optional loans. Customer `email` and `password` configure bank access. `emailPassword` lets the initializer complete native registration using that customer's real IMAP mailbox. Examples supply all identities and balances; the library supplies no sample customers. Existing passwords and mail are retained on resume.

The nine component roles are `gateway`, `core`, `core-db`, `bff`, `bff-db`, `frontend`, `redis`, `initialize`, `staff`, in address order. The customer gateway and staff website publish browser ports on `127.0.0.1`; other components stay inside the emulator. Pass `staff_port=None` to omit the staff host port. Emulated clients use HTTPS on the gateway IP: customer APIs at `/api/v1/` and staff APIs at `/fineract-provider/api/v1/`. The staff IP serves the management website and the same staff API.

Without `setSavePath`, recompilation creates fresh storage outside `output`. Saved state includes both databases, Redis, initialization records, database credentials, JWT keys and TLS certificates. Stop the stack before recompiling, and resume with the same configuration and addresses. Existing eight-component saved deployments can add the staff address without resetting their bank data.

The default customer images are prepared Linux AMD64 artifacts from unmodified Apache Fineract Consumer Facing revision `ce2621c0fe76c28f58de5cf5627c49f20f5980ca`. The core image is `apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7`. To move the prepared application images to another host:

```sh
docker save -o bank-images.tar \
  apache/fineract:4a61d7c218413eca8310d30b098722047e891bb7 \
  emuvista/bank-consumer:ce2621c0fe76 \
  emuvista/bank-frontend:ce2621c0fe76
# On the destination:
docker load -i bank-images.tar
```

The staff website uses the public `openmf/web-app:1.14` image, pinned by digest in `DEFAULT_IMAGES`. It connects to the bundle's Fineract through its own HTTPS proxy; no external demo backend is used. PostgreSQL, Redis, nginx and Python also use public images. Override references with `BankBundle(emu, images={role: reference})`. See [H22](../../examples/H22_bank_service/README.md) for browser operations and the complete bank and email example.
