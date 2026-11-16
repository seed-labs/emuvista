"""Generate standalone Mastodon Compose artifacts without SEED network routing."""
import json
from pathlib import Path
import re
import shlex
import shutil

from seedemu.core import Node
from seedemu.core.enums import NodeRole


def generate_mastodon_compose(server, output, *, token_volumes, site_title='Mastodon',
                              bootstrap_email_domains=(),
                              image='handsonsecurity/emuvista-mastodon:1.0',
                              readiness_file='/run/mastodon-bundle.ready'):
    """Return a Compose service and write its config and image build context.

    The caller owns accounts, network/domain choice, and top-level named-volume
    declarations. token_volumes maps configured token-export usernames to volumes.
    This standalone deployment uses HTTP; the SEED bundle also supports HTTPS.
    """
    output = Path(output)
    if server._scheme != 'http':
        raise ValueError('Standalone Mastodon Compose currently requires HTTP')
    exports = {entry['username']: entry['path'] for entry in server._token_exports}
    for name, volume in token_volumes.items():
        if name not in exports:
            raise ValueError(f'Configure exportToken before sharing credentials for {name}')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', volume):
            raise ValueError('Invalid Compose volume name')
    for path in (output / 'mastodon-config', output / 'application-images',
                 output / 'application-images/mastodon'):
        if path.is_symlink():
            raise ValueError('Generated Mastodon directories must not be symlinks')
    port, domain = server._port, server._domain
    node = Node('mastodon', NodeRole.Host, 0)
    server.install(node)
    root = output / 'mastodon-config'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, mode=0o700)
    for file in node.getFiles():
        target, content = file.get()
        if not target.endswith('/install.sh'):
            if target.endswith('/initialize.rb'):
                # Limit the email allowlist to the account bootstrap Rails process.
                content = (
                    "require 'json'\n"
                    "bootstrap = JSON.parse(File.read('/opt/mastodon-service/bootstrap.json'))\n"
                    "Rails.configuration.x.email_domains_allowlist = "
                    "Array(Rails.configuration.x.email_domains_allowlist) | bootstrap.fetch('email_domains')\n"
                    + content
                )
                content = content.replace("Setting.site_title = 'H16 Mastodon'",
                                          "Setting.site_title = bootstrap.fetch('site_title')")
            path = root / Path(target).name
            path.write_text(content)
            path.chmod(0o600)
    (root / 'bootstrap.json').write_text(json.dumps({
        'site_title': site_title, 'email_domains': list(bootstrap_email_domains),
    }) + '\n')
    (root / 'bootstrap.json').chmod(0o600)
    commands = ['#!/bin/bash', 'set -euo pipefail',
                f'rm -f {shlex.quote(readiness_file)}',
                'cp /bundle-config/* /opt/mastodon-service/',
                'chmod 644 /opt/mastodon-service/*',
                'chmod 755 /opt/mastodon-service/run.sh',
                'bash /opt/mastodon-service/start.sh']
    for name in token_volumes:
        commands += [f'install -d -m 700 -o 10001 -g 10001 /run/agent-credentials/{name}',
                     f'install -m 600 -o 10001 -g 10001 {shlex.quote(exports[name])} '
                     f'/run/agent-credentials/{name}/credentials.json']
    commands += [f'touch {shlex.quote(readiness_file)}', 'exec sleep infinity']
    (root / 'launch.sh').write_text('\n'.join(commands) + '\n')
    image_context = output / 'application-images/mastodon'
    if image_context.exists():
        shutil.rmtree(image_context)
    shutil.copytree(Path(__file__).resolve().parents[2] / 'docker_images/mastodon', image_context)
    return {
        'image': image,
        'build': './application-images/mastodon',
        'entrypoint': ['bash', '/bundle-config/launch.sh'],
        'ports': [f'127.0.0.1:{port}:{port}'],
        'networks': {'default': {'aliases': [domain]}},
        'volumes': ['./mastodon-config:/bundle-config:ro',
                    'mastodon-postgresql:/var/lib/postgresql', 'mastodon-redis:/var/lib/redis',
                    'mastodon-data:/var/lib/mastodon', 'mastodon-media:/opt/mastodon/public/system',
                    *(f'{volume}:/run/agent-credentials/{name}' for name, volume in token_volumes.items())],
        'healthcheck': {'test': ['CMD-SHELL',
            f'test -f {shlex.quote(readiness_file)} && curl -fsS --max-time 5 '
            f'--resolve {domain}:{port}:127.0.0.1 '
            f'http://{domain}:{port}/api/v2/instance >/dev/null'],
            'interval': '10s', 'timeout': '8s', 'retries': 60, 'start_period': '180s'},
    }

