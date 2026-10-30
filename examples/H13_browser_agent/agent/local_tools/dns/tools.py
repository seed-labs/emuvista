"""Run read-only DNS queries in this container."""

import re
import subprocess

from local_tools.dns.models import LookupArguments


def parse_response(output):
    """Preserve DNS status and response sections; process success does not imply successful resolution."""
    status = re.search(r'status: ([A-Z0-9]+)', output)
    flags = re.search(r';; flags: ([^;]*);', output)
    result = {'dns_status': status.group(1) if status else None,
              'authoritative': bool(flags and 'aa' in flags.group(1).split()),
              'answer': [], 'authority': [], 'additional': []}
    section = None
    for line in output.splitlines():
        if line.startswith(';; ') and line.endswith(' SECTION:'):
            section = line[3:-9].lower()
            continue
        if section not in {'answer', 'authority', 'additional'} or line.startswith(';'):
            continue
        fields = line.split(None, 4)
        if len(fields) == 5 and fields[1].isdigit():
            result[section].append(dict(name=fields[0], ttl=int(fields[1]),
                                       record_class=fields[2], record_type=fields[3], value=fields[4]))
    return result


def lookup(name, record_type='A', server=None, recursive=True, tcp=False):
    args = LookupArguments(name=name, record_type=record_type, server=server,
                           recursive=recursive, tcp=tcp)
    # Query inside the browser container without a Docker socket.
    command = ['dig']
    if args.server:
        command.append('@' + args.server)
    command += [args.name, args.record_type, '+time=3', '+tries=1', '+noall', '+comments',
                '+answer', '+authority', '+additional', '+stats',
                '+recurse' if args.recursive else '+norecurse', '+tcp' if args.tcp else '+notcp']
    base = {'name': args.name, 'record_type': args.record_type,
            'server': args.server, 'recursive': args.recursive, 'tcp': args.tcp}
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=12)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {**base, 'query_completed': False, 'error': type(error).__name__,
                'message': '无法完成查询，请检查 本容器网络和 dig 安装情况。'}
    parsed = parse_response(completed.stdout)
    return {**base, **parsed, 'query_completed': completed.returncode == 0 and parsed['dns_status'] is not None,
            'exit_code': completed.returncode, 'output': completed.stdout[:24000],
            'stderr': completed.stderr[:2000],
            'verification': 'NOERROR 不等于记录符合目标；请核对 answer。权威回答与递归解析应分别说明。'}
