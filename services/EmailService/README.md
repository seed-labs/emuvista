# EmailBundle

Deploys Mailu's SMTP/IMAP server, Roundcube Webmail, administration, Redis, Rspamd and mailbox initializer from prepared upstream images. Each component owns an emulated IP and uses the emulated router. DNS is provided by the example's infrastructure.

```python
from services.EmailService import EmailBundle

emu.render()
email = EmailBundle(emu, resolver='10.150.0.54')
email.setInitialConfiguration('mailboxes.json')
email.addInternalNetwork('150', 'net0',
    [f'10.150.0.{i}' for i in range(10, 18)], '10.150.0.254')
email.enableHostAccess(8445)
# Optional: email.setSavePath('./email-state')
compiler.addContainerBundle(email)
emu.compile(compiler, './output', override=True)
```

Run `docker compose build` and `docker compose up -d` in `output`. Building only adds routing tools to prepared images; no application checkout or compilation is required. Override image references using `EmailBundle(emu, images={role: reference})`.

`setInitialConfiguration(path_or_dict)` supplies `hostname`, `domains`, `admin`, `users` and optional `aliases`. Users define `email`, `password`, optional `quota_bytes` and `change_password_on_login`. Aliases define `email` and a `destination` list of configured users. No sample identities are supplied by the library. Native Mailu APIs create the accounts at first startup. Existing mailbox passwords and data are retained on resume.

Mailu application components share one emulated subnet, matching its internal trust model. Their ordered roles are `front`, `admin`, `smtp`, `imap`, `redis`, `webmail`, `antispam`, `initialize`. The required `resolver` argument identifies an existing DNSSEC-validating resolver. Without a network assignment, free addresses are allocated on a rendered host network.

Only the front container publishes a browser port, bound to `127.0.0.1`. Emulated clients use its internal address: SMTP 25, authenticated SMTP 587/465, IMAP 143/993 and ManageSieve 4190. Use the generated `email/config/cert.pem` to trust the laboratory certificate in protocol clients. Users and agents authenticate to their own mailboxes.

[H00](../../examples/H00_mini_internet/) provides DNS using SEED's `DomainNameService`, `Dnssec` and `DomainNameCachingService`. Add application records before rendering. Supply the signer's `getTrustAnchor('.')` to the caching server's `addDnssecTrustAnchor()` and call `setDnssecValidation()`. Mailu also checks the signed name `example.org` at startup. H21 defines this name in its private simulation namespace; public Internet resolution is not configured. EmailBundle does not generate DNS records, keys or resolver containers.

Without `setSavePath`, recompilation uses fresh temporary state outside the output directory. Explicit saved state includes accounts, mail, queues, Webmail settings, Redis, DKIM, TLS keys, initialization markers and credentials. Stop the stack before recompiling; resume with the same configuration and network. H21 also saves the SEED DNS signing keys under `--state`. TLS certificates have a finite lifetime and should be renewed for longer experiments.

See [H21](../../examples/H21_email_service/README.md) for accounts and browser use.
