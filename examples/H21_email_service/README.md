# Email service

Mailu provides SMTP, IMAP, Roundcube Webmail and mailbox administration on the mini Internet.

```sh
python3 email_service.py
cd output
docker compose build
docker compose up -d
```

Use the updated SEED Emulator with the DNSSEC validation and signing-key APIs. Mailu uses the official `ghcr.io/mailu/*:2024.06.67` images; first build downloads them and adds routing tools when needed. SEED generates its signing keys using the official ISC BIND Docker image.

| Interface | Address |
| --- | --- |
| Webmail | https://localhost:8445/webmail/ |
| Administration | https://localhost:8445/admin/ |

Accept the laboratory certificate in your browser. Alice and Bob use `alice@seed.example` / `bob@seed.example` with password `EmailDemo123!`. Carol uses `carol@other.example` with the same password. The administrator is `postmaster@seed.example` / `MailAdminDemo123!`.

Log into Webmail as Alice, click **Compose**, enter Bob's address, a subject and a message, then **Send**. Log into Bob's mailbox to read and reply. `support@seed.example` is an alias for Bob. Edit [mailboxes.json](mailboxes.json) to define domains, users, passwords, quotas and aliases.

In Administration, open **Mail domains** to manage domains, mailboxes, aliases and quotas. Accounts are created from the JSON automatically; public sign-up is disabled.

Agents inside the emulator use `10.150.0.10`: SMTP submission on 587 with STARTTLS or 465 with TLS, and IMAPS on 993. Server-to-server SMTP uses port 25. Only browser HTTPS is mapped to localhost; protocol traffic remains on SEED networks. The certificate for client verification is `output/email/config/cert.pem`.

Without `--state`, recompilation creates fresh mail storage outside `output`. Stop the current stack before recompiling. To save and resume mailboxes, use `python3 email_service.py --state ./email-state` with the same configuration and network. Keep the state directory outside `output`.

SEED provides authoritative DNS at `10.150.0.53`, signs the private root with its `Dnssec` layer, and validates queries at `10.150.0.54`. EmailBundle uses this resolver. The private zone contains mail-domain A/MX records and the `example.org` record required by Mailu's startup check. Public Internet mail delivery is not configured.

See [the bundle API](../../services/EmailService/README.md).
