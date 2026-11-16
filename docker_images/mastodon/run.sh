#!/bin/bash
set -euo pipefail
export PATH=/opt/ruby/bin:/usr/local/bin:$PATH
cd /opt/mastodon
set -a
source /var/lib/mastodon/runtime.env
set +a
# Allow host-side localhost access, including installations with an existing runtime.env.
export ALTERNATE_DOMAINS="${ALTERNATE_DOMAINS:+$ALTERNATE_DOMAINS,}localhost"
exec "$@"
