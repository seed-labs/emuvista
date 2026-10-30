# H15 Chat

This example demonstrates cross-AS messaging with ChatService. It reuses the
B00 mini-Internet topology, installs a Tinode server in AS151, and places four
`tn-cli` clients in AS152, AS153, AS154, and AS160. Two users can log in from
different ASes and exchange messages through the server.

## Topology

| Virtual node | ASN | Compose service | Role |
|---|---|---|---|
| `chat151` | 151 | `hnode_151_host_0` | Tinode server and MySQL database |
| `cli152` | 152 | `hnode_152_host_0` | Chat client |
| `cli153` | 153 | `hnode_153_host_0` | Chat client |
| `cli154` | 154 | `hnode_154_host_0` | Chat client |
| `cli160` | 160 | `hnode_160_host_0` | Chat client |

The server exposes HTTP on port `6060` and gRPC on port `16060`. The command-line
clients use **gRPC port 16060**. With the default B00 addressing, the server is
`10.151.0.71`. ChatService resolves the bound server address during configuration
and writes it to `/root/chat.env` on each client, so the commands below use that
file instead of hard-coding an address.

## How to Run

Use a Linux amd64 host with Docker Compose and a Python environment containing
the SEED Emulator dependencies. The SEED checkout must provide
`examples.internet.B00_mini_internet.mini_internet.build_emulator(hosts_per_as=...)`.
The current H15 example uses an amd64 Tinode binary and rejects `--platform arm`.

Activate your SEED Python environment. From the **emuvista repository root**, set
`SEEDEMU_ROOT` to the actual SEED checkout and generate the Docker configuration:

```bash
export SEEDEMU_ROOT="$HOME/seed-emulator"
python3 examples/H15_chat/chat.py --platform amd
cd examples/H15_chat/output
docker compose build
docker compose up -d
docker compose ps
```

For example, if SEED is under `~/seed-labs/seed-emulator`, use that path instead.
The script can also discover a sibling directory named `seed-emulator`.
Allow time for MySQL initialization and Tinode startup after the containers start.

During Docker build, ChatService downloads the two official
[Tinode v0.25.3 release assets](https://github.com/tinode/chat/releases/tag/v0.25.3)
and verifies their SHA-256 checksums before extraction. No `packages/` directory
is required. The build needs access to GitHub, the system package repositories,
and the Python package index.

## Create the Chat Service

The example first builds the B00 topology, then installs and binds the service:

```python
from examples.internet.B00_mini_internet import mini_internet
from seedemu.core import Binding, Filter
from services.ChatService import ChatService

emu = mini_internet.build_emulator(hosts_per_as=2)
chat = ChatService()

chat.installServer('chat151')
emu.addBinding(Binding('chat151', filter=Filter(asn=151, nodeName='host_0')))

for asn in (152, 153, 154, 160):
    vnode = 'cli{}'.format(asn)
    chat.installClient(vnode, server_vnode='chat151')
    emu.addBinding(Binding(vnode, filter=Filter(asn=asn, nodeName='host_0')))

emu.addLayer(chat)
```

`installServer()` and `installClient()` create virtual service nodes. The bindings
place them on physical hosts. `server_vnode` allows each client to obtain the
server address after binding. See the [ChatService README](../../services/ChatService/)
for service configuration methods.

## Manual Demonstration

The following demonstration uses two host terminals, one for Alice in AS152 and
one for Bob in AS153. Run Docker commands from `examples/H15_chat/output`.
Commands entered after starting `tn-cli.py` are **tn-cli commands, not Bash commands**.

### Step 1: Log in as Alice

On the host, in terminal A:

```bash
docker compose exec hnode_152_host_0 bash
```

Inside that client container:

```bash
source /root/chat.env
cd "$TNCLI_DIR"
python3 tn-cli.py --host="${TINODE_HOST}:${TINODE_GRPC_PORT}" \
  --login-basic=alice:alice123 --no-cookie
```

On a fresh database, the service runs Tinode's initializer with the bundled
`data.json`. The official [sample data](https://github.com/tinode/chat/blob/v0.25.3/tinode-db/data.json)
contains `alice/alice123` and `bob/bob123`. These are demonstration accounts;
existing databases or custom packages may have different accounts.
`--no-cookie` prevents this session from saving a login cookie.

Wait for a successful login response before continuing. Supplying only the IP
address can make the gRPC client attempt port `443`; always include `:16060`,
or use the generated environment variables as above.

### Step 2: Log in as Bob

On the host, in terminal B:

```bash
docker compose exec hnode_153_host_0 bash
```

Inside that client container:

```bash
source /root/chat.env
cd "$TNCLI_DIR"
python3 tn-cli.py --host="${TINODE_HOST}:${TINODE_GRPC_PORT}" \
  --login-basic=bob:bob123 --no-cookie
```

Keep both clients open. Successful logins verify connectivity and authentication;
the next steps verify message delivery.

### Step 3: Create and join a chat group

At Alice's **tn-cli prompt** in terminal A, enter:

```text
.must $group sub new --fn='H15 Chat Demo' --auth=JRWPA
.log $group.topic
```

`.must` waits for a successful response and stores it in `$group`. The second
command prints the server-assigned topic ID, beginning with `grp`. Copy that ID.
`H15 Chat Demo` is the display name, not the topic ID. The access mode permits
other authenticated demonstration users to join, read, and write in this group.

At Bob's **tn-cli prompt** in terminal B, enter the following, replacing
`<GROUP_ID>` with the complete ID printed by Alice (without angle brackets):

```text
.must sub <GROUP_ID>
```

Wait for the subscription to succeed. Both clients must attach to the same topic
to receive its live messages. Running `sub new` again creates a different group.

### Step 4: Exchange messages

At Alice's tn-cli prompt:

```text
.must pub $group.topic 'Hello Bob, this is Alice in AS152.'
```

Bob's terminal should display an incoming message containing that text. At Bob's
tn-cli prompt, replace `<GROUP_ID>` with the same topic ID and reply:

```text
.must pub <GROUP_ID> 'Hello Alice, this is Bob in AS153.'
```

Alice's terminal should display Bob's reply. A successful publish response confirms
server acceptance; seeing the message in the other terminal confirms delivery
across the emulated network. Exact output formatting and generated IDs may vary.

Clients in AS154 and AS160 can follow the same login and subscription steps with
an available account. After reconnecting, subscribe to the existing topic ID again.
Use `sub -h` and `pub -h` at the tn-cli prompt for command help. Further examples
are in the official [tn-cli sample script](https://github.com/tinode/chat/blob/v0.25.3/tn-cli/sample-script.txt).

### Step 5: Exit and stop the emulation

In each tn-cli session:

```text
.quit
```

Then enter `exit` at each container's Bash prompt. From the host's
`examples/H15_chat/output` directory:

```bash
docker compose down
```

This example does not configure persistent MySQL storage. Removing the server
container with `down` discards accounts and messages stored in its writable layer.
A new server container initializes the sample database again.

## Verification and Troubleshooting

Run these commands on the host from `examples/H15_chat/output`:

```bash
# Check container state.
docker compose ps

# Check server listeners and startup logs.
docker compose exec hnode_151_host_0 bash -lc 'ss -lntp | grep -E "6060|16060"'
docker compose exec hnode_151_host_0 tail -n 80 /root/tinode.log

# Inspect the address and ports supplied to a client.
docker compose exec hnode_152_host_0 cat /root/chat.env
```

- **Connection refused on port 443:** include the gRPC port in `--host`.
- **Connection refused on port 16060:** check the server listener and startup log.
  A running container does not necessarily mean Tinode has finished starting.
  If `tinode.log` does not exist yet, also inspect `docker compose logs hnode_151_host_0`.
- **Authentication fails:** verify the username and password and whether this is
  the initialized sample database. Do not recreate the database just to diagnose
  an account problem, as doing so would discard its data.
- **Login succeeds but no message arrives:** ensure both clients subscribed to
  the same server-generated group ID and that the publish command succeeded.

## Standard Arguments

Run these commands from the emuvista repository root:

```bash
python3 examples/H15_chat/chat.py amd
python3 examples/H15_chat/chat.py --platform amd --output examples/H15_chat/output
python3 examples/H15_chat/chat.py --dumpfile examples/H15_chat/chat.bin
```

Supported arguments:

- `amd`: optional legacy platform argument.
- `--platform amd`: supported platform; `arm` is rejected by H15.
- `--output PATH`: Docker compiler output directory.
- `--dumpfile PATH`: serialize the emulator instead of compiling Docker output.
- `--override` / `--no-override`: control replacement of existing output.
- `--skip-render`: compile without calling `emu.render()` first.
- `--hosts-per-as N`: hosts per stub AS in the B00 topology (default `2`).

## TestRunner Lifecycle

`example.yaml` declares `runner: internet`. If your SEED checkout includes
`seedemu/testing/cli.py`, run the following from the **SEED repository root**.
Set `H15_MANIFEST` to the absolute path of your emuvista manifest:

```bash
export H15_MANIFEST="$HOME/seed-labs/emuvista/examples/H15_chat/example.yaml"
python3 seedemu/testing/cli.py compile "$H15_MANIFEST"
python3 seedemu/testing/cli.py build   "$H15_MANIFEST"
python3 seedemu/testing/cli.py up      "$H15_MANIFEST"
python3 seedemu/testing/cli.py probe   "$H15_MANIFEST"
# Perform the manual chat demonstration before stopping the containers.
python3 seedemu/testing/cli.py down    "$H15_MANIFEST"
```

Alternatively, run the complete lifecycle:

```bash
python3 seedemu/testing/cli.py all "$H15_MANIFEST"
```

`all` cleans generated output, compiles, builds, starts, probes, and finally
stops the emulation. Use the separate steps when you want to keep it running
for interactive testing.

Readiness checks container state for the server and four clients. The probes
check ping reachability from AS152, AS153, and AS160 to the server. There is
currently no `test_runtime.py` or `test_programs` entry: automated checks do not
validate account login or message delivery. Use the manual demonstration above
to check those application-level operations.
