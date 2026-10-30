# ChatService

ChatService is a composite service for SEED Emulator. It deploys a Tinode chat environment on ordinary SEED nodes using two logical roles:

- `ChatServer` runs MySQL and the Tinode daemon, and serves the HTTP and gRPC API that clients connect to.
- `ChatClient` runs `tn-cli` and connects an interactive command-line client to a `ChatServer`.

`ChatService` coordinates role relationships, node placement, credentials, and ports. It generates containers through the SEED `Node` API and does not require a dedicated application image.

## Basic usage

The following assumes `emulator` already contains AS151, AS152, and AS153,
each with a physical host named `host_0`. Configure service settings before
calling `installServer()` or `installClient()`.

```python
from seedemu.core import Binding, Filter
from services.ChatService import ChatService

chat = ChatService()  # Downloads pinned official packages during Docker build.

chat.installServer("chat151")
emulator.addBinding(
    Binding("chat151", filter=Filter(asn=151, nodeName="host_0"))
)

for vnode, asn in (("cli152", 152), ("cli153", 153)):
    chat.installClient(vnode, server_vnode="chat151")
    emulator.addBinding(
        Binding(vnode, filter=Filter(asn=asn, nodeName="host_0"))
    )

emulator.addLayer(chat)
```

Each client vnode needs its own binding. A client may reference a server inside the topology with `server_vnode`, or a server outside it with `server_addr`; exactly one of the two is required.

## Server address resolution

A `ChatClient` created with `server_vnode` does not carry an address at build time. During `configure()`, `ChatService` looks up the resolved binding of the server vnode, takes that node's primary local-network address, and sets it on every client that references it. Clients attached with `server_addr` keep the supplied address.

The default ports are HTTP `6060` and gRPC `16060`. Before installing server or client targets, change them on the service with `setHttpPort()` and `setGrpcPort()`; clients inherit the service ports during `configure()`.

## Credentials

The development defaults describe a lab deployment only: database user `tinode`, database password `tinode123`, database name `tinode`. Override them before deploying anywhere else:

```python
chat.setDbUser("...")
chat.setDbPassword("...")
chat.setDbName("...")
```

The Tinode API key served to clients is `DEFAULT_API_KEY` in `ChatServer.py`, the upstream sample key. A setter is not provided yet, so treat this key as a placeholder and do not rely on it for access control.

Values interpolated into generated shell and `sed` expressions pass through `check_safe()`, which accepts only alphanumerics and `_ - . @`, to restrict these interpolated values.

## Demo topology

The demo topology — a B00 mini-Internet with one chat server on AS151 and four `tn-cli` clients — is not part of this package. It lives separately in [H15 Chat](../../examples/H15_chat/), which is where this repository keeps topology drivers, so that installing the service never drags a demo topology along with it.

The Tinode tarballs are downloaded automatically during Docker build and are not committed; see below.

## Chat packages

With `ChatService()`, server and client Docker builds download the two official [Tinode v0.25.3 release assets](https://github.com/tinode/chat/releases/tag/v0.25.3) and verify the SHA-256 values below before extracting. This follows the build-time release download pattern used by CAService, with pinned versions and checksum verification as used in the Monero base-image build. The default server binary targets Linux amd64. Docker builds need network access to GitHub and the Python package index. No local packages directory is required.

For local archive overrides, pass `tinode_pkg` and/or `tncli_pkg` to `ChatService`, or use `setTinodePackage()` / `setTnCliPackage()`. The H15 example always uses build-time downloads and does not discover local archives. For direct service users, each omitted archive path selects its official download. Supplied local archives are imported as-is; the checksum table can be used to verify them manually.

| Archive | Bytes | SHA-256 |
|---|---:|---|
| `tinode-mysql.linux-amd64.tar.gz` | 33,604,747 | `77fe75a4d7bd50afbfc7d8616f9f684b4f09c8302bb27bf41eb0486351de5ee1` |
| `tn-cli.tar.gz` | 18,765 | `8e8bfa41c94e5426720945a2935592af6f12b31e4acb75b418de500b6ccebb0b` |

Verify a copy before building:

```bash
sha256sum packages/tinode-mysql.linux-amd64.tar.gz packages/tn-cli.tar.gz
```

The downloaded client requirements are installed by pip. They contain version ranges,
so the full Python dependency set is not locked. `setTinodeGrpcVersion(version)`
can select a specific `tinode-grpc` version before installing clients; H15 exposes
this through the `TINODE_GRPC_VERSION` environment variable.

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
