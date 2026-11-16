#!/usr/bin/env python3
"""Add an interactive domain agent using Bundle-owned tools."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
H12 = HERE.parent / 'H12_domain_name_purchase'
sys.path.insert(0, str(H12))
from domain_name_purchase import build_scenario, configure_bundles
from shutil import copytree
from container.prepare_context import prepare_context
from seedemu.compiler import Docker, Platform


# Match the indentation of other Compose services.
DOCKER_COMPOSE_ENTRY = """\
    {name}:
        build: ./domain-agent
        init: true
        cap_add: [NET_ADMIN]
        volumes:
            - type: bind
              source: {profile_directory}
              target: /opt/agent-config
            - type: bind
              source: {egress_file}
              target: /opt/network-config/egress_urls.txt
              read_only: true
            - h13-domain-purchases:/var/lib/domain-agent/purchases
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
        emu, bundles = build_scenario()
        if dumpfile is not None:
            raise RuntimeError('Bundle scenarios require Docker compilation; use --output instead of dumpfile')

        source = HERE / 'agent'
        if not (source / 'agent_web.py').is_file():
            raise RuntimeError(f'Missing agent source: {source}')
        emu.render()
        docker = Docker(platform=platform)
        configure_bundles(emu, bundles, docker)
        gateway = emu.getDefaultRouterByAsnAndNetwork(154, 'net0')
        docker.attachCustomContainer(
            compose_entry=DOCKER_COMPOSE_ENTRY.format(
                name='domain-agent',
                profile_directory=json.dumps(str(source.resolve())),
                egress_file=json.dumps(str(HERE / 'egress_urls.txt')),
            ),
            asn=154, net='net0', ip_address='10.154.0.80',
            port_forwarding='127.0.0.1:18089:8089/tcp',
            env=[f'SIM_GATEWAY={gateway}'],
            node_name='domain-agent', show_on_map=True,
        )
        emu.compile(docker, str(output), override=True)
        for directory in ('namingo', 'fossbilling'):
            copytree(HERE.parents[1] / 'docker_images' / directory,
                     output / 'application-images' / directory)
        prepare_context(output)
        import yaml
        compose_path = output / 'docker-compose.yml'
        compose = yaml.safe_load(compose_path.read_text())
        compose.setdefault('volumes', {})['h13-domain-purchases'] = {}
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False))
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
