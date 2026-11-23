# ERPBundle

A company business management and HR bundle, backed by ERPNext and Frappe HR
on one Frappe site. Both applications share users, roles, employee records,
sessions, and a MariaDB database.

The upstream HR image includes Frappe, ERPNext, and HRMS. The bundle adds startup
configuration and initial company data; it does not replace their websites.
The [ERP application image](../../docker_images/erp/erp-app/Dockerfile) only selects root
for SEED's network setup; application processes run as the upstream `frappe` user.

```sh
docker compose -f docker_images/erp/compose.yml build
```

```python
erp = ERPBundle(emu, name='company-erp', resolver=DNS_RESOLVER)
erp.setHostname('erp.company.com')
erp.setInitialConfiguration('company.json')
erp.enableHostAccess(8082)

emu.render()
erp.addInternalNetwork('164', 'applications',
                       [f'10.164.20.{i}' for i in range(60, 66)])
erp.addInternalNetwork('164', 'data', ['10.164.30.60', '10.164.30.61'])
compiler.addContainerBundle(erp)
emu.compile(compiler, 'output', override=True)
```

The first network supplies six application addresses, in this order: frontend,
backend, websocket, worker, scheduler, initializer. The second supplies MariaDB
and Redis. Only the frontend has a host port mapping. SEED supplies routes.

Initialization waits for the database and Redis, installs both apps, creates
the company, and imports the supplied employees and leave allocations. Other
application processes wait for initialization to finish.

The example owns the employee data. Employee Number is the stable employee ID,
also used as the Employee document name and account username. User records link
to those employees. Employee profiles own linked account names and identifiers;
installed Frappe Server Scripts keep those fields consistent and preserve the
onboarding link when all activities finish before employee creation. Update shared
profile information through the Employee record. Passwords remain account data.

| Built-in account | Password |
| --- | --- |
| `Administrator` | `ERPAdminDemo123!` |

Employee credentials come from the example configuration. They are not mailbox
accounts and do not require an email server. Email notifications are disabled.

Use `connectIdentity(identity)` to join Company single sign-on and register ERP
as the canonical employee-profile source. `connectChat(chat)` configures expense
approval notifications through the native chat API. The bundle waits for chat
initialization and trusts its exported public certificate for these requests.
Neither application delegates its business permissions to the identity service.

Use `setSavePath(path)` to preserve ERP sites and database state across
recompilation. Without it, compilation uses a new temporary state directory.
Restarting the same generated Compose project reuses that project's data.
Reusing saved state does not reapply the initial employee configuration.

The current upstream application image is AMD64. H98 uses AMD64 for this bundle.
