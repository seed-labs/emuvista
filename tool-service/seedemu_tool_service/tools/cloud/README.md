# Cloud agent tools

This domain follows the DNS tool pattern: a running SEED topology explicitly
publishes its Nextcloud service with Docker labels, while each authorized source
publishes an assigned service ID and an opaque credential reference. The FastAPI
service reads those labels and executes only fixed WebDAV/OCS requests inside the
selected source container.

## Tool flow

1. `cloud.storage_find(source)` discovers only services assigned to `source`.
2. `cloud.file_upload` sends bounded base64 data through WebDAV `PUT`.
3. `cloud.file_share` creates a read-only user share through the Nextcloud OCS API.
4. `cloud.file_download` retrieves bounded data through WebDAV `GET`.

The topology, rather than this package, owns service URLs, container names,
network addresses, accounts and passwords. Credentials remain in
`/opt/seedemu/cloud/<service_id>/credentials` inside the source container and
are never returned through an API response.

## Metadata contract

Service container labels:

- `org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.service_id`
- `org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.provider=nextcloud`
- `org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.webdav_url`
- `org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.ocs_url`

Source container labels:

- `org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.services`
- `org.seedsecuritylabs.seedemu.meta.agent.exposed.cloud.credentials` (JSON map of service ID to opaque reference)
