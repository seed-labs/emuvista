#!/usr/bin/env python3
"""Generate five Minecraft agents and Mastodon for host Minecraft Java 26.1."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / 'seed-emulator')]
from seedemu.core import Node
from seedemu.core.enums import NodeRole
from services.AgentService import AgentService, ToolPackage
from bundles.MastodonBundle import MastodonBundle, generate_mastodon_compose
from bundles.MastodonBundle.server import SocialMediaServer

AGENT_NAMES = ('alice', 'bob', 'carol', 'dave', 'eve')
# Occupational interests and temperament, not prescribed action sequences.
AGENT_PERSONAS = {
    'alice': 'You are a farmer. You are patient, observant, and warm toward your neighbors. '
             'You enjoy tending crops and keeping food on the table.',
    'bob': 'You are a lumberjack. You are practical, hearty, and fond of the outdoors. '
           'You know the value of good timber and enjoy keeping a useful wood supply.',
    'carol': 'You are a carpenter. You are sociable, inventive, and careful with your work. '
             'You enjoy turning wood into useful everyday things and making a home comfortable.',
    'dave': 'You are a construction worker. You are methodical, dependable, and quietly proud of your craft. '
            'You care about sturdy homes, convenient paths, and welcoming shared spaces.',
    'eve': 'You are a miner. You are curious, resourceful, and cautious underground. '
           'You enjoy finding stone and ores that can be put to good use back home.',
}
MASTODON_DOMAIN = 'mastodon.e16.test'
MASTODON_PORT = 18443


def generate_agent(output, env_file, name):
    if not env_file.is_file():
        raise ValueError(f'Create {env_file} from {HERE / ".env.example"} first')
    context = output / name
    if context.is_symlink() or env_file.resolve().is_relative_to(context.resolve()):
        raise ValueError('The generated agent build directory must not be a symlink or contain the environment file')
    package = ToolPackage('minecraft', HERE / 'tools/minecraft',
                          configuration={'local': {'bridge_url': 'http://127.0.0.1:8765'}})
    social = ToolPackage(**MastodonBundle.getAgentTools(), requirements=['pydantic>=2,<3'])
    agents = AgentService().addToolPackage(package).addToolPackage(social)
    agent = agents.install(name).setTools([*(t['name'] for t in package.manifest),
        'socialmedia.inbox', 'socialmedia.browse', 'socialmedia.read', 'socialmedia.post'])
    agent.setFramework('langchain')
    social_account = {
        'instance_url': f'http://{MASTODON_DOMAIN}:{MASTODON_PORT}', 'allow_http': True,
        'credential_file': '/run/socialmedia/credentials.json',
    }
    agent.setPersona({
        'id': name, 'name': name.capitalize(), 'accounts': {'socialmedia': social_account},
        'system': f'Your name is {name.capitalize()}. You are a resident of this world. '
                  f'People know you as {name.capitalize()}, and your Mastodon account is @{name}@{MASTODON_DOMAIN}. '
                  'This is where you live, meet others, and carry out your daily activities. '
                  'Speak as yourself in the first person. In incoming chat, the sender is the other speaker, '
                  'not your identity. Recognize messages addressed to your name. '
                  'Use minecraft.chat to speak to others; private thoughts are not audible to them. '
                  f'{AGENT_PERSONAS[name]} '
                  'Your occupation guides your interests, but you choose your own goals and may pursue other activities. '
                  'Your occupation does not imply that you already own supplies, buildings, or a business. '
                  'Mastodon is a community noticeboard where you can share experiences, ask for help, '
                  'and answer other people\'s questions beyond nearby conversation. '
                  'If you encounter a problem and nobody is nearby or available to help, you can post '
                  'a question on Mastodon describing what happened and what you have already tried. '
                  'You can browse others\' posts and offer useful answers when you have relevant knowledge; '
                  'distinguish firsthand experience from suggestions or uncertainty. '
                  'Use socialmedia.inbox to check replies and mentions, and socialmedia.read to read '
                  'a post and its conversation before answering. Reply with socialmedia.post using '
                  'in_reply_to_id set to the original post\'s status ID, not the notification ID. '
                  'Mastodon replies are not delivered through nearby Minecraft chat notifications; '
                  'check your inbox when you want to follow up. Avoid repeatedly posting the same '
                  'unanswered question. Publication is confirmed only by successful=true and status.id. '
                  'Be honest about your experiences, feelings, and uncertainties.',
        'task': 'Choose what to do next based on your own goals, current circumstances, and ongoing activities.',
    })
    # Reuse AgentService's installation/policy/runtime on a detached configuration
    # node. No simulated routers or application servers are needed for host MC.
    node = Node(name, NodeRole.Host, 0)
    # This standalone container does not need the SEED host's diagnostic suite.
    node.getSoftware().clear()
    agent.install(node)
    # E16 keeps its own loop; package installation and authorization use the new service.
    config = next(json.loads(file.get()[1]) for file in node.getFiles()
                  if file.get()[0] == '/etc/emuvista-agent/config.json')
    config['framework'] = {'name': 'e16_langchain',
                           'entrypoint': '/opt/emuvista-agent/adapter/main.py'}
    # This loop uses real local waits, not the new resident framework's ClockClient.
    config['clock'] = None
    node.setFile('/etc/emuvista-agent/config.json', json.dumps(config, indent=2) + '\n')
    node.importFile(str(HERE / 'adapters/langchain/adapter.py'), '/opt/emuvista-agent/adapter/adapter.py')
    node.importFile(str(HERE / 'adapters/langchain/main.py'), '/opt/emuvista-agent/adapter/main.py')
    # Replace only generated build files, removing stale sources on regeneration.
    # The environment file and Docker-managed named volumes remain untouched.
    if context.exists():
        shutil.rmtree(context)
    rootfs = context / 'rootfs'
    rootfs.mkdir(parents=True)
    for target, source in node.getImportedFiles().items():
        path = rootfs / target.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, path)
    for file in node.getFiles():
        target, content = file.get()
        path = rootfs / target.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    shutil.copytree(HERE / 'bridge', context / 'bridge',
                    ignore=shutil.ignore_patterns('node_modules', '__pycache__'))
    shutil.copy2(HERE / 'start.py', context / 'start.py')
    dockerfile = [
        'FROM node:22-bookworm-slim',
        'RUN apt-get update && apt-get install -y --no-install-recommends '
        + shlex.join(sorted(node.getSoftware() | {'util-linux'})) + ' && rm -rf /var/lib/apt/lists/*',
        'COPY rootfs/ /',
        *('RUN ' + command for command in node.getBuildCommands()),
        *('RUN ' + command for command in node.getBuildCommandsAtEnd()),
        'COPY bridge/ /opt/minecraft-bridge/',
        'RUN cd /opt/minecraft-bridge && npm ci --omit=dev && npm cache clean --force',
        'COPY start.py /opt/e16/start.py',
        'ENV PYTHONPATH=/opt/emuvista-agent:/opt/emuvista-agent/adapter PYTHONDONTWRITEBYTECODE=1',
        'ENTRYPOINT ["python3", "-u", "/opt/e16/start.py"]',
    ]
    (context / 'Dockerfile').write_text('\n'.join(dockerfile) + '\n')
    (context / '.dockerignore').write_text('**/node_modules\n**/__pycache__\n')
    return {
        'build': './' + name, 'init': True,
        'environment': {'E16_AGENT_NAME': name},
        'extra_hosts': ['host.docker.internal:host-gateway'],
        'depends_on': {'mastodon': {'condition': 'service_healthy'}},
        'volumes': [{'type': 'bind', 'source': str(env_file), 'target': '/run/e16.env',
                     'read_only': True, 'bind': {'create_host_path': False}},
                    f'{name}-state:/home/emuvista-agent',
                    f'{name}-socialmedia:/run/socialmedia:ro'],
        'healthcheck': {'test': ['CMD', 'node', '-e',
            "fetch('http://127.0.0.1:8765/observe').then(r=>r.json()).then(s=>process.exit(s.connected?0:1)).catch(()=>process.exit(1))"],
            'interval': '10s', 'timeout': '5s', 'retries': 3, 'start_period': '30s'},
    }


def generate_mastodon(output):
    """Reuse MastodonBundle's server/templates on E16's ordinary Compose network."""
    server = SocialMediaServer().setDomain(MASTODON_DOMAIN).setHttp(MASTODON_PORT)
    server.addAccount('admin', 'admin123456', email='admin@example.com', admin=True)
    for name in AGENT_NAMES:
        server.addAccount(name, name + '123456', email=name + '@example.com')
        server.exportToken(name, scopes=['read:accounts', 'read:statuses', 'read:notifications', 'write:statuses'],
                           path=f'/var/lib/mastodon/agent-{name}.json')
    return generate_mastodon_compose(
        server, output,
        token_volumes={name: name + '-socialmedia' for name in AGENT_NAMES},
        site_title='E16 Minecraft Stories',
        bootstrap_email_domains=['example.com'],
        image='emuvista-e16-mastodon:local',
        readiness_file='/run/e16-mastodon.ready',
    )


def generate(output, env_file):
    # Validate all replacement targets before overwriting generated directories.
    if not env_file.is_file():
        raise ValueError('Environment file does not exist')
    for folder in (*AGENT_NAMES, 'mastodon-config', 'application-images'):
        target = output / folder
        if target.is_symlink() or env_file.resolve().is_relative_to(target.resolve()):
            raise ValueError('Generated directories must not contain the environment file or be symlinks')
    services = {name: generate_agent(output, env_file, name) for name in AGENT_NAMES}
    services['mastodon'] = generate_mastodon(output)
    volumes = {name: {} for name in ('mastodon-postgresql', 'mastodon-redis', 'mastodon-data', 'mastodon-media')}
    for name in AGENT_NAMES:
        volumes.update({name + '-state': {}, name + '-socialmedia': {}})
    compose = {'name': 'output', 'services': services, 'volumes': volumes}
    (output / 'docker-compose.yml').write_text(json.dumps(compose, indent=2) + '\n')
    print(f'Generated {output}: {", ".join(name.capitalize() for name in AGENT_NAMES)} and Mastodon. Build/start with Docker Compose.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output')
    parser.add_argument('--env-file', type=Path, default=HERE / '.env')
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    if not env_file.exists():
        shutil.copy2(HERE / '.env.example', env_file)
        env_file.chmod(0o600)
    generate(args.output.resolve(), env_file)


if __name__ == '__main__':
    main()
