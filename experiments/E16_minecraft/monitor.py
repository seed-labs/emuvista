#!/usr/bin/env python3
"""E16 agent activity and Minecraft state dashboard."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.E16_minecraft import monitor_server as shared


def discover(output):
    agents = []
    for path in sorted(output.glob('*/rootfs/etc/emuvista-agent/config.json')):
        service = path.relative_to(output).parts[0]
        if not path.is_file():
            continue
        config = json.loads(path.read_text())
        agents.append({'name': config['identity'], 'service': service,
                       'task': config.get('services', {}).get('persona', {}).get('task', ''),
                       'tools': config.get('allowed_tools', [])})
    return agents


# Reuse the log collector in the same docker exec, then add a read-only bridge query.
# The bridge address is fixed; no environment or credentials are exported.
COLLECT = shared.COLLECT[:shared.COLLECT.rindex('print(json.dumps(')] + r"""
from datetime import datetime, timezone
from urllib.request import ProxyHandler, build_opener
minecraft = {'observed_at': datetime.now(timezone.utc).isoformat()}
try:
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:8765/observe', timeout=3) as response:
        state = json.load(response)
    fields = ('connected', 'username', 'health', 'food', 'position', 'dimension',
              'held_item', 'inventory', 'active_action', 'time_of_day', 'raining', 'error')
    minecraft.update({key: state[key] for key in fields if key in state})
except Exception as error:
    minecraft['error'] = str(error)
print(json.dumps({'log':text,'modified':modified,'process_running':running,'address':address,
                  'profile':profile,'minecraft':minecraft}))
"""


class Observer(shared.Observer):
    discover = staticmethod(discover)
    collect_program = COLLECT

    @staticmethod
    def summarize(metadata, container, observation=None, error=None):
        result = shared.summarize(metadata, container, observation, error)
        state = shared.scrub((observation or {}).get('minecraft', {}))
        # Cached health/inventory remain last-known values, never live after failure.
        state = {**state, 'stale': bool(error or container.get('State') != 'running'
                                      or state.get('error') or not state.get('observed_at'))}
        if error:
            state['error'] = error
        elif container.get('State') != 'running':
            state['error'] = 'Agent container is not running.'
        result['minecraft'] = state
        return result


def make_handler(observer):
    dashboard = HERE / 'dashboard'
    index = (HERE.parent / 'E99_virtual_world_with_agents/dashboard/index.html').read_text()
    index = index.replace('E99', 'E16').replace('Email · Payment · Banking', 'Minecraft · Mastodon')
    index = index.replace('<div class="nav-caption">',
                          '<a class="nav-item" href="/minecraft">Minecraft 状态 →</a><div class="nav-caption">', 1)
    # A header link stays visible on small screens, where the shared sidebar hides.
    index = index.replace('<h1>Agent activity</h1>',
                          '<h1>Agent activity</h1><p><a href="/minecraft">Minecraft 状态 →</a></p>')
    pages = {'/': (index.encode(), 'text/html')}
    for route, filename, content_type in (
        ('/minecraft', 'minecraft.html', 'text/html'),
        ('/minecraft.js', 'minecraft.js', 'text/javascript'),
        ('/minecraft.css', 'minecraft.css', 'text/css'),
    ):
        pages[route] = ((dashboard / filename).read_bytes(), content_type)
    return shared.make_handler(observer, pages=pages)


def main():
    if not any(arg == '--output' or arg.startswith('--output=') for arg in sys.argv[1:]):
        sys.argv.extend(['--output', str(HERE / 'output')])
    shared.main(observer_factory=Observer, handler_factory=make_handler)


if __name__ == '__main__':
    main()
