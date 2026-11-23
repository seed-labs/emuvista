#!/usr/bin/env python3
"""Deploy Mastodon's development version on the mini Internet using SocialNetworkBundle."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.containerBundle import InternetMap
from bundles.SocialNetworkBundle import SocialNetworkBundle
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator, host_zone

ASN = 162


def add_social_records(emu, hostname, address=f'10.{ASN}.0.10'):
    """Add the application record to H00's existing DNS infrastructure."""
    host_zone(emu, hostname).addRecord('@ A ' + address)


def build_image(image):
    """Build the Mastodon development image from the local checkout if it is missing."""
    if subprocess.run(['docker', 'image', 'inspect', image], capture_output=True).returncode == 0:
        return
    source = Path(os.environ.get('MASTODON_SOURCE', ROOT.parent / 'mastodon')).expanduser().resolve()
    devcontainer = source / '.devcontainer' / 'Dockerfile'
    if not devcontainer.is_file():
        raise RuntimeError(f'{image} is missing and {source} has no .devcontainer; set MASTODON_SOURCE')
    # The Mastodon image uses BuildKit features (named contexts, cache mounts).
    env = dict(os.environ, MASTODON_SOURCE=str(source), DOCKER_BUILDKIT='1')
    base = re.search(r'^\s*FROM\s+(?:--\S+\s+)*(\S+)', devcontainer.read_text(), re.M | re.I)
    if base:
        env.setdefault('MASTODON_DEVCONTAINER_IMAGE', base.group(1))
    print(f'Building {image} from {source}; the first build takes a while.', flush=True)
    subprocess.run(['docker', 'compose', '-f', str(ROOT / 'docker_images/social/compose.yml'), 'build'],
                   env=env, check=True)


def services(output):
    """Return Compose service states, accepting either JSON output style."""
    text = subprocess.run(['docker', 'compose', 'ps', '--all', '--format', 'json'], cwd=output,
                          capture_output=True, text=True, check=True).stdout.strip()
    try:
        rows = json.loads(text) if text else []
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {row['Service']: row for row in (rows if isinstance(rows, list) else [rows])}


def start(output, bundle, timeout):
    """Build and start the emulation, then wait for the accounts and the gateway."""
    build_image(bundle.getImages()['web'])
    # SEED's node images start FROM local images built by its dummy services. Compose's
    # default BuildKit builder builds everything at once, so use the legacy builder (as in H23).
    subprocess.run(['docker', 'compose', 'build'], cwd=output, env=dict(os.environ, DOCKER_BUILDKIT='0'),
                   check=True)
    subprocess.run(['docker', 'compose', 'up', '-d'], cwd=output, check=True)
    initializer = bundle.getContainer('initialize').getHostname()
    gateway = bundle.getContainer('gateway').getHostname()
    deadline, failed, reported = time.monotonic() + timeout, None, None
    while True:
        rows = services(output)
        init, front = rows.get(initializer, {}), rows.get(gateway, {})
        initialized = init.get('State') == 'exited' and init.get('ExitCode') == 0
        if initialized and front.get('Health') == 'healthy':
            return
        if init.get('State') == 'exited' and not initialized:
            # The initializer restarts up to three times before it stays stopped.
            failed = failed or time.monotonic()
            if time.monotonic() - failed > 60:
                raise RuntimeError(f'{initializer} failed; inspect: docker compose logs {initializer}')
        else:
            failed = None
        status = (f'{initializer} {init.get("State", "created")}, '
                  f'{gateway} {front.get("Health") or front.get("State", "created")}')
        if status != reported:
            print('Waiting for Mastodon:', status, flush=True)
            reported = status
        if time.monotonic() > deadline:
            raise RuntimeError('Mastodon was not ready in time; inspect docker compose ps and logs')
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('accounts.json'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--state', type=Path, help='Save and resume accounts, posts and media')
    parser.add_argument('--host-port', type=int, default=8450)
    parser.add_argument('--start', action='store_true',
                        help='Build and start the emulation, then wait until the accounts are ready')
    parser.add_argument('--timeout', type=int, default=1800,
                        help='Seconds --start waits for Mastodon after starting it (default: 1800)')
    args = parser.parse_args()
    output = args.output.resolve()
    if args.state and (args.state.resolve() == output or output in args.state.resolve().parents):
        parser.error('social network state must be outside output')
    emu = build_emulator()
    configuration = json.loads(args.config.read_text())
    bundle = SocialNetworkBundle(emu, resolver=DNS_RESOLVER)
    bundle.setHostname(configuration['hostname'])
    bundle.setInitialConfiguration(configuration)
    add_social_records(emu, configuration['hostname'])
    emu.render()
    bundle.addInternalNetwork(str(ASN), 'net0',
                              [f'10.{ASN}.0.{i}' for i in range(10, 10 + len(bundle.getContainers()))],
                              f'10.{ASN}.0.254')
    bundle.enableHostAccess(args.host_port)
    if args.state:
        bundle.setSavePath(args.state)
    compiler = Docker(platform=Platform.AMD64)
    internet_map = InternetMap(emu)
    internet_map.setPorts([8083, 8080, 8084])
    compiler.addContainerBundle(internet_map)
    compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(output), override=True)
    if args.start:
        try:
            start(output, bundle, args.timeout)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            parser.exit(1, f'{error}\n')
        admin = bundle.getAdminCredentials()
        print(f'Mastodon is ready at http://localhost:{args.host_port} (emulated clients: {bundle.getURL()}).')
        print(f'Sign in as {admin["email"]} / {admin["password"]}, or with an account from {args.config.name}.')


if __name__ == '__main__':
    main()
