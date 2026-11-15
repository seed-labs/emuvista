#!/usr/bin/env python3
"""Read the compiled world, wait for infrastructure, then start residents."""

import argparse
import json
from pathlib import Path
import subprocess
import time

import yaml

HERE = Path(__file__).resolve().parent
AGENT_LABEL = 'org.seedsecuritylabs.seedemu.meta.org.emuvista.agent.'

PREPARE_DATA = '''import json
import os
import pathlib
import shutil
import sys

reset, agents = json.loads(sys.argv[1])
for name in reset:
    directory = pathlib.Path(name)
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
for name in agents:
    os.chown(name, 10001, 10001)
    os.chmod(name, 0o700)
'''


class Startup:
    def __init__(self, output, timeout=900):
        self.output = Path(output).resolve()
        self.timeout = timeout
        self.compose_files = ['docker-compose.yml']
        self.configuration = json.loads(self.compose('config', '--format', 'json'))
        services = self.configuration['services']
        self.agents = [name for name, service in services.items()
                       if AGENT_LABEL + 'id' in service.get('labels', {})]
        if not self.agents:
            raise RuntimeError(
                'No compiled agents found. Run python3 virtual_world_with_agents.py first.')
        self.initializers = {name for name, service in services.items()
                             if service.get('labels', {}).get('org.emuvista.component') == 'initialize'}
        self.infrastructure = [name for name, service in services.items()
                               if name not in self.agents
                               and not service.get('build', {}).get('dockerfile', '').startswith('dummies/')]

        deployments = [json.loads(path.read_text())
                       for path in self.output.glob('*/deployment.json')]
        roots = {Path(item['state_path']).resolve(): item['persistent'] for item in deployments}
        self.runtime_data = {}
        for service in services.values():
            for volume in service.get('volumes', []):
                if volume['type'] == 'bind' and not volume.get('read_only'):
                    source = Path(volume['source']).resolve()
                    if source.parent in roots:
                        self.runtime_data[source] = roots[source.parent]

        state = next(
            (Path(item['state_path']).parent for item in deployments if item['persistent']), None)
        self.agent_state = []
        self.state_mounts = {}
        if state:
            for name in self.agents:
                labels = services[name]['labels']
                source = state / 'agents' / labels[AGENT_LABEL + 'id']
                self.agent_state.append(source)
                self.state_mounts[name] = {'volumes': [{
                    'type': 'bind', 'source': str(source),
                    'target': labels[AGENT_LABEL + 'state-directory'],
                    'bind': {'create_host_path': False},
                }]}

    def compose(self, *arguments, timeout=120):
        files = [argument for path in self.compose_files for argument in ('-f', path)]
        result = subprocess.run(['docker', 'compose', *files, *arguments], cwd=self.output,
                                text=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1200:] or 'Docker Compose failed')
        return result.stdout

    def status(self):
        rows = [json.loads(line) for line in self.compose(
            'ps', '--all', '--format', '{{json .}}').splitlines()]
        return {row['Service']: row for row in rows}

    def prepare_data(self, reset=False):
        reset_paths = [path for path, persistent in self.runtime_data.items()
                       if reset and not persistent]
        paths = list(dict.fromkeys(reset_paths + self.agent_state))
        if not paths:
            return
        for path in paths:
            if path.is_symlink():
                raise RuntimeError('Runtime data cannot be a symbolic link')
            path.mkdir(parents=True, exist_ok=True, mode=0o755)
        if self.state_mounts:
            override = 'docker-compose.agents.yml'
            (self.output /
             override).write_text(yaml.safe_dump({'services': self.state_mounts}, sort_keys=False))
            self.compose_files.append(override)

        name = self.agents[0]
        image = self.configuration['services'][name].get(
            'image') or self.configuration['name'] + '-' + name
        command = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--user', '0:0',
                   '--entrypoint', 'python3']
        targets = {path: '/runtime/' + str(index) for index, path in enumerate(paths)}
        for path, target in targets.items():
            command.extend(['--mount', 'type=bind,source=' + str(path) + ',target=' + target])
        payload = [[targets[path] for path in reset_paths],
                   [targets[path] for path in self.agent_state]]
        command.extend([image, '-c', PREPARE_DATA, json.dumps(payload)])
        result = subprocess.run(command, cwd=self.output, text=True, capture_output=True,
                                timeout=self.timeout, stdin=subprocess.DEVNULL)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1200:] or 'Runtime data preparation failed')
        if reset_paths:
            print('Starting a fresh world: temporary application data cleared; initial configuration retained.', flush=True)
        elif self.agent_state:
            print('Using saved application data and resident memory.', flush=True)

    def pending(self, rows):
        pending = []
        for name in self.infrastructure:
            row = rows.get(name, {})
            state = row.get('State', 'not_created')
            if name in self.initializers:
                if state == 'exited':
                    if row.get('ExitCode') != 0:
                        raise RuntimeError(
                            name + ' failed; inspect its Compose logs before starting residents')
                else:
                    pending.append(name)
            elif state != 'running' or row.get('Health', '') not in ('', 'healthy'):
                if state in ('exited', 'dead'):
                    raise RuntimeError(
                        name + ' stopped; inspect its Compose logs before starting residents')
                pending.append(name)
        return pending

    def wait(self):
        deadline = time.monotonic() + self.timeout
        while True:
            pending = self.pending(self.status())
            if not pending:
                print('Infrastructure ready: initializers completed and services healthy.', flush=True)
                return
            message = 'Waiting for infrastructure: ' + ', '.join(pending)
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    'Infrastructure readiness timed out. No residents were started. ' + message)
            print(message, flush=True)
            time.sleep(min(5, max(0, deadline - time.monotonic())))

    def run(self, infrastructure_only=False, agents_only=False):
        rows = self.status()
        active = [name for name in self.agents if rows.get(name, {}).get('State') == 'running']
        if active:
            raise RuntimeError('Residents are already running. Use docker compose down before starting the world again: '
                               + ', '.join(active))
        self.prepare_data(reset=not agents_only and not rows)
        if not agents_only:
            print('Starting infrastructure; resident containers remain stopped.', flush=True)
            self.compose('up', '-d', '--no-build', '--pull', 'never',
                         *self.infrastructure, timeout=self.timeout)
        self.wait()
        if not infrastructure_only:
            print('Starting residents after successful readiness checks.', flush=True)
            self.compose('up', '-d', '--no-build', '--pull', 'never',
                         '--no-deps', *self.agents, timeout=120)
        else:
            print('Residents remain stopped. Start them with: python3 start.py --agents-only', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--timeout', type=int, default=900)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--infrastructure-only', action='store_true')
    group.add_argument('--agents-only', action='store_true')
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error('timeout must be positive')
    try:
        Startup(args.output, args.timeout).run(args.infrastructure_only, args.agents_only)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
