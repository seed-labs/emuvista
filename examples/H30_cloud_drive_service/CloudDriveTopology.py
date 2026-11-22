#!/usr/bin/env python3
"""H30: two DSH agents, Cloud Drive, DNS and PKI; generated only via SEED APIs."""
from __future__ import annotations

import argparse
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
from services.DshAgentService import DshAgentService

ASN = 158
PREFIX = "10.158.0."
DOMAIN = "cloud.h30.seedvista.test"
RUNTIME = HERE / ".runtime"
OUTPUT = HERE / "output"
CLOUD_HTTPS_PORT = 18445
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
        f"bash {path} >/var/log/h30-initialize.log 2>&1 "
        f"&& echo H30_{name.upper()}_INITIALIZED "
        "|| { cat /var/log/h30-initialize.log >&2; false; }",
        isPostConfigCommand=True,
    )
    node.addDockerCommand(
        "HEALTHCHECK --interval=2s --timeout=2s --start-period=300s --retries=3 "
        "CMD test \"$(head -n 1 /run/emuvista/initialized 2>/dev/null)\" "
        "= \"$(awk '{print $22}' /proc/1/stat)\""
    )


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
    agents = DshAgentService()
    for name in ("alice", "bob"):
        state = RUNTIME / name / "dsh"
        state.mkdir(parents=True, exist_ok=True)
        nodes[name].addSharedFolder(f"/var/lib/dshagent/{name}", str(state))
        nodes[name].addSoftware("netcat-openbsd")
        agents.install(name, bundles=[HERE / "bundles/cloud-tools.yml"])
        emulator.addBinding(Binding(name, filter=Filter(asn=ASN, nodeName=f"^{name}$")))
    initialize_on_start(nodes["cloud"], "cloud", CLOUD_INITIALIZATION)
    nodes["cloud"].addPort(f"127.0.0.1:{CLOUD_HTTPS_PORT}", 443)
    dns = DomainNameService()
    dns.install("h30-dns").addZone("h30.seedvista.test.")
    dns.getZone("h30.seedvista.test.").resolveToVnode("cloud", "h30-drive")
    dns.getZone("h30.seedvista.test.").resolveToVnode("ca", "h30-ca")
    ca = CAService()
    store = RootCAStore(caDomain="ca.h30.seedvista.test")
    ca_server = ca.install("h30-ca")
    ca_server.setCAStore(store).setCertDuration("2160h").installCACert()
    cloud = CloudDriveService(saveState=True, savePath=str(RUNTIME / "cloud"))
    cloud.createDatabase("h30-db").setDatabasePassword("h30-demo-postgres-password")
    cloud.createObjectStorage("h30-objects").setCredentials("S3RVER", "S3RVER")
    drive = cloud.createDrive("h30-drive")
    drive.setDatabase("h30-db").setObjectStorage("h30-objects")
    drive.setAdminCredentials("admin", "h30-demo-admin-password")
    drive.setServerNames([DOMAIN]).setCAServer(ca_server).enableHTTPS()
    for vnode, name in (("h30-dns", "dns"), ("h30-ca", "ca"), ("h30-drive", "cloud")):
        emulator.addBinding(Binding(vnode, action=Action.FIRST, filter=Filter(asn=ASN, nodeName=name)))
    for layer in (base, routing, dns, ca, cloud, agents):
        emulator.addLayer(layer)
    return emulator


def compile_topology(output: Path = OUTPUT) -> None:
    emulator = build_emulator()
    emulator.render()
    # DomainNameService is authoritative-only by default. Keep the local zone
    # and forward external lookups to Docker's per-container DNS resolver.
    dns_node = emulator.getLayer("Base").getAutonomousSystem(ASN).getHost("dns")
    dns_node.setFile("/etc/bind/named.conf.options", """options {
    directory "/var/cache/bind";
    recursion yes;
    allow-query { 127.0.0.0/8; 10.158.0.0/24; };
    allow-recursion { 127.0.0.0/8; 10.158.0.0/24; };
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
        str(output), override=True,
    )
    print(f"CloudDrive topology compiled to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    compile_topology(parser.parse_args().output.resolve())
