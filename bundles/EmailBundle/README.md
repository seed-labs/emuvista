# EmailBundle

Deploys Mailu's SMTP/IMAP server, Roundcube Webmail, administration, Redis, Rspamd and mailbox initializer from prepared upstream images. Each component owns an emulated IP and uses the emulated router. DNS is provided by the example's infrastructure.

| Built-in administrator | Password |
| --- | --- |
| `admin@mail.com` | `MailAdminDemo123!` |

```python
from bundles.EmailBundle import EmailBundle

emu.render()
email = EmailBundle(emu, resolver='10.150.0.54')
email.setHostname('mail.com')
email.setInitialConfiguration('mailboxes.json')
email.addInternalNetwork('150', 'net0',
    [f'10.150.0.{i}' for i in range(10, 18)], '10.150.0.254')
email.enableHostAccess(8445)
# Optional: email.setSavePath('./email-state')
compiler.addContainerBundle(email)
emu.compile(compiler, './output', override=True)
```

Run `docker compose build` and `docker compose up -d` in `output`. Building only adds routing tools to prepared images; no application checkout or compilation is required. Override image references using `EmailBundle(emu, images={role: reference})`.

`setHostname(name)` sets the server domain, defaulting to `mail.com`. Configure DNS separately. `getURL()` returns its HTTP URL.

`getMailConnection(address)` exports SMTP/IMAP credentials for a configured
mailbox and the mailbox initializer dependency. Consumers can supply their own
initializer name to order startup when sharing a sender. The connection contains
no consumer-specific application settings.
`getDomains()` and `getMailboxConnection()` let consumers select the correct IMAP
server for each customer's address. A bank declares this with `connectEmail(email)`.

`setInitialConfiguration(path_or_dict)` supplies `domains`, `users` and optional `aliases`. The server hostname is configured separately with `setHostname()`. Users define `email`, `password`, optional `quota_bytes` and `change_password_on_login`. Aliases define `email` and a `destination` list of configured users. Each instance has `admin@<first configured domain>` / `MailAdminDemo123!`; the default example uses `admin@mail.com`. No administrator credential setter is exposed. Application mailboxes are supplied by the caller. Native Mailu APIs create the accounts at first startup. Existing mailbox passwords and data are retained on resume.

Mailu application components share one emulated subnet, matching its internal trust model. Their ordered roles are `front`, `admin`, `smtp`, `imap`, `redis`, `webmail`, `antispam`, `initialize`. The required `resolver` argument identifies an existing DNSSEC-validating resolver. Without a network assignment, free addresses are allocated on a rendered host network.

Only the front container publishes a browser port, bound to `127.0.0.1`. Emulated clients use its internal address: SMTP 25, authenticated SMTP 587, IMAP 143 and ManageSieve 4190. Webmail uses HTTP; SMTP and IMAP use plain connections. Users and agents authenticate to their own mailboxes.

After setting the initial configuration, `email.addUser(user)` adds one mailbox
using the same user fields before compilation.

[H00](../../examples/H00_mini_internet/) provides DNS using SEED's `DomainNameService`, `Dnssec` and `DomainNameCachingService`. Add application records before rendering. Supply the signer's `getTrustAnchor('.')` to the caching server's `addDnssecTrustAnchor()` and call `setDnssecValidation()`. Mailu also checks the signed name `example.org` at startup. H21 defines this name in its private simulation namespace; public Internet resolution is not configured. EmailBundle does not generate DNS records, keys or resolver containers.

Without `setSavePath`, recompilation uses fresh temporary state outside the output directory. Explicit saved state includes accounts, mail, queues, Webmail settings, Redis, DKIM, initialization markers and credentials. Stop the stack before recompiling; resume with the same configuration and network. H21 also saves the SEED DNS signing keys under `--state`.

See [H21](../../examples/H21_email_service/README.md) for accounts and browser use.

Agent sends use SMTP and then append a copy to the mailbox's Sent folder over
IMAP. Replies can supply `inReplyTo`; sent messages have Date/Message-ID headers.
`sent=true, savedToSent=false` reports accepted mail whose archive copy failed,
so callers must not resend merely to repair Sent. Inbox observations include full
text and reply identifiers, newest first.

`email.getAgentTools()` exports instance hostnames and served domains into
`context.tool_config['email']`. Personal `accounts.email` contains the address and
password. Tools select its provider by email domain, or an explicit personal
`instance` selector, and resolve SMTP/IMAP transport without exposing it to the model.

Public mailbox signup is available at `/admin/user/signup` (or
`/admin/user/signup/<domain>`). Configured domains allow registration through the
native Mailu form; no JSON edit is needed for new users.
