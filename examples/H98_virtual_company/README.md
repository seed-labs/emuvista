# Virtual Company

Company applications on H00's AS164 campus. The application and data LANs are
separate; departments and the branch office reach them through the emulated
network. Email, Bank, Payment and agents are not included.

## Start

From this directory:

```sh
for group in erp identity workchat project knowledge helpdesk; do
    DOCKER_BUILDKIT=0 docker compose -f ../../docker_images/$group/compose.yml build
done
python3 virtual_company.py
python3 build.py
cd output
docker compose up -d --no-build
```

`build.py` builds the generated base images first, then builds each service
individually with BuildKit. Run it again to rebuild using the cache, or use
`python3 build.py --no-cache` to rerun all build steps. Use `--output` when the
compiled deployment is in a different directory.

After changing sources under `docker_images`, rebuild the corresponding image
group first. Rerun `virtual_company.py` only when changing the topology or initial
configuration.

If GitHub downloads require a proxy, set `HTTPS_PROXY` or `https_proxy` in your
terminal before building. The script supplies it only to GitHub download steps
using a temporary Dockerfile and host networking. Generated Dockerfiles and
runtime networking stay unchanged.

The first startup installs the databases and company data. Containers ending in
`-initialize` exit with code 0 when finished. Stop with `docker compose down`.
Recompile without `--state` for a fresh company. To preserve all application data,
use `python3 virtual_company.py --state ../../.runtime/company` before building.

## Applications and login

| Application | Browser URL | Emulated domain |
| --- | --- | --- |
| ERP and HR | http://localhost:8082/app and http://localhost:8082/hrms | erp.company.com |
| Cloud drive | http://localhost:8081 | cloud.company.com |
| Company identity | http://localhost:8085/realms/company/account/ | login.company.com |
| Work chat | https://chat.localhost:8086 | chat.company.com |
| Projects | http://localhost:8087 | projects.company.com |
| Knowledge | http://localhost:8088 | knowledge.company.com |
| Helpdesk and IT assets | http://localhost:8089 | helpdesk.company.com |
| Internet Map | http://localhost:8080 | — |

Chat uses its native self-signed HTTPS certificate; accept the certificate once
in your browser. `chat.localhost` resolves to the local machine.

Choose **Company** on application login pages. Projects and Helpdesk redirect
automatically. Sign in with an employee ID below and `EmployeeDemo123!`. Within
the same browser, the identity session is reused across applications.

| Employee ID | Name | Initial responsibilities |
| --- | --- | --- |
| `EMP0001` | Alice Chen | Engineering manager, interviews, leave and expense approval, purchasing and sales |
| `EMP0002` | Bob Li | Employee self-service and business collaboration |
| `EMP0003` | Carol Wang | HR and accounting |

Employee IDs are stable. [company.json](company.json) seeds the company once.
Maintain employees in ERP/HR afterwards. ERP's Employee record supplies the name,
email, department, manager and employment status. A directory worker updates the
identity provider and application accounts through their native APIs every
30 seconds. Applications keep their own business permissions.

For a new employee, HR creates the Employee with a stable employee number. An
administrator opens that Employee, fills **Company Email**, selects **Company
Email** as the preferred contact email, saves, and clicks **Create User**. The directory creates the central login; its initial
password is `EmployeeDemo123!`, with a password change required at first login.

For administration, choose **Company** and sign in with `admin` /
`IdentityAdminDemo123!`. This opens each application's management account.
The identity administration console uses the same credentials.

Native backend accounts remain available for setup and recovery:

| Application | Account | Password |
| --- | --- | --- |
| Identity administration: http://localhost:8085/admin/ | `admin` | `IdentityAdminDemo123!` |
| ERP / HR | `Administrator` | `ERPAdminDemo123!` |
| Cloud drive | `admin` | `CompanyDrive123!` |
| Work chat | `admin@company.com` | `WorkChatAdminDemo123!` |
| Helpdesk backend | `glpi` | `HelpdeskAdminDemo123!` |

Projects and Helpdesk use their native trusted-header login behind an OIDC
gateway. Project employee lookup uses IdentityBundle's LDAP catalog. Their browser entry points require Company login; API routes retain
native API authentication. Knowledge uses native signed SAML.
ERP and work chat also retain native administrator login. Cloud's local login
is available at `/login?direct=1`.

## Try the business workflows

- **Leave:** Bob requests Annual Leave for a future weekday in HR. Alice approves
  it. Each employee has 20 days for the current calendar year.
- **Expenses:** Bob creates an Expense Claim of type Travel. Alice sets the
  sanctioned amount and `Main - EC` cost center, approves and submits it.
  Accounting creates its payment journal. Approved claims notify chat's finance
  channel when chat is available.
- **Purchasing and inventory:** create a Purchase Order for Company Hardware
  Supplier and `COMPANY-LAPTOP`; receive it into `Stores - EC`, then create the
  Purchase Invoice and Payment Entry.
- **Sales:** create a Sales Order for Company Customer, deliver the stocked item,
  invoice it and record the customer's payment.
- **Payroll:** Company Monthly Salary is assigned to the initial employees with
  a base of USD 5,000. Create a Salary Slip to calculate it. Recruitment and
  onboarding are described below.
- **Collaboration:** use company chat channels, the Company Operations project,
  knowledge pages, cloud files and Helpdesk tickets with the same employee login.
- **Shared profiles:** change Bob's first name on his Employee record. After the
  next sync, inspect his identity, cloud, chat, project, knowledge and helpdesk accounts; the employee ID stays fixed.

The company starts with USD 100,000 of opening cash in its native accounting
ledger. This example records internal business operations and does not connect
external bank or payment systems. Appraisal completion and full payroll
disbursement have not been verified end to end.

See the [validation walkthrough](../../docs/virtual-company-validation.md) for
the ordered manual checks and expected results (Chinese).

## Recruitment and onboarding

Use the native ERP search bar to open the document types below. These operations
were verified with a runtime hire, Dave Liu (`EMP0004`), without editing JSON or
recompiling the world.

| Step | Operator | Native operation |
| --- | --- | --- |
| Prepare interviews | Carol | Create a Skill and an Interview Round; add expected skills and select Alice as interviewer |
| Publish a vacancy | Carol | Create or edit a Job Opening, set its designation and department, and enable Publish; candidates can browse `/jobs` |
| Apply | Candidate | Open the public vacancy and select Apply Now; no employee login is required |
| Interview | Carol / Alice | Set the applicant's designation, create an Interview and schedule it; Alice submits Interview Feedback, then HR submits the cleared interview |
| Offer | Carol | Submit a Job Offer and record the candidate's response as Accepted |
| Plan onboarding | Carol | Create an Employee Onboarding linked to the applicant and offer; choose the company holiday list and add activities with assignees and required-task flags; submit it to create native tasks |
| Complete tasks | Assignees | Complete their assigned Tasks; required activities block premature employee creation |
| Create the employee | Carol | On the onboarding form, choose Create → Employee; enter a unique employee number, name, gender, birth/join dates, department and manager |
| Open the account | Administrator | On the Employee, fill Company Email, choose it as Preferred Contact Email, save, and click Create User; the central directory provisions application accounts |
| Finish setup | Carol / employee | Submit Leave Allocation and Salary Structure Assignment; the employee signs in through Company and changes the temporary password; HR closes the vacancy |

Administrators can prepare reusable Employee Onboarding Templates. HR can also
enter activities directly. Onboarding creates tasks in ERP's own project module;
these are independent of ProjectBundle. Alice and Carol have the native Projects
User role needed to handle those tasks, and Alice also has the Interviewer role.

The onboarding-to-employee link is retained even when all tasks were completed
before employee creation. Company Email is editable before account linking and
becomes read-only afterwards. Runtime hires were verified with ERP/HR, cloud, projects,
knowledge, helpdesk and chat single sign-on. Chat asks new users to confirm their
email visibility on first entry. Each application retains its own permissions.

Offer acceptance is recorded by HR. Company email delivery and candidate electronic
signing are not configured in this example.

## Deployment layout

| Application | Application addresses | Data addresses |
| --- | --- | --- |
| Cloud drive | 10.164.20.16 | 10.164.30.10, 10.164.30.12 |
| ERP / HR | 10.164.20.60–65 | 10.164.30.60–61 |
| Identity | 10.164.20.70–72 | 10.164.30.70–71 |
| Projects | 10.164.20.80–83 | 10.164.30.80 |
| Knowledge | 10.164.20.90–91 | 10.164.30.90 |
| Helpdesk | 10.164.20.100–102 | 10.164.30.100 |
| Work chat | 10.164.20.110–111 | 10.164.30.110–113 |

Chat requires native HTTPS; the other applications use HTTP. Browser login
redirects use localhost ports; service requests use emulated domains and addresses.
ERP trusts the chat certificate for notifications; no separate CA is deployed. The current custom ERP image is
AMD64. Software sources and deployment verification status are recorded in
[company research](../../docs/virtual-company-research.md) (Chinese).
