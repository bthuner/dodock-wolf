#!/usr/bin/env bash
# The Wolf agent on the Wazuh manager's host (the "ids" profile): reads alerts.json and nothing
# else. It runs in the `wazuh` group (compose.yaml group_add), as the docs ask on a real manager.
set -euo pipefail
cd /home/frappe/frappe-bench
CONFIG="$WOLF_AGENT_CONFIG"

until [ -s sites/.wolf-demo-token ] && curl -fsS http://frontend:8080/api/method/ping >/dev/null 2>&1; do
	echo "waiting for wolf.localhost"; sleep 5
done

if [ ! -f "$CONFIG" ]; then
	# --bench names no bench: this host runs Wazuh, not Frappe
	token=$(cat sites/.wolf-demo-token)
	until env/bin/wolf-agent --config "$CONFIG" register --url http://frontend:8080 --token "$token" \
		--hostname wazuh-manager --bench /home/frappe/wolf-agent; do
		echo "register failed, retrying"; sleep 5
	done
	env/bin/python - "$CONFIG" <<'PY'
import json, sys
path = sys.argv[1]
cfg = json.load(open(path))
cfg.update({"push_interval": 15, "spool_dir": "/home/frappe/wolf-agent/spool", "auth_log": False, "suricata": False,
            "mariadb": False, "processes": False, "exposure": False, "backups": False, "tls": False,
            "versions": False, "site_settings": False, "integrity": False, "outbound": False})
json.dump(cfg, open(path, "w"), indent=2)
PY
fi

exec env/bin/wolf-agent --config "$CONFIG" -v run
