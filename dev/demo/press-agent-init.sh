#!/usr/bin/env bash
# The Press demo's agent: register as the Press app server f1-demo-press (once), read the demo
# layout in /home/frappe/demo-press (written by `bench generate-demo-press`), run.
set -euo pipefail
cd /home/frappe/frappe-bench
CONFIG="$WOLF_AGENT_CONFIG"
ROOT=/home/frappe/demo-press

until [ -s sites/.wolf-demo-token ] && curl -fsS http://frontend:8080/api/method/ping >/dev/null 2>&1; do
	echo "waiting for wolf.localhost"; sleep 5
done

if [ ! -f "$CONFIG" ]; then
	token=$(cat sites/.wolf-demo-token)
	until env/bin/wolf-agent --config "$CONFIG" register --url http://frontend:8080 --token "$token" \
		--hostname f1-demo-press --platform press; do
		echo "register failed, retrying"; sleep 5
	done
	env/bin/python - "$CONFIG" "$ROOT" <<'PY'
import json, sys
path, root = sys.argv[1:]
cfg = json.load(open(path))
cfg["push_interval"] = 15
# in the shared volume: `bench generate-demo-press` waits on the tail state and spools past host metrics
cfg["spool_dir"] = root + "/agent-spool"
json.dump(cfg, open(path, "w"), indent=2)
PY
	env/bin/wolf-agent --config "$CONFIG" demo press --root "$ROOT" --configure
fi

exec env/bin/wolf-agent --config "$CONFIG" -v run
