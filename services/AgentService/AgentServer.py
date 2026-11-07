"""Configure one agent, its framework and tool policy."""

import json
import re
import shlex
from pathlib import Path
from seedemu.core import Server

ROOT = '/opt/emuvista-agent'
CONFIG = '/etc/emuvista-agent/config.json'


class AgentServer(Server):
    def __init__(self, packages):
        super().__init__()
        self._packages = packages
        self._identity = None
        self._allowed = []
        self._services = {}
        self._steps = []
        self._framework = None
        self._environment = {}
        self._environment_file = None
        self._installed = False
        self.appendClassName('AgentService')

    def _editable(self):
        if self._installed:
            raise RuntimeError('configure the agent before rendering')

    def setIdentity(self, identity):
        self._editable()
        if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,49}', identity):
            raise ValueError('invalid agent identity')
        self._identity = identity
        self.setDisplayName('Agent '+identity)
        return self

    def allowTools(self, *names):
        self._editable()
        self._allowed = list(dict.fromkeys(names))
        return self

    def setService(self, name, configuration):
        self._editable()
        self._services[name] = json.loads(json.dumps(configuration))
        return self

    def setScript(self, steps):
        self._editable()
        self._steps = json.loads(json.dumps(steps))
        self._framework = None
        return self

    def setFramework(self, source, entrypoint='adapter:run', requirements=()):
        """Copy a framework adapter exposing run(context); dependencies use pip."""
        self._editable()
        source = Path(source).resolve()
        if not re.fullmatch(r'[a-zA-Z_]\w*:[a-zA-Z_]\w*', entrypoint):
            raise ValueError('entrypoint must be module:function')
        if not (source/(entrypoint.split(':')[0]+'.py')).is_file():
            raise ValueError('adapter module not found')
        self._framework = (source, entrypoint, list(requirements))
        return self

    def setEnvironment(self, name, value):
        self._editable()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('invalid environment variable')
        self._environment[name] = str(value)
        return self

    def setEnvironmentFile(self, path, prefixes=('LLM_', 'AGENT_')):
        """Read a bind-mounted environment at startup; never copy its values into images."""
        self._editable()
        path=Path(path).resolve()
        if not path.is_file():raise ValueError('environment file not found')
        if not prefixes or any(not re.fullmatch(r'[A-Z][A-Z0-9_]*_',p) for p in prefixes):
            raise ValueError('invalid environment prefixes')
        self._environment_file=(path,list(prefixes))
        return self

    def install(self, node):
        self._editable()
        names = {tool['name'] for package in self._packages.values() for tool in package.manifest}
        if not set(self._allowed) <= names:
            raise ValueError('authorized tools are not installed: '+str(sorted(set(self._allowed)-names)))
        node.addSoftware('python3 python3-venv ca-certificates')
        node.addBuildCommand('python3 -m venv '+ROOT+'/venv')
        node.addBuildCommand('useradd --uid 10001 --create-home --shell /usr/sbin/nologin emuvista-agent')
        source = Path(__file__).parent/'runtime/emuvista_agent'
        for path in source.glob('*.py'):
            node.importFile(str(path.resolve()), ROOT+'/emuvista_agent/'+path.name)
        packages = []
        requirements = []
        for package in self._packages.values():
            if package.software:
                node.addSoftware(' '.join(package.software))
            requirements.extend(package.requirements)
            for path, relative in package.files():
                node.importFile(str(path), ROOT+'/packages/'+package.name+'/'+relative.as_posix())
            packages.append(package.name)
        framework = None
        if self._framework:
            source, framework, framework_requirements = self._framework
            requirements.extend(framework_requirements)
            for path in source.rglob('*'):
                if any(p in {'__pycache__', '.git', '.venv'} for p in path.relative_to(source).parts):
                    continue
                if path.is_symlink():
                    raise ValueError('adapter source must not contain symlinks')
                if path.is_file() and not any(p in {'__pycache__', '.git', '.venv'} for p in path.relative_to(source).parts):
                    node.importFile(str(path), ROOT+'/adapter/'+path.relative_to(source).as_posix())
        if requirements:
            node.addBuildCommand(ROOT+'/venv/bin/pip install '+shlex.join(dict.fromkeys(requirements)))
        config = {'identity': self._identity, 'uid': 10001, 'root': ROOT,
                  'packages': packages, 'allowed_tools': self._allowed,
                  'services': self._services, 'steps': self._steps, 'framework': framework}
        node.setFile(CONFIG, json.dumps(config, indent=2)+'\n')
        node.setFile('/usr/local/bin/agentctl', '#!/bin/sh\nexport PYTHONPATH='+ROOT+':'+ROOT+'/adapter\n'
                     'export PYTHONDONTWRITEBYTECODE=1\nexec '+ROOT+'/venv/bin/python -m emuvista_agent \"$@\"\n')
        node.addBuildCommandAtEnd('chmod 755 /usr/local/bin/agentctl')
        # Files and policy belong to root; the framework runs under its own user.
        node.addBuildCommandAtEnd('chmod -R go-w '+ROOT+' /etc/emuvista-agent')
        environment = {'PYTHONPATH': ROOT+':'+ROOT+'/adapter', 'PYTHONDONTWRITEBYTECODE': '1',
                       'VIRTUAL_ENV': ROOT+'/venv', 'PATH': ROOT+'/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       'HOME': '/home/emuvista-agent', **self._environment}
        command = ['runuser', '-u', 'emuvista-agent', '--', 'env',
                   *(key+'='+value for key,value in environment.items()),
                   ROOT+'/venv/bin/python', '-u', '-m', 'emuvista_agent', 'run']
        if self._environment_file:
            source,prefixes=self._environment_file
            target='/run/emuvista-agent.env'
            node.addSharedFolder(target,str(source),read_only=True,bind={'create_host_path':False})
            command=['python3',ROOT+'/emuvista_agent/launch.py',target,json.dumps(prefixes),*command]
        node.appendStartCommand(shlex.join(command)+' > /home/emuvista-agent/agent.log 2>&1', fork=True)
        self._installed = True
