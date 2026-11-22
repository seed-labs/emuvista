#!/usr/bin/env python3
"""Build generated company images one service at a time."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def build_service(name, service, output, project, environment, no_cache=False):
    build = service['build']
    context = Path(build['context'])
    dockerfile = context / build.get('dockerfile', 'Dockerfile')
    source = dockerfile.read_text()
    lines = source.splitlines(keepends=True)
    proxy_download = environment.get('HTTPS_PROXY') and any(
        line.startswith('RUN ') and 'https://github.com/' in line for line in lines)
    options = ['--no-cache'] if no_cache else []

    if proxy_download:
        # Keep the proxy scoped to downloads that need it. Other steps retain
        # their original network and build cache.
        prefix = ('RUN --network=host '
                  '--mount=type=secret,id=build_https_proxy,env=HTTPS_PROXY '
                  '--mount=type=secret,id=build_https_proxy,env=https_proxy ')
        source = ''.join(
            line.replace('RUN ', prefix, 1)
            if line.startswith('RUN ') and 'https://github.com/' in line else line
            for line in lines)
        with TemporaryDirectory(prefix='emuvista-company-build-') as temporary:
            staged = Path(temporary) / 'Dockerfile'
            staged.write_text(source)
            command = ['docker', 'build', '--progress=plain', '--allow', 'network.host',
                       '--secret', 'id=build_https_proxy,env=HTTPS_PROXY',
                       '-f', str(staged), '-t', service.get('image', f'{project}-{name}'),
                       *options, str(context)]
            subprocess.run(command, cwd=output, env=environment, check=True)
    else:
        subprocess.run(['docker', 'compose', '--progress', 'plain', 'build', *options, name],
                       cwd=output, env=environment, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    environment = dict(os.environ, DOCKER_BUILDKIT='1')
    proxy = environment.get('HTTPS_PROXY') or environment.get('https_proxy')
    if proxy:
        environment['HTTPS_PROXY'] = proxy
    configuration = json.loads(subprocess.check_output(
        ['docker', 'compose', 'config', '--format', 'json'],
        cwd=output, env=environment, text=True))
    services = {name: service for name, service in configuration['services'].items()
                if service.get('build')}
    # SeedEmu's generated node images refer to these local base images in FROM.
    ordered = sorted(
        services,
        key=lambda name: not services[name]['build'].get('dockerfile', '').startswith('dummies/'),
    )
    for index, name in enumerate(ordered, 1):
        print(f'Building {index}/{len(ordered)}: {name}', flush=True)
        build_service(name, services[name], output, configuration['name'],
                      environment, args.no_cache)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
