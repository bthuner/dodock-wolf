"""Alert rule evaluation, run every minute by the scheduler."""

import json

import frappe
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime

from dodock_wolf.wolf import conditions, entities, events, incidents, notify, rollups, sequences

SCOPE_FIELDS = ("host", "bench", "site")


def evaluate_all():
	for name in frappe.get_all("Wolf Alert Rule", filters={"enabled": 1}, pluck="name"):
		rule = frappe.get_doc("Wolf Alert Rule", name)
		try:
			evaluate(rule)
			error = None
		except Exception:
			frappe.db.rollback()
			error = frappe.get_traceback()[-1000:]
			frappe.log_error(title=f"[Wolf] Alert rule {name} failed")
		frappe.db.set_value(
			"Wolf Alert Rule",
			name,
			{"last_evaluated": now_datetime(), "last_error": error},
			update_modified=False,
		)
		frappe.db.commit()


def evaluate(rule, now=None):
	"""Evaluate one rule. Returns {"fired": [...], "resolved": [...]} incident names."""
	now = now or now_datetime()
	result = {"fired": [], "updated": [], "resolved": []}
	if not conditions.in_active_window(now.time(), rule.active_from, rule.active_to):
		return result

	since = add_to_date(now, minutes=-max(cint(rule.window_minutes), 1))
	rows = query(rule, since)
	sequence = rule.signal_type == "sequence"

	min_samples = cint(rule.min_samples) or 1
	resolve_threshold = rule.resolve_threshold if rule.get("use_resolve_threshold") else None
	fire_after = cint(rule.get("fire_after_evaluations")) or 1
	by_key = {row["group_key"] if sequence else conditions.group_key(rule.group_by, row): row for row in rows}
	open_by_key = {
		inc.group_key: inc.name
		for inc in frappe.get_all(
			"Wolf Incident",
			filters={"alert_rule": rule.name, "status": ("in", incidents.OPEN)},
			fields=["name", "group_key"],
			order_by="started_at asc",
		)
	}
	old_state = conditions.load_state(rule.get("evaluation_state"))
	state = {}

	# Every group with data, an open incident or a pending counter gets one step.
	for key in sorted(set(by_key) | set(open_by_key) | set(old_state)):
		row = by_key.get(key)
		breached = row is not None and conditions.is_breached(row, rule.operator, rule.threshold, min_samples)
		still = conditions.is_still_breached(row, rule.operator, rule.threshold, resolve_threshold, min_samples)
		new, action = conditions.hysteresis_step(
			old_state.get(key),
			breached,
			still,
			key in open_by_key,
			fire_after=fire_after,
			resolve_after=cint(rule.get("resolve_after_evaluations")) or 1,
			auto_resolve=bool(rule.auto_resolve),
		)
		if new:
			state[key] = new

		if action == "resolve":
			name = open_by_key[key]
			incidents.resolve(name)
			result["resolved"].append(name)
			if _flag(rule, "notify_on_resolve"):
				notify.enqueue(name, "resolved")
			elif notify.has_stateful(rule.name):
				# Close the alert on PagerDuty-style channels even when the others stay quiet.
				notify.enqueue(name, "resolved", only_stateful=True)
			continue
		if action not in ("fire", "update"):
			continue

		if sequence:
			scope = {f: row.get(f) for f in SCOPE_FIELDS}
			scope["label"] = row["label"]
		else:
			scope = conditions.incident_scope(rule.group_by, row)
			scope["label_key"] = row.get("label_key")
		if rule.require_recent_deployment and not incidents.latest_deployment(
			scope["host"], scope["bench"], scope["site"], minutes=cint(rule.deployment_window_minutes) or 30
		):
			if action == "fire" and fire_after > 1:
				# Keep the streak so the next breach after a deployment fires at once.
				state[key] = [fire_after - 1, 0]
			continue

		summary = sequences.summary(row, rule.window_minutes) if sequence else (
			f"{describe_signal(rule)} = {conditions.format_value(row['value'])} "
			f"({rule.operator} {conditions.format_value(rule.threshold)}) over {rule.window_minutes} min"
		)
		# an event rule reopens a resolved incident only for events newer than its resolution
		# (by their time or by their arrival: a late batch was not seen by whoever resolved it)
		newest_at = row.get("last_at") if rule.signal_type in ("event", "sequence") else None
		name, kind = incidents.open_incident(rule, key, scope, summary, started_at=row.get("first_at"), newest_at=newest_at)
		if not name:
			if action == "fire" and fire_after > 1:
				state[key] = [fire_after - 1, 0]  # a newer event then reopens it at once
			continue
		if sequence:
			incidents.link_events(name, row["events"])
		elif rule.signal_type == "event":
			incidents.link_events(name, matching_event_names(rule, since, row))
		elif kind:
			record_metric_alert(rule, name, scope, summary)
		if kind:
			result["fired"].append(name)
			notify.enqueue(name, kind)
		else:
			result["updated"].append(name)

	if state != old_state:
		frappe.db.set_value(
			"Wolf Alert Rule", rule.name, "evaluation_state", conditions.dump_state(state) if state else None, update_modified=False
		)
	if result["fired"]:
		frappe.db.set_value("Wolf Alert Rule", rule.name, "last_fired", now, update_modified=False)
	return result


def _flag(doc, field, default=1):
	"""Check fields added after a rule was created read as None on in-memory docs."""
	value = doc.get(field)
	return default if value is None else cint(value)


def describe_signal(rule):
	if rule.signal_type == "metric":
		return f"{rule.aggregation}({rule.metric_name})"
	if rule.signal_type == "sequence":
		first, then = (" or ".join(sequences.categories(rule.get(f))) for f in ("first_categories", "then_categories"))
		return f"{first} then {then} within {rule.sequence_minutes} min, same {rule.sequence_entity}"
	return f"count({rule.event_type}{'/' + rule.event_category if rule.event_category else ''})"


def _scope_filters(rule, params, prefix=""):
	conds = []
	for field in SCOPE_FIELDS:
		value = rule.get(f"filter_{field}")
		if value:
			conds.append(f"{prefix}`{field}` = %(filter_{field})s")
			params[f"filter_{field}"] = value
	return conds


def _select_group(group_by):
	cols = conditions.group_columns(group_by)
	select = [f"`{c}`" for c in cols]
	# Scope hints let a site-grouped incident still know its bench and host.
	select += [f"max(`{f}`) as {f}_hint" for f in SCOPE_FIELDS if f not in cols]
	group = f"group by {', '.join(f'`{c}`' for c in cols)}" if cols else ""
	return ", ".join(select), group


def _until():
	# Upper bound for rule windows: rows stamped in the future (older data, clock skew) are
	# ignored instead of keeping every window breached until real time catches up.
	return add_to_date(now_datetime(), minutes=1)


def query(rule, since):
	"""The rule's rows over [since, now]: one per group (metric, event) or entity (sequence)."""
	if rule.signal_type == "metric":
		return query_metric(rule, since)
	if rule.signal_type == "sequence":
		return query_sequence(rule, since)
	return query_events(rule, since)


MAX_PAIRS = 2000  # (second event, entity value) candidates per evaluation
MAX_LOOKUPS = 50  # first events looked up to link, newest pairs first
FIRST_LOOKBACK_HOURS = 24  # a deduplicated first event indexed this long before the gap still counts


def query_sequence(rule, since):
	"""Second events seen in [since, now], each with a first event naming the same entity before
	it, at most Sequence Minutes before the second's latest occurrence (wolf/sequences.py). One
	candidate per (second event, entity value), with the newest first event's last occurrence:
	a brute force of thousands of first events stays one row. The scope filters apply to the
	second event."""
	kind = rule.sequence_entity
	first, then = sequences.categories(rule.first_categories), sequences.categories(rule.then_categories)
	if kind not in sequences.KINDS or not first or not then:
		return []
	gap = max(cint(rule.sequence_minutes), 1)
	first_since = add_to_date(since, minutes=-gap)
	params = {"kind": kind, "first": tuple(first), "then": tuple(then), "since": since, "until": _until(),
	          "first_since": first_since, "indexed_since": add_to_date(first_since, hours=-FIRST_LOOKBACK_HOURS)}  # fmt: skip
	where = _scope_filters(rule, params, prefix="b.") + _first_where(rule, kind, params)
	payload = kind == "ip"  # the second event's remote address (sequences.keep)
	pairs = frappe.db.sql(
		f"""select xb.value, b.name as b_name, b.`timestamp` as b_at, b.last_seen as b_last,
			greatest(b.last_seen, b.creation) as b_seen, b.category as b_category, b.host as b_host,
			b.bench as b_bench, b.site as b_site{", b.payload as b_payload" if payload else ""},
			max(a.last_seen) as a_last, min(a.`timestamp`) as a_at
		from `tabWolf Event` b
		join `tabWolf Event Entity` xb on xb.event = b.name and xb.kind = %(kind)s
		join `tabWolf Event Entity` xa on xa.kind = xb.kind and xa.value = xb.value and xa.event != b.name
			and xa.`at` >= %(indexed_since)s
		join `tabWolf Event` a on a.name = xa.event
		where b.category in %(then)s and b.last_seen between %(since)s and %(until)s
			and a.`timestamp` <= b.last_seen{"".join(f" and {w}" for w in where)}
		group by xb.value, b.name, b.`timestamp`, b.last_seen, b.creation, b.category, b.host, b.bench, b.site{", b.payload" if payload else ""}
		order by b.last_seen desc
		limit {MAX_PAIRS}""",
		params,
		as_dict=True,
	)
	kept = []
	for p in pairs:
		p.a_last, p.b_last = get_datetime(p.a_last), get_datetime(p.b_last)
		if payload:
			p.b_ip = _remote_ip(p.pop("b_payload"))
		if sequences.keep(p, kind, gap):
			kept.append(p)
	for p in kept[:MAX_LOOKUPS]:
		_first_event(rule, kind, p, gap)
	return sequences.group(kept, kind)


def _first_where(rule, kind, params):
	"""Conditions on the first event `a` (joined to the second `b`)."""
	where = ["a.category in %(first)s", "a.last_seen >= %(first_since)s"]
	if kind == "user":
		where.append("coalesce(a.site, '') = coalesce(b.site, '')")  # a user is per site
	if rule.get("first_min_severity"):
		where.append("a.severity in %(severities)s")
		params["severities"] = tuple(conditions.severities_at_least(rule.first_min_severity))
	return where


def _first_event(rule, kind, pair, gap):
	"""The newest first event of a kept pair, to link it and name its category."""
	params = {"kind": kind, "value": pair.value, "b": pair.b_name, "b_site": pair.b_site or "", "b_last": pair.b_last,
	          "first": tuple(sequences.categories(rule.first_categories)), "first_since": add_to_date(pair.b_last, minutes=-gap),
	          "indexed_since": add_to_date(pair.b_last, minutes=-gap, hours=-FIRST_LOOKBACK_HOURS)}  # fmt: skip
	where = [w.replace("coalesce(b.site, '')", "%(b_site)s") for w in _first_where(rule, kind, params)]
	rows = frappe.db.sql(
		f"""select a.name, a.category from `tabWolf Event Entity` xa join `tabWolf Event` a on a.name = xa.event
		where xa.kind = %(kind)s and xa.value = %(value)s and xa.event != %(b)s and xa.`at` >= %(indexed_since)s
			and a.`timestamp` <= %(b_last)s and {" and ".join(where)}
		order by a.last_seen desc
		limit 1""",
		params,
	)
	if rows:
		pair.a_name, pair.a_category = rows[0]


def _remote_ip(payload):
	try:
		data = json.loads(payload or "{}")
	except ValueError:
		return None
	return entities.normal_ip(data.get("ip")) if isinstance(data, dict) and data.get("ip") else None


def query_metric(rule, since):
	"""Aggregate the rule's metric per group over [since, now], at the resolution of the window."""
	agg = rule.aggregation or "avg"
	if agg not in conditions.AGGREGATIONS:
		frappe.throw(f"Unknown aggregation {agg}")
	until = _until()
	params = {"metric": rule.metric_name}
	where = ["metric_name = %(metric)s", *_scope_filters(rule, params)]
	cols = conditions.group_columns(rule.group_by)
	hints = [f for f in SCOPE_FIELDS if f not in cols]
	resolution = rollups.resolution_for((now_datetime() - since).total_seconds())
	return rollups.aggregate(where, params, cols, hints, agg, resolution, since, until, [rule.metric_name])


def _event_where(rule, since, params):
	params.update(event_type=rule.event_type, since=since, until=_until())
	where = [
		"event_type = %(event_type)s",
		"last_seen between %(since)s and %(until)s",
		*_scope_filters(rule, params),
	]
	if rule.event_category:
		where.append("category = %(category)s")
		params["category"] = rule.event_category
	if rule.min_severity:
		where.append("severity in %(severities)s")
		params["severities"] = tuple(conditions.severities_at_least(rule.min_severity))
	return where


def query_events(rule, since):
	params = {}
	where = _event_where(rule, since, params)
	select, group = _select_group(rule.group_by)
	rows = frappe.db.sql(
		f"""select {select}, sum(`count`) as value, count(*) as samples, min(`timestamp`) as first_at,
			max(greatest(last_seen, creation)) as last_at
		from `tabWolf Event`
		where {' and '.join(where)} {group}""",
		params,
		as_dict=True,
	)
	# Without group by, an empty table still yields one row of NULLs.
	return [r for r in rows if r.samples]


def matching_event_names(rule, since, row):
	params = {}
	where = _event_where(rule, since, params)
	for col in conditions.group_columns(rule.group_by):
		if row.get(col) is None:
			where.append(f"`{col}` is null")
		else:
			where.append(f"`{col}` = %(grp_{col})s")
			params[f"grp_{col}"] = row[col]
	return frappe.db.sql_list(
		f"select name from `tabWolf Event` where {' and '.join(where)} limit 500",
		params,
	)


def record_metric_alert(rule, incident, scope, summary):
	name = events.emit(
		"host_metric_alert",
		f"{rule.rule_name}: {summary}",
		severity=rule.severity,
		category=rule.metric_name,
		source="wolf",
		payload={"rule": rule.name, "summary": summary, "threshold": flt(rule.threshold)},
		host=scope.get("host"),
		bench=scope.get("bench"),
		site=scope.get("site"),
	)
	incidents.link_events(incident, [name])
