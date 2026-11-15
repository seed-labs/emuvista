# Email service

Mailu provides SMTP, IMAP, Roundcube Webmail and mailbox administration on the shared [H00 mini Internet](../H00_mini_internet/).

```sh
python3 email_service.py
cd output
docker compose build
docker compose up -d
```

Mailu uses the official `ghcr.io/mailu/*:2024.06.67` images; first build downloads them and adds routing tools when needed.

| Interface | Address |
| --- | --- |
| Webmail | http://localhost:8445/webmail/ |
| Administration | http://localhost:8445/admin/ |
| Internet Map | http://localhost:8080 |

| Account | Password | Role |
| --- | --- | --- |
| `admin@mail.com` | `MailAdminDemo123!` | Built-in administrator |
| `bank@mail.com` | `BankMailDemo123!` | Bank sender |
| `alice@mail.com` | `EmailDemo123!` | Mailbox |
| `bob@mail.com` | `EmailDemo123!` | Mailbox |
| `carol@mail.com` | `EmailDemo123!` | Mailbox |

Administrator credentials are fixed by EmailBundle. Internal webmail:
<http://mail.com/webmail/>.

Log into Webmail as Alice, click **Compose**, enter Bob's address, a subject and a message, then **Send**. Log into Bob's mailbox to read and reply. `support@mail.com` is an alias for Bob. Edit [mailboxes.json](mailboxes.json) to define domains, users, passwords, quotas and aliases.

In Administration, open **Mail domains** to manage domains, mailboxes, aliases and quotas. JSON creates the initial accounts. New users can register at
<http://localhost:8445/admin/user/signup/mail.com> while the service is running.

Agents inside the emulator use `mail.com` (`10.150.0.10`): authenticated SMTP submission on 587 and IMAP on 143. Server-to-server SMTP uses port 25. Mail protocol traffic remains on SEED networks; browser HTTP binds to localhost, and Internet Map uses port 8080.

Without `--state`, recompilation creates fresh mail storage outside `output`. Stop the current stack before recompiling. To save and resume mailboxes, use `python3 email_service.py --state ./email-state` with the same configuration and network. Keep the state directory outside `output`.

H00 provides root and TLD DNS, a recursive resolver at `10.150.0.54` and shared zone hosting at `10.154.0.53`. The mail domains have their own hosted zones with A/MX records. DNSSEC is disabled; EmailBundle skips Mailu's DNSSEC startup check. Public Internet mail delivery is not configured.

See [the bundle API](../../bundles/EmailBundle/README.md).
