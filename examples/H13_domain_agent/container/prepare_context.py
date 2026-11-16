"""Stage the chat agent and service-owned tools without copying browser code or secrets."""
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def prepare_context(output):
    from bundles.DomainRegistrarBundle import DomainRegistrarBundle

    source = HERE.parent / 'agent'
    context = Path(output) / 'domain-agent'
    context.mkdir()
    for name in ('Dockerfile', 'start.sh'):
        shutil.copyfile(HERE / name, context / name)
    shutil.copyfile(HERE.parent / 'egress_urls.txt', context / 'egress_urls.txt')
    target = context / 'agent'
    target.mkdir()
    for name in ('requirements.txt', 'agent_web.py', 'domain_agent.py', 'bundle_tools.py',
                 'agent_web.html', 'agent_web.js'):
        shutil.copyfile(source / name, target / name)
    exported = DomainRegistrarBundle.getAgentTools()
    packages = {exported['name']: exported['source']}
    allowed = []
    for name, path in packages.items():
        path = Path(path)
        shutil.copytree(path, context / 'packages' / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        allowed.extend(item['name'] for item in json.loads((path / 'tools.json').read_text()))
    config = {
        'packages': list(packages), 'allowed_tools': allowed,
        'accounts': {'domain_purchase': {
            'registrar_url': 'http://10.150.0.10:8080',
            'payment_url': 'http://10.160.0.71:8080',
            'email': 'user@example.com', 'password': 'Aa123456',
            'currency': 'USD', 'tlds': ['com', 'net'],
            'state_dir': '/var/lib/domain-agent/purchases',
        }},
    }
    (context / 'tool-config.json').write_text(json.dumps(config, indent=2) + '\n')
    (context / 'tool-config.json').chmod(0o600)
