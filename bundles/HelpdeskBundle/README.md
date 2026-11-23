# HelpdeskBundle

IT tickets and asset management using GLPI, MariaDB and a standard OIDC gateway.
The backend uses its supported external-header authentication. Its native API
retains application/session-token authentication.

Use the common configuration/network methods and `connectIdentity()`. Employees
receive self-service profiles and a stable registration number equal to their
employee ID. Build application/gateway images with
`docker compose -f docker_images/helpdesk/compose.yml build`.

Native backend administrator: `glpi` / `HelpdeskAdminDemo123!`; the published
browser endpoint requires Company login. `setSavePath()` preserves data.
See [H98](../../examples/H98_virtual_company/).
