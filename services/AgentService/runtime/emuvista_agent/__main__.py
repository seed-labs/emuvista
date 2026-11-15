"""Local tool CLI and direct framework application launcher."""

import argparse
import json
import os
import sys
from .runtime import AgentContext
from .events import JsonEvents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/emuvista-agent/config.json')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    commands.add_parser('run')
    call = commands.add_parser('call')
    call.add_argument('tool')
    call.add_argument('arguments', nargs='?', default='{}')
    args = parser.parse_args()
    context = None
    try:
        context = AgentContext.load(args.config)
        if args.command == 'list':
            print(json.dumps({'agent': context.identity, 'tools': context.tools.list()}))
        elif args.command == 'call':
            redactor = JsonEvents(context.identity, context.config)
            result = context.tools.invoke(args.tool, json.loads(args.arguments))
            print(json.dumps(redactor.clean(
                {'agent': context.identity, 'result': result}), allow_nan=False))
        else:
            if args.config != '/etc/emuvista-agent/config.json':
                raise ValueError('framework startup uses the installed default configuration')
            os.execv(sys.executable, [sys.executable, '-u',
                     context.config['framework']['entrypoint']])
        return 0
    except Exception as error:
        if context and context.observer:
            context.emit('run_failed', status='failed', error=str(error))
        else:
            print(json.dumps({'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
