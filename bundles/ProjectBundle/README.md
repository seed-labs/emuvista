# ProjectBundle

Project management using OpenProject Community, PostgreSQL, web/worker processes
and a standard OIDC gateway. The gateway uses the backend's supported
trusted-header authentication; native APIs retain API-token authentication. Its native LDAP employee lookup
uses the catalog provided by IdentityBundle.

Use the common configuration/network methods and `connectIdentity()`. Native
accounts use employee IDs. The Company Operations project includes the seeded
employees. Build its application and gateway images with
`docker compose -f docker_images/project/compose.yml build`.

Use Company `admin` / `IdentityAdminDemo123!` for administration; the published
browser endpoint uses Company login. `setSavePath()` preserves data and secrets.
See [H98](../../examples/H98_virtual_company/).
