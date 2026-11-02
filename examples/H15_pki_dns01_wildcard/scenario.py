#!/usr/bin/env python3
"""Build a wildcard-certificate scenario with a restricted RFC 2136 updater."""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import secrets
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
DNS_CONFIG = "/etc/bind/pki-dns01.conf"
ZONE_FILE = "/etc/bind/zones/pki.test"
KEY_FILE = "/etc/bind/acme-update.key"
CREDENTIALS_FILE = "/etc/letsencrypt/credentials/rfc2136.ini"


def build_emulator() -> Emulator:
    emu = Emulator()
    base = Base()
    routing = Routing()
    as150 = base.createAutonomousSystem(150)
    as150.createNetwork("net0", prefix="10.150.0.0/24")
    nodes = {}
    for name, address in (
        ("ca", "10.150.0.10"),
        ("web", "10.150.0.20"),
        ("client", "10.150.0.30"),
        ("dns", "10.150.0.53"),
    ):
        nodes[name] = as150.createHost(name).joinNetwork("net0", address)

    dns = DomainNameService()
    dns_server = dns.install("pki-dns").addZone(DOMAIN).setMaster()
    dns_server.setInclude(DOMAIN, DNS_CONFIG)
    zone = dns.getZone(DOMAIN)
    zone.addRecord("@ SOA ns.pki.test. hostmaster.pki.test. 2026110301 900 900 1800 60")
    zone.addRecord("@ NS ns.pki.test.")
    zone.addRecord("ns A 10.150.0.53")
    zone.addRecord("ca A 10.150.0.10")
    zone.addRecord("api.svc A 10.150.0.20")

    tsig_secret = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    nodes["dns"].setFile(ZONE_FILE, "\n".join(zone.getRecords()) + "\n")
    nodes["dns"].setFile(
        KEY_FILE,
        'key "acme-updater" { algorithm hmac-sha256; secret "{}"; };\n'.format(
            tsig_secret
        ),
    )
    nodes["dns"].setFile(
        DNS_CONFIG,
        '''include "{}";
zone "pki.test." {{
    type master;
    file "{}";
    update-policy {{
        grant acme-updater name _acme-challenge.svc.pki.test. TXT;
    }};
}};
'''.format(KEY_FILE, ZONE_FILE),
    )
    nodes["dns"].addBuildCommandAtEnd(
        "chown root:bind {} && chmod 0640 {}".format(KEY_FILE, KEY_FILE)
    )

    credentials = (
        "dns_rfc2136_server = 10.150.0.53\n"
        "dns_rfc2136_port = 53\n"
        "dns_rfc2136_name = acme-updater\n"
        "dns_rfc2136_secret = {}\n"
        "dns_rfc2136_algorithm = HMAC-SHA256\n"
    ).format(tsig_secret)
    nodes["web"].setFile(CREDENTIALS_FILE, credentials)
    nodes["web"].addSoftware("certbot python3-certbot-dns-rfc2136")
    nodes["web"].addBuildCommandAtEnd(
        "install -d -m 0700 /etc/letsencrypt/credentials && chmod 0600 {}".format(
            CREDENTIALS_FILE
        )
    )

    ca_service = CAService()
    ca_server = ca_service.install("pki-ca")
    ca_server.setCAStore(RootCAStore(CA_DOMAIN))
    ca_server.installCACert(Filter(asn=150))

    web_service = WebService()
    web_server = web_service.install("pki-web")
    web_server.setServerNames(["api.svc.pki.test"])

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
    parser.add_argument("--output", type=Path, default=HERE / "output")
    parser.add_argument("--platform", choices=["amd", "arm"], default="amd")
    args = parser.parse_args()

    emu = build_emulator()
    emu.render()
    platform = Platform.AMD64 if args.platform == "amd" else Platform.ARM64
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(Docker(platform=platform), str(output), override=True)
    print(f"Generated DNS-01 PKI example in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
