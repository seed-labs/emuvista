#!/usr/bin/env python3
"""Run compile/build/up smoke tests in a disposable copy of the repository."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def examples():
    manifests = {}
    for category, prefix in (('examples', 'H'), ('experiments', 'E')):
        for directory in sorted((ROOT / category).glob(prefix + '[0-9][0-9]*')):
            if not directory.is_dir():
                continue
            manifest = directory / 'example.yaml'
            if not manifest.is_file():
                raise ValueError('Missing compile test manifest: ' + str(manifest.relative_to(ROOT)))
            code = directory.name.split('_', 1)[0]
            if code in manifests:
                raise ValueError('Duplicate example code: ' + code)
            manifests[code] = manifest.relative_to(ROOT)
    return manifests


def stage_source(destination):
    """Copy versioned and unignored source, excluding local credentials and state."""
    files = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    for item in files.decode().split('\0'):
        if not item:
            continue
        relative = Path(item)
        if (relative.name in ('.env', 'model_profiles.json')
                or (relative.name.startswith('.env.') and relative.name != '.env.example')
                or any(part in ('.runtime', '.git', '.aws', '.codex', '.agents',
                                'ci-artifacts', '__pycache__')
                       for part in relative.parts)):
            continue
        source = ROOT / relative
        if not source.is_file() or not source.resolve().is_relative_to(ROOT):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # Compilation and container startup use dummy settings, never the user's API key.
    environment = destination / 'experiments/E99_virtual_world_with_agents/.env'
    environment.parent.mkdir(parents=True, exist_ok=True)
    environment.write_text('LLM_API_KEY=ci-placeholder\nLLM_MODEL=ci-placeholder\n'
                           'LLM_BASE_URL=http://192.0.2.10:8000/v1\nAGENT_MAX_CYCLES=1\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('list', 'compile', 'build', 'all'))
    parser.add_argument('example', nargs='?', default='all', help='Example code, such as H00, H12, or all')
    parser.add_argument('--artifact-dir', type=Path, default=ROOT / 'ci-artifacts')
    parser.add_argument('--json', action='store_true', help='Print a JSON example list for CI')
    args = parser.parse_args()
    try:
        manifests = examples()
    except ValueError as error:
        parser.error(str(error))
    if args.example != 'all':
        if args.example not in manifests:
            parser.error('Unknown example: ' + args.example)
        manifests = {args.example: manifests[args.example]}
    if args.command == 'list':
        print(json.dumps(list(manifests)) if args.json else '\n'.join(manifests))
        return 0

    from ci.runner import ExampleRunner
    work_root = ROOT / '.runtime' / 'ci'
    work_root.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, manifest in manifests.items():
        directory = Path(tempfile.mkdtemp(prefix=name + '-', dir=work_root))
        workspace = directory / 'emuvista'
        artifacts = args.artifact_dir.resolve() / name
        try:
            import seedemu
            # Legacy examples import templates from a sibling SeedEmu checkout.
            (directory / 'seed-emulator').symlink_to(Path(seedemu.__file__).resolve().parents[1],
                                                    target_is_directory=True)
            stage_source(workspace)
            runner = ExampleRunner(workspace / manifest, artifacts,
                                   'emuvista-ci-' + name.lower() + '-' + uuid.uuid4().hex[:8])
            results[name] = runner.smoke('up' if args.command == 'all' else args.command)
        except Exception as error:
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / 'result.json').write_text(json.dumps({'error': str(error), 'exit_code': 1}) + '\n')
            results[name] = 1
            print('{}: {}'.format(name, error), file=sys.stderr)
        print('{}: {} ({})'.format(name, 'FAIL' if results[name] else 'PASS', artifacts), flush=True)
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    (args.artifact_dir / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(results.values()))


if __name__ == '__main__':
    raise SystemExit(main())
