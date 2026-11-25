#!/usr/bin/env bash
set -euo pipefail

example_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
output_dir="$example_dir/output"

if [[ ! -f "$output_dir/docker-compose.yml" ]]; then
    echo "H24 has not been compiled yet: $output_dir/docker-compose.yml is missing" >&2
    exit 1
fi

cd "$output_dir"
docker compose down

# Reset the H24 market, venue, and Bank customer/transaction state so every
# presentation starts with the seeded bank balances. Mailboxes are preserved.
rm -rf -- h24-state/stock-db h24-state/quantreplay-db h24-state/quantreplay
mkdir -p h24-state/stock-db h24-state/quantreplay-db h24-state/quantreplay

bank_state_dir="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["state_path"])' \
    "$output_dir/h24-bank/deployment.json")"
if [[ "$(basename -- "$bank_state_dir")" != seedemu-bank-* \
      || ! -f "$bank_state_dir/configuration.sha256" ]]; then
    echo "Refusing to reset unexpected Bank state path: $bank_state_dir" >&2
    exit 1
fi
for state in core-db bff-db redis initialization; do
    rm -rf -- "$bank_state_dir/$state"
    mkdir -p -- "$bank_state_dir/$state"
done

# Keep generated build contexts in sync with the H24 source while only rebuilding
# the Python controller/agent images. This does not rebuild BankBundle or Mailu.
cp "$example_dir/container/runner.py" h24-demo-runner/runner.py
cp "$example_dir/container/runner.Dockerfile" h24-demo-runner/Dockerfile
cp "$example_dir/container/agent_worker.py" h24-demo-runner/agent_worker.py
docker compose build h24-demo-runner h24-alice-agent-vm h24-bob-agent-vm h24-carol-agent-vm

docker compose up -d --no-build
docker compose ps h24-alice-agent-vm h24-bob-agent-vm h24-carol-agent-vm h24-demo-runner
