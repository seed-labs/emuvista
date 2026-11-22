#!/bin/bash
set -euo pipefail

# The stable launcher supplies the instance arguments. Users only pass a command.
if [[ $0 == /usr/local/bin/dshagent ]]; then
    exec /opt/emuvista/dshagent/launch "$@"
fi
export DSH_HOME="$1"
profile="$2"
shift 2
bundles=()
while [[ ${1:-} == /opt/emuvista/dshagent/* ]]; do bundles+=("$1"); shift; done
mode=${1:-web}
if (($#)); then shift; fi
umask 077
mkdir -p "$DSH_HOME"
exec 9>"$DSH_HOME/.dshagent-init.lock"
flock 9
target="$DSH_HOME/profiles/$profile"
pending="$DSH_HOME/.dshagent-init-$profile"
if [[ ! -d "$target" || -f "$pending" ]]; then
    touch "$pending"
    if [[ ! -d "$target" ]]; then
        dsh --profile "$profile" --from-default-profile web --dump-config >/dev/null
    fi
    for bundle in "${bundles[@]}"; do
        name=$(node -p 'require(process.argv[1]).name' "$bundle/package.json")
        if ! node -e 'process.exit(Number(!Object.hasOwn(require(process.argv[1]).dependencies ?? {},process.argv[2])))' "$target/package.json" "$name"; then
            dsh plugin --profile "$profile" add "$bundle"
        fi
    done
    cp /opt/emuvista/dshagent/profile.patch.yml "$target/cordis.patch.yml"
    dsh --profile "$profile" --dump-config >/dev/null
    rm -f "$pending"
fi
exec 9>&-
case "$mode" in
    manual) ;;
    auto)
        nohup dsh --profile "$profile" --host 127.0.0.1 --port 3080 --no-open \
            </dev/null >/opt/emuvista/dshagent/web.log 2>&1 &
        ;;
    web)
        exec dsh --profile "$profile" --host 127.0.0.1 --port 3080 --no-open \
            "$@" > >(tee /opt/emuvista/dshagent/web.log) 2>&1
        ;;
    *) echo "Usage: dshagent [web]" >&2; exit 2 ;;
esac
