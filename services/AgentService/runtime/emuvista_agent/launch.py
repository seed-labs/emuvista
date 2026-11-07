"""Read runtime environment from a bind-mounted file before dropping privileges."""
import ast
import json
import os
from pathlib import Path
import re
import sys


def read_environment(path, prefixes=('LLM_', 'AGENT_')):
    values = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):line=line[7:]
        key, separator, value = line.partition('=')
        key=key.strip()
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key) or not key.startswith(tuple(prefixes)):
            continue
        value=value.strip()
        if value.startswith(('"',"'")):
            value=ast.literal_eval(value)
        else:value=value.split(' #',1)[0].rstrip()
        if not isinstance(value,str):raise ValueError('environment values must be strings')
        values[key]=value
    return values


if __name__=='__main__':
    filename,prefixes=sys.argv[1:3]
    command=sys.argv[3:]
    os.environ.update(read_environment(filename,json.loads(prefixes)))
    os.execvp(command[0],command)
