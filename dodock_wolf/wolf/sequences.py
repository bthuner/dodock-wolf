"""Sequence rules: "A then B within N minutes on the same entity" (no frappe imports; #72 step 5).

A sequence rule names the categories of a first and of a second event, the entity they must share
(`ip`, `user` or `host`, from Wolf Event Entity) and the longest gap between them. rules.py finds
the pairs; `group` turns them into one row per entity value, the shape the rule evaluator reads
(value, samples, first_at, last_at) plus the incident's scope and the events to link.

- `ip`: the remote address of both events (`payload.ip`), public only. A server's own address
  (Suricata's `dest_ip`) or a private one would pair unrelated events.
- `user`: the same user on the same site ("Administrator" on two sites is not one person).
- `host`: the same host, under any of its names (aliases).
"""

import ipaddress

KINDS = ("ip", "user", "host")
MAX_EVENTS = 200  # events linked to one incident per evaluation


def categories(text):
	"""Categories from a Small Text field: one per line, or separated by commas or spaces."""
	return [c for c in str(text or "").replace(",", " ").split() if c]


def is_public(ip):
	try:
		return ipaddress.ip_address(ip).is_global
	except ValueError:
		return False


def keep(pair, kind):
	"""Whether a candidate pair (a rules.query_sequence row) really is the same entity."""
	if kind == "ip":
		return pair["value"] == pair.get("a_ip") == pair.get("b_ip") and is_public(pair["value"])
	if kind == "user":
		return (pair.get("a_site") or "") == (pair.get("b_site") or "")
	return True


def group(pairs, kind):
	"""One row per entity value from (first, second) pairs, newest second event last."""
	rows = {}
	for p in pairs:
		if not keep(p, kind):
			continue
		key = f"{kind}={p['value']}"
		row = rows.get(key)
		if row is None:
			row = rows[key] = {
				"group_key": key,
				"label": f"{kind} {p['value']}",
				"seconds": set(),
				"events": [],
				"first_at": p["a_at"],
				"last_at": p["b_seen"],
				"newest": p,
			}
		row["seconds"].add(p["b_name"])
		for name in (p["a_name"], p["b_name"]):
			if name not in row["events"] and len(row["events"]) < MAX_EVENTS:
				row["events"].append(name)
		row["first_at"] = min(row["first_at"], p["a_at"])
		if p["b_seen"] >= row["last_at"]:
			row["last_at"], row["newest"] = p["b_seen"], p
	out = []
	for row in rows.values():
		newest = row.pop("newest")
		row["value"] = row["samples"] = len(row.pop("seconds"))
		row.update(host=newest.get("b_host"), bench=newest.get("b_bench"), site=newest.get("b_site"))
		row["first_category"], row["second_category"] = newest["a_category"], newest["b_category"]
		row["gap_minutes"] = max(int((newest["b_at"] - newest["a_at"]).total_seconds() // 60), 0)
		out.append(row)
	return out


def summary(row, window_minutes):
	times = f"{row['value']} time" + ("s" if row["value"] != 1 else "")
	return (
		f"{row['first_category']} then {row['second_category']} {row['gap_minutes']} min later, same "
		f"{row['label']} ({times} in {window_minutes} min)"
	)
