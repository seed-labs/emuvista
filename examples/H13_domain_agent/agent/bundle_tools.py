"""Adapt Bundle JSON definitions and handlers to H13's independent model loop."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
import threading
from types import ModuleType, SimpleNamespace

from jsonschema import Draft7Validator

# All sessions share one customer/cart. Keep calls serialized even if a WebSocket disconnects.
_customer_lock = threading.Lock()


class ToolRegistry:
    def __init__(self, config_path):
        path = Path(config_path).resolve()
        config = json.loads(path.read_text())
        self.context = SimpleNamespace(accounts=config['accounts'])
        self.definitions = {}
        self.handlers = {}
        self.validators = {}
        allowed = set(config['allowed_tools'])
        for package in config['packages']:
            if not re.fullmatch(r'[a-z][a-z0-9_]*', package):
                raise ValueError('Invalid tool package name')
            source = path.parent / 'packages' / package
            namespace = 'h13_bundle_' + hashlib.sha256(str(source).encode()).hexdigest()[:16]
            if namespace not in sys.modules:
                module = ModuleType(namespace)
                module.__path__ = [str(source)]
                sys.modules[namespace] = module
            for definition in json.loads((source / 'tools.json').read_text()):
                name = definition['name']
                if name in self.definitions or not name.startswith(package + '.'):
                    raise ValueError('Duplicate or invalid tool name')
                if name not in allowed:
                    continue
                module, handler = definition['handler'].split(':')
                function = getattr(importlib.import_module('.' + module, namespace), handler)
                schema = definition['input_schema']
                Draft7Validator.check_schema(schema)
                self.definitions[name] = definition
                self.handlers[name] = function
                self.validators[name] = Draft7Validator(schema)
        if allowed != set(self.definitions):
            raise ValueError('Configured tools are missing from the Bundle')

    def list(self):
        return [copy.deepcopy({key: definition[key] for key in ('name', 'description', 'input_schema')})
                for _, definition in sorted(self.definitions.items())]

    def invoke(self, name, arguments):
        if name not in self.handlers:
            raise PermissionError('Tool is not authorized: ' + name)
        self.validators[name].validate(arguments)
        with _customer_lock:
            return self.handlers[name](arguments, self.context)


def create_registry(config_path=None):
    return ToolRegistry(config_path or Path(__file__).with_name('tool-config.json'))
