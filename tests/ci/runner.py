"""Emuvista smoke tests built on SeedEmu's manifest runner."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import yaml

from seedemu.testing import InternetTestRunner


class ExampleRunner(InternetTestRunner):
    def __init__(self, manifest, artifact_dir, project):
        super().__init__(manifest, artifact_dir)
        self.project = project
        self.source = next(parent for parent in self.emulation_dir.parents
                           if (parent / 'docker_images').is_dir())

    def docker_env(self):
        environment = dict(os.environ)
        environment.pop('COMPOSE_FILE', None)
        environment.pop('COMPOSE_PROFILES', None)
        environment.update(COMPOSE_PROJECT_NAME=self.project, COMPOSE_PARALLEL_LIMIT='1',
                           COMPOSE_BAKE='false')
        environment.setdefault('DOCKER_BUILDKIT', '1')
        return environment

    def run_command(self, name, cmd, *, cwd, env=None, timeout=None):
        """Stream long builds to disk and retain partial logs after a timeout."""
        if not name.startswith('build-'):
            try:
                return super().run_command(name, cmd, cwd=cwd, env=env, timeout=timeout)
            except subprocess.TimeoutExpired as error:
                def decode(value):
                    return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
                result = subprocess.CompletedProcess(
                    cmd, 124, decode(error.stdout),
                    decode(error.stderr) + '\nTIMEOUT: {} seconds\n'.format(timeout))
                self.write_command_log(name, cmd, cwd, result)
                return result
        log = self.artifact_dir / 'logs' / (self.slug(name) + '.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        self.log('{}: {} (log: {})'.format(name, shlex.join(cmd), log))
        with log.open('w') as output:
            output.write('COMMAND: {}\nCWD: {}\n\n'.format(shlex.join(cmd), cwd))
            output.flush()
            try:
                result = subprocess.run(cmd, cwd=cwd, env=env, text=True,
                                        stdout=output, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, timeout=timeout, check=False)
                status = result.returncode
            except subprocess.TimeoutExpired:
                status = 124
                output.write('\nTIMEOUT: {} seconds\n'.format(timeout))
            output.write('\nEXIT: {}\n'.format(status))
        return subprocess.CompletedProcess(cmd, status, '', '')

    def compose(self, name, *arguments, timeout=120):
        compose = self.compose_file()
        return self.run_command(name, ['docker', 'compose', '-f', str(compose), *arguments],
                                cwd=compose.parent, env=self.docker_env(), timeout=timeout)

    def configuration(self):
        result = self.compose('compose-config', 'config', '--format', 'json')
        if result.returncode:
            raise RuntimeError('Invalid Compose configuration; see compose-config.log')
        return json.loads(result.stdout)

    def build(self):
        configuration = self.configuration()
        timeout = int(self.manifest.get('build', {}).get('timeout', 3600))
        for group in self.manifest.get('build', {}).get('images', []):
            manifest = self.source / 'docker_images' / group / 'compose.yml'
            services = yaml.safe_load(manifest.read_text())['services']
            for name in services:
                result = self.run_command(
                    'build-{}-{}'.format(group, name),
                    ['docker', 'compose', '-f', str(manifest), 'build', name],
                    cwd=manifest.parent, env=self.docker_env(), timeout=timeout)
                if result.returncode:
                    return result.returncode
        for index, command in enumerate(self.manifest.get('build', {}).get('commands', [])):
            result = self.run_command('build-prepare-{}'.format(index), command,
                                      cwd=self.source, env=self.docker_env(), timeout=timeout)
            if result.returncode:
                return result.returncode
        # Generated node Dockerfiles use the local dummies as base images.
        services = configuration['services']
        names = [name for name, service in services.items() if service.get('build')]
        names.sort(key=lambda name: not self.is_dummy(services[name]))
        for name in names:
            result = self.compose('build-' + name, 'build', name, timeout=timeout)
            if result.returncode:
                return result.returncode
        return 0

    @staticmethod
    def is_dummy(service):
        build = service.get('build', {})
        return isinstance(build, dict) and build.get('dockerfile', '').startswith('dummies/')

    @classmethod
    def pending(cls, services, rows):
        """Only declared one-shot jobs may exit successfully."""
        initializers = {name for name, service in services.items()
                        if service.get('labels', {}).get('org.emuvista.component') == 'initialize'}
        for service in services.values():
            dependencies = service.get('depends_on', {})
            if isinstance(dependencies, dict):
                initializers.update(name for name, dependency in dependencies.items()
                                    if dependency.get('condition') == 'service_completed_successfully')
        pending = []
        for name, service in services.items():
            if cls.is_dummy(service):
                continue
            row = rows.get(name, {})
            state = row.get('State', 'missing')
            if name in initializers:
                if state == 'exited':
                    if row.get('ExitCode') != 0:
                        raise RuntimeError('{} initialization failed: {}'.format(name, row))
                    continue
            elif state == 'running' and row.get('Health', '') in ('', 'healthy'):
                continue
            elif state in ('exited', 'dead'):
                raise RuntimeError('{} stopped unexpectedly: {}'.format(name, row))
            pending.append('{}: {} {}'.format(name, state, row.get('Health', '')))
        return pending

    def up(self):
        timeout = int(self.manifest.get('runtime', {}).get('timeout', 900))
        startup = self.manifest.get('runtime', {}).get('startup')
        if startup:
            import sys
            result = self.run_command(
                'up', [sys.executable, startup, '--output', str(self.compose_file().parent),
                       '--timeout', str(timeout)],
                cwd=self.emulation_dir, env=self.docker_env(), timeout=timeout + 120)
        else:
            result = self.compose('up', 'up', '-d', '--no-build', timeout=timeout)
        return result.returncode or self.readiness()

    def readiness(self):
        services = self.configuration()['services']
        settings = self.manifest.get('runtime', {})
        deadline = time.monotonic() + int(settings.get('timeout', 900))
        stable_since = None
        while time.monotonic() < deadline:
            result = self.compose('runtime-status', 'ps', '--all', '--format', 'json')
            if result.returncode:
                return result.returncode
            rows = {row['Service']: row for row in self.parse_compose_ps_output(result.stdout)}
            pending = self.pending(services, rows)
            self.write_json('runtime-status.json', {'containers': rows, 'pending': pending})
            if pending:
                stable_since = None
            else:
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= int(settings.get('stability', 10)):
                    return 0
            time.sleep(2)
        raise RuntimeError('Startup timed out; see runtime-status.json and runtime-logs.log')

    def down(self):
        for name, arguments in (
            ('runtime-ps', ['ps', '--all', '--format', 'json']),
            ('runtime-logs', ['logs', '--no-color', '--timestamps', '--tail', '200']),
        ):
            try:
                self.compose(name, *arguments, timeout=60)
            except Exception as error:
                self.log('Could not collect {}: {}'.format(name, error))
        return self.compose('down', 'down', '--volumes', '--remove-orphans',
                            '--timeout', '20', timeout=180).returncode

    def smoke(self, stage):
        """Compile failure never triggers Docker cleanup of an old deployment."""
        results = {}
        started = False
        try:
            for name in ('compile', 'build', 'up'):
                started = name == 'up'
                before = time.monotonic()
                status = getattr(self, name)()
                results[name] = {'exit_code': status, 'seconds': round(time.monotonic() - before, 2)}
                if status or name == stage:
                    break
        except Exception as error:
            results[name] = {'exit_code': 1, 'error': str(error)}
            self.log(str(error))
        finally:
            if started:
                try:
                    results['down'] = {'exit_code': self.down()}
                except Exception as error:
                    results['down'] = {'exit_code': 1, 'error': str(error)}
            self.write_json('result.json', {'id': self.emulation_id(), 'project': self.project,
                                           'workspace': str(self.source), 'stages': results})
        return int(any(result['exit_code'] != 0 for result in results.values()))
