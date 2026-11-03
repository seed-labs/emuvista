#!/usr/bin/env python3
"""H14: two DSH agents, Cloud Drive, DNS and PKI; generated only via SEED APIs."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.core import Action, Binding, Emulator, Filter
from seedemu.layers import Base, Routing
from seedemu.services import CAService, DomainNameService, RootCAStore
from services.CloudDriveService import CloudDriveService

ASN = 154
PREFIX = "10.154.0."
DOMAIN = "cloud.seedvista.test"
RUNTIME = HERE / ".runtime"
OUTPUT = HERE / "output"
DSH_RUNTIME_IMAGE = "seedemu-dsh-runtime:0.2.0-rc.2"
CLOUD_HTTPS_PORT = 18444
# Optional route to a host-only proxy; set to an empty string when not needed.
HOST_ONLY_NETWORK = "192.168.56.0/24"
# Claw packages are built for demonstration stage two, not loaded by default.
PLUGIN_PACKAGES = ("cloud-client", "cloud-bundle", "claw", "claw-bundle")

AGENT_INITIALIZATION = r"""#!/bin/bash
set -Eeuo pipefail
mkdir -p /run/emuvista
trap 'touch /run/emuvista/initialization.failed' ERR
exec 9>/run/emuvista/initialization.lock
flock 9
rm -f /run/emuvista/initialized /run/emuvista/initialization.failed
export DSH_HOME=/root/.dsh
profile="$DSH_HOME/profiles/demo"
pending="$DSH_HOME/.h14-profile-initializing"
mkdir -p "$DSH_HOME"
# A pending marker lets an interrupted first installation resume.
# An existing profile without this marker belongs to the user.
if [ ! -d "$profile" ] || [ -f "$pending" ]; then
    touch "$pending"
    if [ ! -d "$profile" ]; then
        dsh --profile demo --from-default-profile web --dump-config >/dev/null
    fi
    dsh plugin --profile demo add /opt/emuvista/agent-plugins/cloud-bundle
    cp /opt/emuvista/demo.patch.yml "$profile/cordis.patch.yml"
    touch "$profile/.h14-initialized"
    rm -f "$pending"
else
    echo "Preserving existing demo profile"
fi
dsh --profile demo --dump-config >/dev/null
rm -f /run/emuvista/initialization.failed
awk '{print $22}' /proc/1/stat >/run/emuvista/initialized
"""

CLOUD_INITIALIZATION = r"""#!/bin/bash
set -Eeuo pipefail
mkdir -p /run/emuvista
trap 'touch /run/emuvista/initialization.failed' ERR
exec 9>/run/emuvista/initialization.lock
flock 9
rm -f /run/emuvista/initialized /run/emuvista/initialization.failed
occ() {
    runuser -u www-data -- php /var/www/html/occ "$@"
}
# The service has already initialized Nextcloud before this post-config command.
# Apply the example default only when the user has not configured one.
if ! occ config:system:get skeletondirectory >/dev/null 2>&1; then
    occ config:system:set skeletondirectory --value=""
fi
for role in alice bob; do
    if occ user:info "$role" >/dev/null 2>&1; then
        echo "Preserving existing account: $role"
    else
        OC_PASS="${role}-password" runuser -u www-data -- php /var/www/html/occ user:add --password-from-env "$role"
    fi
done
rm -f /run/emuvista/initialization.failed
awk '{print $22}' /proc/1/stat >/run/emuvista/initialized
"""





def initialize_on_start(node, name: str, script: str) -> None:
    """Declare idempotent initialization and readiness through the SEED API."""
    path = f"/opt/emuvista/initialize-{name}.sh"
    node.addDockerCommand("RUN command -v flock")
    node.setFile(path, script)
    # Clear readiness before service startup, including ordinary container restarts.
    node.appendStartCommand(
        "mkdir -p /run/emuvista && "
        "rm -f /run/emuvista/initialized /run/emuvista/initialization.failed"
    )
    node.appendStartCommand(
        f"bash {path} >/var/log/h14-initialize.log 2>&1 "
        f"&& echo H14_{name.upper()}_INITIALIZED "
        "|| { cat /var/log/h14-initialize.log >&2; false; }",
        isPostConfigCommand=True,
    )
    node.addDockerCommand(
        "HEALTHCHECK --interval=2s --timeout=2s --start-period=300s --retries=3 "
        "CMD test \"$(head -n 1 /run/emuvista/initialized 2>/dev/null)\" "
        "= \"$(awk '{print $22}' /proc/1/stat)\""
    )


def install_agent_plugins(node) -> None:
    """Import repository source and compile it as part of the node image."""
    for package in PLUGIN_PACKAGES:
        source = ROOT / "agent-plugins" / package
        for entry in ("package.json", "pnpm-lock.yaml", "tsconfig.json", "cordis.patch.yml", "src", "tests"):
            path = source / entry
            files = sorted(path.rglob("*")) if path.is_dir() else [path]
            for file in files:
                if file.is_file():
                    node.importFile(
                        str(file), f"/opt/emuvista/agent-plugins/{package}/{file.relative_to(source)}"
                    )
    # This public API emits RUN after imported source files have been copied.
    for package in ("cloud-client", "claw", "cloud-bundle", "claw-bundle"):
        directory = f"/opt/emuvista/agent-plugins/{package}"
        node.addBuildCommandAtEnd(
            f"cd {directory} && pnpm install --frozen-lockfile --ignore-workspace"
        )
        if package in ("cloud-client", "claw"):
            node.addBuildCommandAtEnd(f"cd {directory} && pnpm run build")


def build_emulator() -> Emulator:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    temp = RUNTIME / "tmp"
    temp.mkdir(exist_ok=True)
    os.environ["TMPDIR"] = str(temp)
    tempfile.tempdir = str(temp)
    emulator = Emulator()
    base, routing = Base(), Routing()
    asys = base.createAutonomousSystem(ASN)
    asys.createNetwork("net0")
    asys.setNameServers([PREFIX + "53"])
    router = asys.createRouter("router0").joinNetwork("net0", address=PREFIX + "254")
    # Keep simulated client routing, with outbound Internet egress via Docker.
    router.appendStartCommand(
        f"ip route replace default via {PREFIX}1 dev net0", isPostConfigCommand=True
    )
    nodes = {
        name: asys.createHost(name).joinNetwork("net0", address=PREFIX + str(number))
        for name, number in (("cloud", 10), ("alice", 20), ("bob", 30), ("dns", 53), ("ca", 60))
    }
    # All hosts in this single-LAN demo use Docker NAT for external traffic.
    # Internal Cloud/DNS/CA traffic stays on the directly connected emulated LAN.
    for node in nodes.values():
        node.appendStartCommand(
            f"ip route replace default via {PREFIX}1 dev net0", isPostConfigCommand=True
        )
    if HOST_ONLY_NETWORK:
        for node in (router, *nodes.values()):
            node.appendStartCommand(
                f"ip route replace {HOST_ONLY_NETWORK} via {PREFIX}1 dev net0",
                isPostConfigCommand=True,
            )
    for name in ("alice", "bob"):
        node = nodes[name]
        node.addSoftware("curl jq ca-certificates coreutils")
        node.addDockerCommand(f"COPY --from={DSH_RUNTIME_IMAGE} /usr/local/ /usr/local/")
        install_agent_plugins(node)
        state = RUNTIME / name / "dsh"
        state.mkdir(parents=True, exist_ok=True)
        node.addSharedFolder("/root/.dsh", str(state))
        node.importFile(str(HERE / "agent/cordis.patch.yml"), "/opt/emuvista/demo.patch.yml")
        initialize_on_start(node, "agent", AGENT_INITIALIZATION)
    initialize_on_start(nodes["cloud"], "cloud", CLOUD_INITIALIZATION)
    nodes["cloud"].addPort(f"127.0.0.1:{CLOUD_HTTPS_PORT}", 443)
    dns = DomainNameService()
    dns.install("h14-dns").addZone("seedvista.test.")
    dns.getZone("seedvista.test.").resolveToVnode("cloud", "h14-drive")
    dns.getZone("seedvista.test.").resolveToVnode("ca", "h14-ca")
    ca = CAService()
    store = RootCAStore(caDomain="ca.seedvista.test")
    ca_server = ca.install("h14-ca")
    ca_server.setCAStore(store).setCertDuration("2160h").installCACert()
    cloud = CloudDriveService(saveState=True, savePath=str(RUNTIME / "cloud"))
    cloud.createDatabase("h14-db").setDatabasePassword("h14-demo-postgres-password")
    cloud.createObjectStorage("h14-objects").setCredentials("S3RVER", "S3RVER")
    drive = cloud.createDrive("h14-drive")
    drive.setDatabase("h14-db").setObjectStorage("h14-objects")
    drive.setAdminCredentials("admin", "h14-demo-admin-password")
    drive.setServerNames([DOMAIN]).setCAServer(ca_server).enableHTTPS()
    for vnode, name in (("h14-dns", "dns"), ("h14-ca", "ca"), ("h14-drive", "cloud")):
        emulator.addBinding(Binding(vnode, action=Action.FIRST, filter=Filter(asn=ASN, nodeName=name)))
    for layer in (base, routing, dns, ca, cloud):
        emulator.addLayer(layer)
    return emulator


def compile_topology() -> None:
    emulator = build_emulator()
    emulator.render()
    # DomainNameService is authoritative-only by default. Keep the local zone
    # and forward external lookups to Docker's per-container DNS resolver.
    dns_node = emulator.getLayer("Base").getAutonomousSystem(ASN).getHost("dns")
    dns_node.setFile("/etc/bind/named.conf.options", """options {
    directory "/var/cache/bind";
    recursion yes;
    allow-query { 127.0.0.0/8; 10.154.0.0/24; };
    allow-recursion { 127.0.0.0/8; 10.154.0.0/24; };
    dnssec-validation no;
    empty-zones-enable no;
    forward only;
    forwarders { 127.0.0.11; };
};
""")

    # Use SEED's pinned step-cli release from a reusable image.
    for (_, kind, _), node in emulator.getRegistry().getAll().items():
        if kind not in {"rs", "rnode", "hnode", "csnode"}:
            continue
        commands = node.getBuildCommands()
        commands[:] = [c for c in commands if "github.com/smallstep/cli/releases/download/" not in c]
        node.addDockerCommand(
            "COPY --from=smallstep/step-cli:0.26.1 /usr/local/bin/step /usr/local/bin/step"
        )
    emulator.compile(
        Docker(platform=Platform.AMD64, internetMapEnabled=False),
        str(OUTPUT), override=True,
    )
    print(f"CloudDrive topology compiled to {OUTPUT}")


if __name__ == "__main__":
    compile_topology()
