#!/bin/bash
# Start the domain agent with simulation routing.
set -euo pipefail
# Automatically configure routes and DNS from egress addresses.
python3 - <<'NETWORK_PY'
"""配置仿真路由、模型出网例外和 DNS 分流。 / Configure simulation routes, model egress exceptions, and split DNS."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


def read_hosts(path):
    """读取每行一个 URL、域名或 IP，不读取模型密钥。 / Read one URL, domain, or IP per line without reading model credentials."""
    hosts = set()
    for number, value in enumerate(path.read_text().splitlines(), 1):
        value = value.strip()
        if not value:
            continue
        try:
            host = str(ipaddress.ip_address(value))
        except ValueError:
            parsed = urlsplit(value if '://' in value else '//' + value)
            host = parsed.hostname
            if (not host or parsed.username is not None or parsed.password is not None
                    or any(c.isspace() for c in value)):
                raise ValueError(f'Invalid egress address at line {number}')
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
                    raise ValueError(f'Invalid egress host at line {number}')
        hosts.add(host.lower())
    return hosts


def main():
    """在服务启动前配置网络，保留 Docker 默认网关。 / Configure networking before services start, retaining Docker's default gateway."""
    subprocess.run(['ip', 'route', 'replace', '10.0.0.0/8', 'via', os.environ['SIM_GATEWAY']], check=True)
    Path('/run/domain-agent').mkdir(parents=True, exist_ok=True)
    lines = ['no-resolv', 'bind-interfaces', 'listen-address=127.0.0.1', 'server=10.150.0.54']
    # Prefer the host-mounted file; standalone images use the build-time copy.
    config = Path('/opt/network-config/egress_urls.txt')
    if not config.exists():
        config = Path('/opt/domain-agent/egress_urls.txt')
    hosts = read_hosts(config)
    route = json.loads(subprocess.check_output(['ip', '-j', 'route', 'show', 'default']))
    for name in sorted(host for host in hosts if host):
        name = name.strip()
        if not name:
            continue
        try:
            address = ipaddress.ip_address(name)
        except ValueError:
            address = None
        if address is not None:
            # Route private model IPs through Docker instead of the simulation aggregate route.
            if address.version == 4 and address in ipaddress.ip_network('10.0.0.0/8') and address not in ipaddress.ip_network('10.154.0.0/24'):
                subprocess.run(['ip', 'route', 'replace', str(address) + '/32',
                                'via', route[0]['gateway'], 'dev', route[0]['dev']], check=True)
            continue
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', name):
            raise ValueError('Invalid hostname in egress_urls.txt')
        lines.append('server=/' + name + '/127.0.0.11')
    Path('/run/domain-agent/dnsmasq.conf').write_text('\n'.join(lines) + '\n')
    Path('/etc/resolv.conf').write_text('nameserver 127.0.0.1\n')


if __name__ == '__main__':
    main()
NETWORK_PY
pids=()
cleanup() {
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
dnsmasq --keep-in-foreground --conf-file=/run/domain-agent/dnsmasq.conf &
pids+=("$!")
/opt/venv/bin/uvicorn agent_web:app --host 0.0.0.0 --port 8089 --ws-max-size 8388608 --no-access-log &
pids+=("$!")
wait -n "${pids[@]}"
