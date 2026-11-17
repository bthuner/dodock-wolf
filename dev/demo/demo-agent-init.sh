#!/usr/bin/env bash
# A demo server's agent: register as host $2 (once), read the demo layout in
# /home/frappe/demo-$1 (written by `bench generate-demo-$1`), run.
# Usage: demo-agent-init.sh press|multi|single HOSTNAME
set -euo pipefail
KIND="$1"
HOST="$2"
cd /home/frappe/frappe-bench
CONFIG="$WOLF_AGENT_CONFIG"
ROOT="/home/frappe/demo-$KIND"
PLATFORM=generic
[ "$KIND" = press ] && PLATFORM=press

until [ -s sites/.wolf-demo-token ] && curl -fsS http://frontend:8080/api/method/ping >/dev/null 2>&1; do
	echo "waiting for wolf.localhost"; sleep 5
done

if [ ! -f "$CONFIG" ]; then
	# --bench "$ROOT" is not a bench: nothing is registered from this container's own bench. The demo
	# benches reach Wolf through telemetry once `bench generate-demo-$KIND` lays them out.
	token=$(cat sites/.wolf-demo-token)
	until env/bin/wolf-agent --config "$CONFIG" register --url http://frontend:8080 --token "$token" \
		--hostname "$HOST" --platform "$PLATFORM" --bench "$ROOT"; do
		echo "register failed, retrying"; sleep 5
	done
	env/bin/python - "$CONFIG" "$ROOT" <<'PY'
import json, sys
path, root = sys.argv[1:]
cfg = json.load(open(path))
cfg["push_interval"] = 15
# in the shared volume: `bench generate-demo-*` waits on the tail state and spools past host metrics
cfg["spool_dir"] = root + "/agent-spool"
json.dump(cfg, open(path, "w"), indent=2)
PY
	env/bin/wolf-agent --config "$CONFIG" demo "$KIND" --root "$ROOT" --configure
fi

exec env/bin/wolf-agent --config "$CONFIG" -v run
