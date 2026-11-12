"""Configure a person's framework deployment on one SEED host."""

import json
import shlex
from pathlib import Path
from seedemu.core import Server
from .frameworks import get_framework

ROOT = '/opt/emuvista-agent'
CONFIG = '/etc/emuvista-agent/config.json'
DATA = '/home/emuvista-agent/state'


class AgentServer(Server):
    def __init__(self, packages, clock, environment_file=None):
        super().__init__()
        self._packages = packages
        self._clock = clock
        self._persona = {}
        self.vnode = None
        self._tools = None
        self._framework = 'langchain'
        self._environment_file = environment_file
        self._installed = False
        self.appendClassName('AgentService')

    def _editable(self):
        if self._installed:
            raise RuntimeError('configure the agent before rendering')

    def setPersona(self, persona):
        self._editable()
        if not isinstance(persona, dict):
            raise TypeError('persona must be a JSON object')
        value = json.loads(json.dumps(persona, allow_nan=False))
        if not isinstance(value.get('id'), str) or not value['id'].strip():
            raise ValueError('persona requires a stable, non-empty person id')
        if not isinstance(value.get('accounts', {}), dict):
            raise TypeError('persona accounts must be an object')
        self._persona = value
        self.setDisplayName(value.get('name') or 'Agent ' + value['id'])
        return self

    def setTools(self, tools):
        self._editable()
        if not isinstance(tools, (list, tuple)) or any(not isinstance(name, str) for name in tools):
            raise TypeError('tools must be a list of registered tool names')
        self._tools = list(dict.fromkeys(tools))
        return self

    def setFramework(self, framework):
        self._editable()
        get_framework(framework)
        self._framework = framework
        return self

    def install(self, node):
        self._editable()
        if 'id' not in self._persona:
            raise ValueError('setPersona with a stable person id before rendering')
        names = {tool['name'] for package in self._packages.values() for tool in package.manifest}
        selected = sorted(names) if self._tools is None else self._tools
        if not set(selected) <= names:
            raise ValueError('tools are not installed: ' + str(sorted(set(selected) - names)))
        node.addSoftware('python3 python3-venv ca-certificates')
        node.addBuildCommand('python3 -m venv ' + ROOT + '/venv')
        node.addBuildCommand(
            'useradd --uid 10001 --create-home --shell /usr/sbin/nologin emuvista-agent')
        node.addBuildCommand('install -d -m 700 -o 10001 -g 10001 ' + DATA)
        for path in (Path(__file__).parent / 'runtime/emuvista_agent').glob('*.py'):
            node.importFile(str(path.resolve()), ROOT + '/emuvista_agent/' + path.name)
        requirements = []
        for package in self._packages.values():
            if package.software:
                node.addSoftware(' '.join(package.software))
            requirements.extend(package.requirements)
            for path, relative in package.files():
                if relative.as_posix() != 'tools.json':
                    node.importFile(str(path), ROOT + '/packages/' +
                                    package.name + '/' + relative.as_posix())
            node.setFile(ROOT + '/packages/' + package.name + '/tools.json',
                         json.dumps(package.manifest, indent=2) + '\n')
        framework = get_framework(self._framework)
        requirements.extend(framework.REQUIREMENTS)
        if requirements:
            node.addBuildCommand(ROOT + '/venv/bin/python -m pip install ' +
                                 shlex.join(dict.fromkeys(requirements)))
        deployment = framework.install(node, ROOT, DATA)
        config = {'identity': self._persona['id'], 'uid': 10001, 'root': ROOT,
                  'clock': self._clock.getURL(),
                  'packages': list(self._packages), 'allowed_tools': selected,
                  'tool_config': {name: package.configuration for name, package in self._packages.items()},
                  'persona': self._persona, 'framework': deployment}
        node.setFile(CONFIG, json.dumps(config, indent=2, allow_nan=False) + '\n')
        node.setFile('/usr/local/bin/agentctl', '#!/bin/sh\nexport PYTHONPATH=' + ROOT + '\n'
                     'export PYTHONDONTWRITEBYTECODE=1\nexec ' + ROOT + '/venv/bin/python -m emuvista_agent "$@"\n')
        node.addBuildCommandAtEnd('chmod 755 /usr/local/bin/agentctl')
        node.addBuildCommandAtEnd('chmod -R go-w ' + ROOT + ' /etc/emuvista-agent')
        node.addBuildCommandAtEnd('chmod 640 ' + CONFIG + ' && chown 0:10001 ' + CONFIG)
        node.setLabel('org.emuvista.agent.id', self._persona['id'])
        node.setLabel('org.emuvista.agent.state-directory', DATA)
        environment = {'PYTHONPATH': ROOT, 'PYTHONDONTWRITEBYTECODE': '1',
                       'VIRTUAL_ENV': ROOT + '/venv',
                       'PATH': ROOT + '/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       'HOME': '/home/emuvista-agent'}
        command = ['runuser', '-u', 'emuvista-agent', '--', 'env',
                   *(key + '=' + value for key, value in environment.items()),
                   ROOT + '/venv/bin/python', '-u', deployment['entrypoint']]
        if self._environment_file:
            target = '/run/emuvista-agent.env'
            node.addSharedFolder(target, str(self._environment_file), read_only=True,
                                 bind={'create_host_path': False})
            command = ['python3', ROOT + '/emuvista_agent/launch.py', target,
                       json.dumps(['LLM_', 'AGENT_']), *command]
        node.appendStartCommand(shlex.join(command) +
                                ' > /home/emuvista-agent/agent.log 2>&1', fork=True)
        self._installed = True
