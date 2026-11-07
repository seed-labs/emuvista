"""Agent runner and local tool CLI."""

import argparse
import importlib
import json
from .runtime import AgentContext
from .events import JsonEvents


def emit(context, **fields):
    if context.observer is not None:
        terminal = fields.get('status') in ('complete', 'failed') and 'tool' not in fields
        context.emit('run_finished' if terminal else 'message', **fields)
        return
    print(json.dumps({'agent': context.identity, **fields}, allow_nan=False), flush=True)


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
        if args.command == 'run':
            context.observer = JsonEvents(context.identity, context.config)
            context.emit('run_started')
        if args.command == 'list':
            emit(context, tools=context.tools.list())
        elif args.command == 'call':
            emit(context, result=context.tools.invoke(args.tool, json.loads(args.arguments)))
        elif context.config['framework']:
            module, function = context.config['framework'].split(':')
            result = getattr(importlib.import_module(module), function)(context)
            emit(context, status='complete', result=result)
        else:
            failed = False
            for step in context.config['steps']:
                try:
                    result = context.tools.invoke(step['tool'], step.get('arguments', {}))
                    emit(context, tool=step['tool'], status='success', result=result)
                    failed |= step.get('expect') == 'denied'
                except PermissionError as error:
                    emit(context, tool=step['tool'], status='denied', error=str(error))
                    failed |= step.get('expect') != 'denied'
            emit(context, status='failed' if failed else 'complete')
            return int(failed)
        return 0
    except Exception as error:
        if context is not None and context.observer is not None:
            context.emit('run_failed', status='failed', error=str(error))
        else:
            print(json.dumps({'error': str(error)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
