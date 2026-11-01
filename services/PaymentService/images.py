"""Inspect or transport the prebuilt images used by PaymentService.

Run from the repository root: python3 -m services.PaymentService.images --help
"""

import argparse
import json
import subprocess
from pathlib import Path

from .PaymentService import PaymentService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, help='JSON role/image overrides, as accepted by payment.py')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='Print the effective role/image mapping')
    commands.add_parser('check', help='Check local availability and print immutable image IDs')
    save = commands.add_parser('save', help='Save all payment images to a Docker image archive')
    save.add_argument('archive', type=Path)
    load = commands.add_parser('load', help='Load an image archive, then check the required images')
    load.add_argument('archive', type=Path)
    args = parser.parse_args()
    images = PaymentService(json.loads(args.images.read_text()) if args.images else None).getImages()
    if args.command == 'list':
        print(json.dumps(images, indent=2))
        return
    if args.command == 'load':
        if not args.archive.is_file():
            parser.error(f'archive does not exist: {args.archive}')
        subprocess.run(['docker', 'image', 'load', '--input', str(args.archive)], check=True)
    unique = sorted(set(images.values()))
    inventory, missing = {}, []
    for reference in unique:
        result = subprocess.run(['docker', 'image', 'inspect', reference], text=True, capture_output=True)
        if result.returncode:
            missing.append(reference)
            # Docker's diagnostic also explains daemon permission/connectivity errors.
            print(result.stderr.strip())
        else:
            value = json.loads(result.stdout)[0]
            inventory[reference] = {'id': value['Id'], 'repo_digests': value.get('RepoDigests', [])}
    if missing:
        raise SystemExit('Required prebuilt images are unavailable: ' + ', '.join(missing))
    print(json.dumps(inventory, indent=2))
    if args.command == 'save':
        if args.archive.exists():
            parser.error(f'archive already exists: {args.archive}')
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['docker', 'image', 'save', '--output', str(args.archive), *unique], check=True)


if __name__ == '__main__':
    main()
