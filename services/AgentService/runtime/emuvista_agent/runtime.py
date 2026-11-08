"""Local tool discovery, argument validation and per-agent authorization."""

import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import types
import uuid
from .events import result_summary


def validate(value, schema):
    supported = {'type', 'properties', 'required', 'additionalProperties', 'items',
                 'description', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'}
    if set(schema)-supported:
        raise ValueError('unsupported tool schema keywords')
    kind = schema.get('type')
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'integer': type(value) is int,
               'number': type(value) in (int, float), 'boolean': type(value) is bool,
               'null': value is None}
    if kind not in matches or not matches[kind]:
        raise ValueError('expected argument type '+str(kind))
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('argument is outside its allowed values')
    if kind == 'object':
        props = schema.get('properties', {})
        if set(schema.get('required', []))-set(value):
            raise ValueError('required argument is missing')
        if not schema.get('additionalProperties', False) and set(value)-set(props):
            raise ValueError('unknown argument')
        for key, item in value.items():
            if key in props:
                validate(item, props[key])
    if kind == 'array':
        for item in value:
            validate(item, schema['items'])
    if kind in ('number', 'integer'):
        if type(value) is float and not math.isfinite(value):
            raise ValueError('number must be finite')
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise ValueError('number is outside its allowed range')
    if kind == 'string':
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', len(value)):
            raise ValueError('string length is outside its allowed range')


class AgentContext:
    def __init__(self, config):
        if os.getuid() != config['uid']:
            raise PermissionError('run as the configured agent user')
        self.identity = config['identity']
        self.config = config
        self.observer = None
        self.tools = ToolRegistry(self)

    @classmethod
    def load(cls, path='/etc/emuvista-agent/config.json'):
        return cls(json.loads(Path(path).read_text()))

    def service(self, name):
        return dict(self.config['services'][name])

    def emit(self, event, **fields):
        if self.observer is not None:
            self.observer(event, **fields)


class ToolRegistry:
    def __init__(self, context):
        self.context = context
        self.allowed = frozenset(context.config['allowed_tools'])
        self.definitions = {}
        self.paths = {}
        for package in context.config['packages']:
            if not re.fullmatch(r'[a-z][a-z0-9_]*', package):
                raise ValueError('invalid tool package')
            path = Path(context.config['root'])/'packages'/package
            for definition in json.loads((path/'tools.json').read_text()):
                name = definition['name']
                if name in self.definitions or not name.startswith(package+'.'):
                    raise ValueError('duplicate or invalid tool definition')
                self.definitions[name] = definition
                self.paths[name] = (package, path)
        if self.allowed-set(self.definitions):
            raise ValueError('policy grants tools that are not installed')

    def list(self):
        return [{key:definition[key] for key in ('name', 'description', 'input_schema')}
                for name,definition in sorted(self.definitions.items()) if name in self.allowed]

    def invoke(self, name, arguments, *, source='agent'):
        call_id = uuid.uuid4().hex
        started = time.monotonic()
        self.context.emit('tool_started', tool=name, call_id=call_id, arguments=arguments,
                          detail_version=2, source=source)
        try:
            result = self._invoke(name, arguments)
        except Exception as error:
            self.context.emit('tool_failed', tool=name, call_id=call_id,
                              source=source,
                              duration_ms=round((time.monotonic()-started)*1000),
                              status='denied' if isinstance(error, PermissionError) else 'error',
                              error=str(error))
            raise
        self.context.emit('tool_finished', tool=name, call_id=call_id, status='success',
                          source=source,
                          duration_ms=round((time.monotonic()-started)*1000),
                          result=result, summary=result_summary(result), detail_version=2)
        return result

    def _invoke(self, name, arguments):
        # Check before importing or executing any handler, including direct CLI calls.
        if name not in self.allowed:
            raise PermissionError('tool is not authorized: '+name)
        definition = self.definitions[name]
        validate(arguments, definition['input_schema'])
        package, path = self.paths[name]
        namespace = 'emuvista_tools_'+package
        if namespace not in sys.modules:
            module = types.ModuleType(namespace)
            module.__path__ = [str(path)]
            sys.modules[namespace] = module
        module, handler = definition['handler'].split(':')
        function = getattr(importlib.import_module('.'+module, namespace), handler)
        return function(arguments, self.context)
