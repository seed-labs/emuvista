# WorkChatBundle

Company channels, topics and direct messages using Zulip. Uses the upstream
application, PostgreSQL, RabbitMQ and Redis. The database image packages the
upstream SQL and English search dictionaries on Debian PostgreSQL; PGroonga
remains disabled, matching the upstream default. Build it and the SASL cache
with `docker_images/workchat/compose.yml`.

Configure with `setInitialConfiguration()`, `setHostname()`, `enableHostAccess()`
and `connectIdentity()`. Add application and data networks after rendering.
`ERPBundle.connectChat()` enables native expense-approval notifications to the
finance channel. The initial channels are general, engineering, human-resources,
finance and support.

The backend requires HTTPS and generates its own self-signed certificate. With
host access enabled, the browser uses `https://chat.localhost:8086`; accept its
certificate on first use. Only the public certificate is exported for connected
ERP requests; the private key stays in chat storage. Its native outbound proxy
allows the internal identity-provider address.

Employee OIDC login shares the company identity session. The native administrator
is `admin@company.com` / `WorkChatAdminDemo123!`. `setSavePath()` preserves data.
See [H98](../../examples/H98_virtual_company/) for the complete deployment.
