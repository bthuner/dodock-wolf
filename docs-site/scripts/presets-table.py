"""Print the preset rules of dodock_wolf/wolf/presets.py as Markdown tables, grouped.

Run from the repository root with `python3 -I docs-site/scripts/presets-table.py`, and paste
the output into content/{en,fr}/4.alerts/2.presets.md when presets change.
"""
import ast
import sys

GROUPS = [
	("Web and deployments", ["502 spike after deployment", "5xx spike"]),
	("Cron, scheduler and workers", [
		"Nightly cron failure (01:00-04:00)", "Scheduler failure", "Scheduler stalled", "Worker crash",
		"Worker queue backlog", "Background jobs failing", "Long-running background job",
		"No background workers", "Queue Redis memory high", "Queue Redis evicting keys", "Bench process down"]),
	("Hosts and agents", ["Disk almost full", "High CPU", "High memory", "High load", "Agent silent"]),
	("Backups, TLS, database and email", [
		"No backup for 26 h", "Backup failed", "TLS certificate expiring within 14 days",
		"TLS certificate expiring within 3 days", "Database connections high", "Slow queries",
		"Replication lag", "Replication stopped", "Email queue backlog", "Email sending errors"]),
	("Logins and accounts", [
		"SSH brute force", "SSH login after brute force", "Repeated sudo failures", "New system account",
		"User added to admin group", "Repeated failed Frappe logins", "Admin login from new IP",
		"Admin login from new country", "Privileged role granted"]),
	("Attacks and intrusion", [
		"Web attack scan", "Sensitive file served", "Network IDS alert (critical)",
		"Host intrusion alert (critical)", "Honeytoken touched", "Bench service exposed",
		"Development settings in production", "Bench code changed outside a deployment",
		"Bench or server config changed", "Bench connects somewhere new"]),
	("Application changes and posture", [
		"Server Script can run new code", "Client Script can run new code", "System Console used",
		"Security settings weakened", "Permission rules changed", "API key generated",
		"API key used from a new IP", "Webhook to a new host", "Unusual data export",
		"Security score low", "Regulatory deadline"]),
	("Sequences across sources", [
		"Scan then login from the same IP", "New-IP login then export or new key",
		"IDS alert then risky change on the host"]),
]
GLYPH = {"info": "○ info", "warning": "◐ warning", "critical": "● critical"}


def presets(path):
	out = {}
	for node in ast.walk(ast.parse(open(path).read())):
		if isinstance(node, ast.Dict):
			d = {}
			for k, v in zip(node.keys, node.values, strict=True):
				if isinstance(k, ast.Constant):
					try:
						d[k.value] = ast.literal_eval(v)
					except ValueError:
						pass
			if "rule_name" in d:
				out[d["rule_name"]] = d
	return out


def condition(d):
	thr = d.get("threshold") or 0
	thr = int(thr) if float(thr).is_integer() else thr
	win = d.get("window_minutes")
	if d.get("signal_type") == "sequence":
		def cats(key):
			return ", ".join(f"`{c}`" for c in d[key].split())
		first = cats("first_categories")
		if d.get("first_min_severity"):
			first += f" ({d['first_min_severity']})"
		return (f"one of {first}, then one of {cats('then_categories')} on the same "
			f"`{d['sequence_entity']}` within {d['sequence_minutes']} min")
	if d.get("signal_type") == "metric":
		what = f"`{d.get('aggregation', 'avg')}({d['metric_name']})`"
	else:
		cat = d.get("event_category")
		what = f"`{d['event_type']}`" + (f" / `{cat}`" if cat else "") + " events"
		if d.get("min_severity"):
			what += f" ({d['min_severity']})"
	text = f"{what} {d.get('operator', '>')} {thr} in {win} min"
	if d.get("active_from"):
		text += f", {d['active_from'][:5]}–{d['active_to'][:5]}"
	if d.get("require_recent_deployment"):
		text += ", after a deployment"
	return text


def main():
	p = presets("dodock_wolf/wolf/presets.py")
	seen = set()
	for title, names in GROUPS:
		print(f"## {title}\n\n| Preset | Fires when | Per | Severity |\n|---|---|---|---|")
		for n in names:
			d = p[n]
			seen.add(n)
			# A sequence rule opens one incident per entity value (`ip 203.0.113.5`), whatever group_by says.
			per = d["sequence_entity"] if d.get("signal_type") == "sequence" else d.get("group_by", "host")
			print(f"| {n} | {condition(d)} | `{per}` | {GLYPH[d.get('severity', 'warning')]} |")
		print()
	missing = set(p) - seen
	if missing:
		sys.exit(f"presets not in any group: {sorted(missing)}")


main()
