# IdentityBundle

A shared company identity provider using Keycloak. Employees sign in with their
stable employee ID. ERP owns employee profiles; a directory worker synchronizes
registered applications through their native APIs. A real OpenLDAP catalog
mirrors employee attributes for backends that require directory lookup. User
passwords remain in the identity provider; the LDAP catalog does not store them.

```python
identity = IdentityBundle(emu, resolver=DNS_RESOLVER)
identity.setInitialConfiguration('company.json')
identity.setHostname('login.company.com').enableHostAccess(8085)
erp.connectIdentity(identity)
```

Set application/data network pools after rendering, then add the identity bundle
**after** its application bundles to the Docker compiler. `connectIdentity()`
records the relationship. Application `configure()` methods register OIDC or SAML clients
and source/consumer adapters; identity `install()` writes their final settings.

Use three application addresses and two data addresses (database, LDAP).

Build custom images with `docker compose -f docker_images/identity/compose.yml build`.
`identity-server` packages the upstream server with the networking tools required
by ContainerBundle. `auth-gateway` supplies standard OIDC authentication for
backends that support trusted-header login. Business APIs remain in their apps.

Administrator: `admin` / `IdentityAdminDemo123!`. Seeded employee passwords come
from the initial configuration. Runtime employees first use `EmployeeDemo123!`
and must change it. Use `setSavePath()` to preserve credentials, clients and state.

The example uses HTTP and localhost browser redirects. Backend requests stay on
the emulated network. Roles and existing sessions remain application-specific;
this directory is not a global authorization or instant session-revocation service.
