# Bundles

ContainerBundle integrations use external images and join rendered SEED networks.
Configure them after `emu.render()` and register them with `compiler.addContainerBundle()`.
Each bundle directly extends SEED's `ContainerBundle`. As in DemoBundle and
Internet Map, registration does not configure it: `emu.compile()` calls
`configure()` and then `install()`. Network pools and DNS remain in the top-level
example. Setters declare application settings; `connectEmail()`, `connectBank()` and `connectIdentity()`
declare partnerships without performing deployment operations.

The bundles use the same common configuration methods:

| Method | Purpose |
| --- | --- |
| `setHostname(name)` | Internal application domain; DNS records are configured separately |
| `setInitialConfiguration(path_or_dict)` | Initial business data |
| `enableHostAccess(port)` | Publish the browser endpoint on localhost |
| `addInternalNetwork(...)` | Assign containers to an emulated network |
| `setSavePath(path)` | Optionally preserve application state |
| `getURL()` | Internal application URL |

Service-specific options remain explicit, such as BankBundle's `staff_port`
for its separate administration website.

- [PaymentBundle](PaymentBundle/): web wallet, payment APIs, initialization and saved state.
- [EmailBundle](EmailBundle/): SMTP/IMAP, webmail and mailbox administration.
- [BankBundle](BankBundle/): banking APIs, customer and staff websites, account and card initialization.
- [ERPBundle](ERPBundle/): company business management and HR with shared identities and employee records.
- [IdentityBundle](IdentityBundle/): employee OIDC/SAML login, LDAP lookup and native directory adapters.
- [WorkChatBundle](WorkChatBundle/): company channels, direct messages and ERP notifications.
- [ProjectBundle](ProjectBundle/): projects, work packages and company login.
- [KnowledgeBundle](KnowledgeBundle/): knowledge pages and company login.
- [HelpdeskBundle](HelpdeskBundle/): IT tickets, assets and company login.
- [SocialNetworkBundle](SocialNetworkBundle/): Mastodon's development version with streaming, background jobs and account initialization.
```python
from bundles.PaymentBundle import PaymentBundle
```

SEED service layers remain in [services](../services/).
