#!/bin/bash
set -euo pipefail
# Resolve the simulated instance through H16 DNS, and model endpoints through Docker DNS.
mkdir -p /run/h15
cat > /run/h15/dnsmasq.conf <<'EOF'
no-resolv
bind-interfaces
listen-address=127.0.0.1
server=/mastodon.com/10.151.0.53
server=127.0.0.11
EOF
printf 'nameserver 127.0.0.1\n' > /etc/resolv.conf
dnsmasq --keep-in-foreground --conf-file=/run/h15/dnsmasq.conf &
dns_pid=$!
python -m uvicorn agent_web:app --host 0.0.0.0 --port 8089 --no-access-log &
web_pid=$!
cleanup() { kill "$dns_pid" "$web_pid" 2>/dev/null || true; wait || true; }
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
wait -n "$dns_pid" "$web_pid"
