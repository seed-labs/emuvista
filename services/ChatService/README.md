# ChatService

ChatService is a composite service for SEED Emulator. It deploys a Tinode chat environment on ordinary SEED nodes using two logical roles:

- `ChatServer` runs MySQL and the Tinode daemon, and serves the HTTP and gRPC API that clients connect to.
- `ChatClient` runs `tn-cli` and connects an interactive command-line client to a `ChatServer`.

`ChatService` coordinates role relationships, node placement, credentials, and ports. It generates containers through the SEED `Node` API and does not require a dedicated application image.

## Basic usage

```python
from seedemu.core import Binding, Filter
from services.ChatService import ChatService

chat = ChatService(
    "packages/tinode-mysql.linux-amd64.tar.gz",
    "packages/tn-cli.tar.gz",
)

chat.installServer("chat151")
emulator.addBinding(
    Binding("chat151", filter=Filter(asn=151, nodeName="host_0"))
)

for vnode in ("cli152", "cli153"):
    chat.installClient(vnode, server_vnode="chat151")

emulator.addLayer(chat)
```

Each client vnode needs its own binding. A client may reference a server inside the topology with `server_vnode`, or a server outside it with `server_addr`; exactly one of the two is required.

## Server address resolution

A `ChatClient` created with `server_vnode` does not carry an address at build time. During `configure()`, `ChatService` looks up the resolved binding of the server vnode, takes that node's primary local-network address, and sets it on every client that references it. Clients attached with `server_addr` keep the supplied address.

The default ports are HTTP `6060` and gRPC `16060`. Change them on the service with `setHttpPort()` and `setGrpcPort()`; clients inherit the service ports during `configure()`.

## Credentials

The development defaults describe a lab deployment only: database user `tinode`, database password `tinode123`, database name `tinode`. Override them before deploying anywhere else:

```python
chat.setDbUser("...")
chat.setDbPassword("...")
chat.setDbName("...")
```

The Tinode API key served to clients is `ChatServer.DEFAULT_API_KEY`, the upstream sample key. A setter is not provided yet, so treat this key as a placeholder and do not rely on it for access control.

Values interpolated into generated shell and `sed` expressions pass through `check_safe()`, which accepts only alphanumerics and `_ - . @`, so a credential cannot break out of the generated commands.

## Demo topology

The demo topology — a B00 mini-Internet with one chat server on AS151 and four `tn-cli` clients — is not part of this package. It lands separately under `examples/`, which is where this repository keeps topology drivers, so that installing the service never drags a demo topology along with it.

The Tinode tarballs the topology needs are download artifacts, excluded from version control; see below.

## Chat packages

`installServer()` and `installClient()` take the paths of two archives and import them into the generated node at build time, so the service package itself never reads them. They are third-party build artifacts and are not committed here. A topology driver looks for them in `services/ChatService/packages/` by default; `packages/` is excluded from version control.

| Archive | Bytes | SHA-256 |
|---|---:|---|
| `tinode-mysql.linux-amd64.tar.gz` | 33,604,747 | `77fe75a4d7bd50afbfc7d8616f9f684b4f09c8302bb27bf41eb0486351de5ee1` |
| `tn-cli.tar.gz` | 18,765 | `8e8bfa41c94e5426720945a2935592af6f12b31e4acb75b418de500b6ccebb0b` |

Verify a copy before building:

```bash
sha256sum packages/tinode-mysql.linux-amd64.tar.gz packages/tn-cli.tar.gz
```

## Security boundaries

- The database user, password, and name are validated before interpolation into generated `mysql` and `sed` commands.
- Clients receive the server address resolved from the emulated local network, not from a hostname that the surrounding environment controls.
- Database and Tinode API credentials in this repository are lab defaults. Replace them, and keep the deployment off untrusted networks, before using it for anything sensitive.

## Main configuration API

```text
ChatService
  installServer(vnode)
  installClient(vnode, server_vnode=None, server_addr=None)
  setTinodePackage(path)
  setTnCliPackage(path)
  setTinodeGrpcVersion(version)
  setDbUser(user)
  setDbPassword(password)
  setDbName(name)
  setHttpPort(port)
  setGrpcPort(port)

ChatServer
  install(node)

ChatClient
  install(node)
  setServerVnode(vnode)
  setServerAddr(addr)
  setServerPorts(http_port, grpc_port)
```
