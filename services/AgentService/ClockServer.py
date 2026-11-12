"""Shared real-time clock server managed by AgentService."""

from pathlib import Path

from seedemu.core import Server


class ClockServer(Server):
    def __init__(self):
        super().__init__()
        self.vnode = 'agent_clock'
        self._address = None
        self.setDisplayName('Agent Clock')
        self.appendClassName('ClockServer')

    def configure(self, node):
        self._address = str(node.getInterfaces()[0].getAddress())

    def getURL(self):
        return f'http://{self._address}:8080'

    def install(self, node):
        node.addSoftware('python3')
        node.importFile(str(Path(__file__).parent / 'runtime/clock_server.py'),
                        '/opt/emuvista-clock/server.py')
        node.appendStartCommand(
            'python3 -u /opt/emuvista-clock/server.py > /var/log/agent-clock.log 2>&1',
            fork=True,
        )
        node.addDockerCommand(
            'HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=15 '
            'CMD python3 -c "import urllib.request; '
            "urllib.request.urlopen('http://127.0.0.1:8080/time', timeout=1).read()\""
        )
