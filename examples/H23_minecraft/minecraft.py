#!/usr/bin/env python3
"""Add one Minecraft Java server to SEED's B02 mini Internet with DNS."""

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT.parent / 'seed-emulator'), str(ROOT)]

from seedemu.compiler import Docker, Platform
from seedemu.containerBundle import InternetMap
from seedemu.layers import PeerRelationship
from bundles.MinecraftBundle import MinecraftBundle
# Use SEED's B02 directly: its InternetMap setup uses the current ContainerBundle
# API, while H00's entrypoint still passes the unsupported internetMapEnabled
# argument to Docker. B02 also provides the DNS infrastructure needed here.
from examples.internet.B02_mini_internet_with_dns.mini_internet_with_dns import build_emulator


def build_world():
    """Create H23 networking and DNS before rendering, allowing extra services."""
    emu = build_emulator()
    emu.getLayer('DomainNameService').getZone('com.').addRecord('minecraft A 10.170.0.10')
    # B02 has no Internet egress. Minecraft downloads its server at first start,
    # so advertise external routes through one real-world router.
    outside = emu.getLayer('Base').createAutonomousSystem(99999)
    outside.createRealWorldRouter(
        'internet-egress', prefixes=['0.0.0.0/1', '128.0.0.0/1']
    ).joinNetwork('ix100', '10.100.0.99')
    emu.getLayer('Ebgp').addPrivatePeerings(100, [3], [99999], PeerRelationship.Provider)
    return emu


def create_minecraft(emu, *, host_port=25565, volume='minecraft-example-data'):
    """Use the same server configuration in H23 and derived experiments."""
    return MinecraftBundle(
        # Keep Docker's DNS for public download domains; B02 serves simulated DNS.
        emu, image='itzg/minecraft-server:java25',
        host_port=host_port, volume=volume,
        environment={
            'EULA': 'TRUE', 'TYPE': 'VANILLA', 'VERSION': '26.1',
            'MEMORY': '2G', 'ONLINE_MODE': 'FALSE', 'SERVER_PORT': '25565',
            'ENABLE_RCON': 'true', 'MOTD': 'EmuVista Minecraft',
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--host-port', type=int, default=25565)
    args = parser.parse_args()
    if not 1 <= args.host_port <= 65535:
        parser.error('host-port must be between 1 and 65535')

    emu = build_world()
    emu.render()
    minecraft = create_minecraft(emu, host_port=args.host_port)
    minecraft.addInternalNetwork('170', 'net0', ['10.170.0.10'], '10.170.0.254')
    compiler = Docker(platform=Platform.AMD64)
    minecraft.registerVolumes(compiler)
    compiler.addContainerBundle(minecraft)
    internet_map = InternetMap(emu)
    internet_map.setPorts([8081, 8080, 8082])
    compiler.addContainerBundle(internet_map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(compiler, str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
