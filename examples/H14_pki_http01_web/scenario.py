#!/usr/bin/env python3
"""Build a minimal HTTP-01 WebService scenario using SEEDEmu's CAService."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
DEFAULT_SEEDEMU_ROOT = HERE.parents[2] / "seed-emulator"
SEEDEMU_ROOT = Path(os.environ.get("SEEDEMU_ROOT", DEFAULT_SEEDEMU_ROOT)).expanduser()
if str(SEEDEMU_ROOT) not in sys.path:
    sys.path.insert(0, str(SEEDEMU_ROOT))

from seedemu.compiler import Docker, Platform  # noqa: E402
from seedemu.core import Binding, Emulator, Filter  # noqa: E402
from seedemu.layers import Base, Routing  # noqa: E402
from seedemu.services import (  # noqa: E402
    CAService,
    DomainNameService,
    RootCAStore,
    WebService,
)

DOMAIN = "pki.test."
CA_DOMAIN = "ca.pki.test"


def build_emulator() -> Emulator:
    emu = Emulator()
    base = Base()
    routing = Routing()
    as150 = base.createAutonomousSystem(150)
    as150.createNetwork("net0", prefix="10.150.0.0/24")
    as150.createRouter("router0").joinNetwork("net0")
    as150.setNameServers(["10.150.0.53"])
    nodes = {}
    for name, address in (
        ("ca", "10.150.0.10"),
        ("web", "10.150.0.20"),
        ("client", "10.150.0.30"),
        ("dns", "10.150.0.53"),
    ):
        nodes[name] = as150.createHost(name).joinNetwork("net0", address)
    nodes["ca"].addSoftware("python3")

    dns = DomainNameService()
    dns_server = dns.install("pki-dns").addZone(DOMAIN).setMaster()
    zone = dns.getZone(DOMAIN)
    zone.addRecord("@ NS ns.pki.test.")
    zone.addRecord("ns A 10.150.0.53")
    zone.addRecord("ca A 10.150.0.10")
    zone.addRecord("web A 10.150.0.20")

    ca_service = CAService()
    ca_server = ca_service.install("pki-ca")
    ca_server.setCAStore(RootCAStore(CA_DOMAIN))
    ca_server.installCACert(Filter(asn=150))

    web_service = WebService()
    web_server = web_service.install("pki-web")
    web_server.setServerNames(["web.pki.test"]).setCAServer(ca_server).enableHTTPS()

    emu.addLayer(base)
    emu.addLayer(routing)
    emu.addLayer(dns)
    emu.addLayer(ca_service)
    emu.addLayer(web_service)
    emu.addBinding(Binding("pki-dns", filter=Filter(asn=150, nodeName="dns")))
    emu.addBinding(Binding("pki-ca", filter=Filter(asn=150, nodeName="ca")))
    emu.addBinding(Binding("pki-web", filter=Filter(asn=150, nodeName="web")))
    return emu


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "output-h14")
    parser.add_argument("--platform", choices=["amd", "arm"], default="amd")
    args = parser.parse_args()

    emu = build_emulator()
    emu.render()
    platform = Platform.AMD64 if args.platform == "amd" else Platform.ARM64
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(Docker(platform=platform), str(output), override=True)
    print(f"Generated HTTP-01 PKI example in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
