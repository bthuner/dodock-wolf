"""Sequence rules: "A then B within N minutes on the same entity" (no frappe imports; #72 step 5).

A sequence rule names the categories of a first and of a second event, the entity they must share
(`ip`, `user` or `host`, from Wolf Event Entity) and the longest gap between them. rules.py reads
one candidate per (second event, entity value), with the newest matching first event's last
occurrence; `keep` checks it and `group` turns the pairs into one row per entity value, the shape
the rule evaluator reads (value, samples, first_at, last_at) plus the incident's scope and the
events to link.

- `ip`: the remote address of the second event (`payload.ip`), public only. A private address,
  or a server's own (Suricata's `dest_ip`), would pair unrelated events.
- `user`: the same user on the same site ("Administrator" on two sites is not one person).
- `host`: the same host, under any of its names (aliases).
"""

import ipaddress
from datetime import timedelta

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


def keep(pair, kind, gap_minutes):
	"""Whether a candidate (a rules.query_sequence row) is a sequence: the newest first event was
	still seen at most `gap_minutes` before the second's latest occurrence, and for `ip` the
	value is the second event's public remote address."""
	if pair["a_last"] < pair["b_last"] - timedelta(minutes=gap_minutes):
		return False
	if kind == "ip":
		return pair["value"] == pair.get("b_ip") and is_public(pair["value"])
	return True


def group(pairs, kind):
	"""One row per entity value from kept pairs; `a_name` / `a_category` / `a_site` may be missing
	(not looked up for every pair)."""
	rows = {}
	for p in pairs:
		key = f"{kind}={p['value']}"
		row = rows.get(key)
		if row is None:
			row = rows[key] = {"group_key": key, "label": f"{kind} {p['value']}", "seconds": set(), "events": [],
			                   "first_at": p["a_at"], "last_at": p["b_seen"], "newest": p}  # fmt: skip
		row["seconds"].add(p["b_name"])
		for name in (p.get("a_name"), p["b_name"]):
			if name and name not in row["events"] and len(row["events"]) < MAX_EVENTS:
				row["events"].append(name)
		row["first_at"] = min(row["first_at"], p["a_at"])
		if p["b_seen"] >= row["last_at"]:
			row["last_at"], row["newest"] = p["b_seen"], p
	out = []
	for row in rows.values():
		newest = row.pop("newest")
		row["value"] = row["samples"] = len(row.pop("seconds"))
		row.update(host=newest.get("b_host"), bench=newest.get("b_bench"), site=newest.get("b_site"))
		# the summary is read by whoever may read the incident: another scope's event stays unnamed
		same_site = newest.get("a_category") and (newest.get("a_site") or "") == (newest.get("b_site") or "")
		row["first_category"] = newest["a_category"] if same_site else "an earlier event"
		row["second_category"] = newest["b_category"]
		row["gap_minutes"] = max(int((newest["b_last"] - newest["a_last"]).total_seconds() // 60), 0)
		out.append(row)
	return out


def summary(row, window_minutes):
	times = f"{row['value']} time" + ("s" if row["value"] != 1 else "")
	return (
		f"{row['first_category']} then {row['second_category']} {row['gap_minutes']} min later, same "
		f"{row['label']} ({times} in {window_minutes} min)"
	)
