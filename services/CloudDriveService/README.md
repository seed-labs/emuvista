# CloudDriveService

CloudDriveService is a composite service for SEED Emulator. It deploys a cloud drive environment on ordinary SEED nodes using three logical roles:

- `NextcloudServer` provides the Web UI, WebDAV, and OCS APIs.
- `PostgreSQLServer` stores users, shares, file indexes, and other metadata.
- `ObjectStorageServer` provides S3-compatible object storage.

`CloudDriveService` coordinates role relationships, node placement, credentials, access control, and optional persistence. It generates containers through the SEED `Node` API and does not require a dedicated application image.

## Basic usage

```python
from seedemu.core import Binding, Filter
from services.CloudDriveService import CloudDriveService

cloud = CloudDriveService()

database = cloud.createDatabase("cloud-db")
objects = cloud.createObjectStorage("cloud-objects")
drive = cloud.createDrive("cloud-app")

drive.setDatabase("cloud-db")
drive.setObjectStorage("cloud-objects")

emulator.addLayer(cloud)
emulator.addBinding(
    Binding("cloud-app", filter=Filter(nodeName="cloud"))
)
```

Only the Drive role needs a binding by default. The database and object storage roles inherit the Drive node, so all three roles run in one container.

## Split deployment

Add standard SEED bindings for the database or object storage vnodes to place them on separate nodes:

```python
emulator.addBinding(
    Binding("cloud-db", filter=Filter(nodeName="database"))
)
emulator.addBinding(
    Binding("cloud-objects", filter=Filter(nodeName="object-storage"))
)
```

The service supports co-located, partially split, and fully split deployments. Backend listen addresses and access allowlists are derived from the resolved bindings. A backend accepts connections only from Drive nodes that reference it.

## HTTPS, DNS, and host ports

The topology is responsible for public names, DNS records, certificate authorities, and host port mappings. To enable HTTPS, configure a public server name and associate the Drive with a SEED `CAServer`:

```python
drive.setServerNames(["cloud.example.test"])
drive.setCAServer(ca_server)
drive.enableHTTPS()
```

Publish DNS records through `DomainNameService`. CloudDriveService does not add host port mappings automatically; call `addPort()` on the selected physical node when access from outside the emulated network is required.

## Credentials

The service generates random database, object storage, and Drive administrator credentials for each logical vnode and distributes them during topology construction. Credentials may also be supplied explicitly:

```python
database.setDatabasePassword("...")
objects.setCredentials("...", "...")
drive.setAdminCredentials("...", "...")
```

Use `getCredentialManager()` only when deployment automation must deliver generated credentials to an authorized component. Do not write returned credentials to logs or source files.

## Persistence and recovery

Persistence is disabled by default. When enabled, PostgreSQL data, stored objects, Nextcloud configuration and data, and matching credentials are saved in a caller-selected host directory:

```python
cloud = CloudDriveService(
    saveState=True,
    savePath="./cloud-drive-state",
)
```

Reusing the same directory automatically loads the existing state. The explicit form is:

```python
cloud = CloudDriveService.loadState("./cloud-drive-state")
```

Set `override=True` to create a new state while preserving the previous directory under a numeric suffix.

The state directory contains runtime data and secrets. Restrict access to it and exclude it from version control. The database, object store, application data, and credential file form one state and should be backed up and restored together.

## Security boundaries

- PostgreSQL and object storage listen only on loopback and their selected emulated-network addresses.
- Dedicated, idempotent firewall chains allow backend access only from Drive nodes that reference each backend.
- Generated credentials are stored in a state file with mode `0600`; loading validates permissions, structure, and conflicts with explicit credentials.
- Nextcloud and object storage versions are pinned, and the Nextcloud archive is verified with a pinned SHA-256 digest.
- A container with network administration privileges can alter its own firewall rules. Grant only the capabilities required by the deployment.

## Main configuration API

```text
CloudDriveService
  createDrive(vnode)
  createDatabase(vnode)
  createObjectStorage(vnode)
  loadState(path)

NextcloudServer
  setDatabase(vnode)
  setObjectStorage(vnode)
  setServerNames(names)
  setAdminCredentials(username, password)
  setCAServer(ca_server)
  enableHTTPS()

PostgreSQLServer
  setDatabaseName(name)
  setDatabaseUser(user)
  setDatabasePassword(password)
  setPort(port)

ObjectStorageServer
  setBucket(bucket)
  setCredentials(access_key, secret_key)
  setRegion(region)
  setPort(port)
```
