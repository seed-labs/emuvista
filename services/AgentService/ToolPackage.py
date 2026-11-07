"""Service-owned tool source copied into agent nodes."""

import json
import re
from pathlib import Path


class ToolPackage:
    def __init__(self, name, source, *, requirements=(), software=()):
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise ValueError('invalid tool package name')
        self.name = name
        self.source = Path(source).resolve()
        self.requirements = tuple(requirements)
        self.software = tuple(software)
        self.manifest = json.loads((self.source/'tools.json').read_text())
        names = set()
        for tool in self.manifest:
            if (not re.fullmatch(re.escape(name)+r'\.[a-z][a-z0-9_]*', tool['name'])
                    or tool['name'] in names
                    or not re.fullmatch(r'[a-zA-Z_]\w*:[a-zA-Z_]\w*', tool['handler'])):
                raise ValueError('invalid or duplicate tool name or handler')
            if not (self.source/(tool['handler'].split(':')[0]+'.py')).is_file():
                raise ValueError('tool handler module not found')
            names.add(tool['name'])
        if not names:
            raise ValueError('tool package must define tools')

    def files(self):
        for path in sorted(self.source.rglob('*')):
            if any(p in {'__pycache__', '.git', '.venv'} for p in path.relative_to(self.source).parts):
                continue
            if path.is_symlink():
                raise ValueError('tool source must not contain symlinks')
            if path.is_file() and not any(p in {'__pycache__', '.git', '.venv'} for p in path.relative_to(self.source).parts):
                yield path, path.relative_to(self.source)
