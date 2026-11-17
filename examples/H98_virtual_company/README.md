# Virtual Company

Company applications on H00's AS164 campus. Network construction belongs to
[H00](../H00_mini_internet/); this example configures services and bindings.

Currently includes the existing CloudDriveService, with its application in the
application LAN and PostgreSQL and object storage on separate data LAN hosts.
Other business systems will be added individually. Email, Bank, and Payment are
not included.

```sh
python3 virtual_company.py
cd output
DOCKER_BUILDKIT=0 docker compose build
docker compose up -d
```

| Interface | URL | Account | Password |
| --- | --- | --- | --- |
| Cloud drive | http://localhost:8081 | `admin` | `CompanyDrive123!` |
| Internet Map | http://localhost:8080 | — | — |

Inside the emulation, use http://cloud.company.com.

| Role | Node | Address |
| --- | --- | --- |
| Cloud drive | `cloud` | `10.164.20.16` |
| Database | `database1` | `10.164.30.10` |
| Object storage | `storage` | `10.164.30.12` |

The example uses HTTP and does not enable persistence. Stop with
`docker compose down`. Use `--platform arm` when generating for ARM64.

Software candidates and development order:
[company research](../../docs/virtual-company-research.md) (Chinese).
