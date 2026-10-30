#!/usr/bin/env python3
"""Add a browser and agent using A11's custom container API."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
H12 = HERE.parent / 'H12_domain_name_purchase'
sys.path.insert(0, str(H12))
from domain_name_purchase import build_emulator
from container.prepare_context import prepare_context
from seedemu.compiler import Docker, Platform


# Match the indentation of other Compose services.
DOCKER_COMPOSE_ENTRY = """\
    {name}:
        build: ./browser-agent
        init: true
        cap_add: [NET_ADMIN]
        shm_size: 1gb
        volumes:
            - type: bind
              source: {profile_directory}
              target: /opt/agent-config
            - type: bind
              source: {egress_file}
              target: /opt/network-config/egress_urls.txt
              read_only: true
        extra_hosts:
            - "host.docker.internal:host-gateway"
"""


def run(dumpfile=None):
    """Follow A11 to build the environment, then dump or render it."""
    if dumpfile is None:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--output', type=Path, default=HERE / 'output')
        parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')

        args = parser.parse_args()
        output = args.output.resolve()
        platform = Platform.AMD64 if args.platform == 'amd' else Platform.ARM64

    try:
        emu = build_emulator()
        if dumpfile is not None:
            emu.dump(dumpfile)
            return 0

        source = HERE / 'agent'
        if not (source / 'agent_web.py').is_file():
            raise RuntimeError(f'Missing agent source: {source}')
        emu.render()
        docker = Docker(platform=platform)
        gateway = emu.getDefaultRouterByAsnAndNetwork(154, 'net0')
        docker.attachCustomContainer(
            compose_entry=DOCKER_COMPOSE_ENTRY.format(
                name='browser-agent',
                profile_directory=json.dumps(str(source.resolve())),
                egress_file=json.dumps(str(HERE / 'egress_urls.txt')),
            ),
            asn=154, net='net0', ip_address='10.154.0.80',
            port_forwarding='127.0.0.1:18089:8089/tcp',
            env=[f'SIM_GATEWAY={gateway}'],
            node_name='browser-agent', show_on_map=True,
        )
        emu.compile(docker, str(output), override=True)
        prepare_context(output)
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
