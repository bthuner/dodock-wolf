"""Incident lifecycle: open / update / resolve, event correlation and timelines."""

import ipaddress
import json

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from dodock_wolf.wolf import live, timeline
from dodock_wolf.wolf.conditions import describe_group
from dodock_wolf.wolf.events import scope_clause

OPEN = ("Open", "Acknowledged")


def find_open(rule, key):
	return frappe.db.get_value(
		"Wolf Incident",
		{"alert_rule": rule, "group_key": key, "status": ("in", OPEN)},
		"name",
		order_by="started_at desc",
	)


def find_recently_resolved(rule, key, minutes):
	if not minutes:
		return None
	return frappe.db.get_value(
		"Wolf Incident",
		{
			"alert_rule": rule,
			"group_key": key,
			"status": "Resolved",
			"resolved_at": (">=", add_to_date(now_datetime(), minutes=-cint(minutes))),
			# a merged incident stays closed; breaches go to its merge target instead
			"merged_into": ("is", "not set"),
		},
		"name",
		order_by="resolved_at desc",
	)


def latest_deployment(host=None, bench=None, site=None, minutes=30, before=None):
	before = before or now_datetime()
	clause, params = scope_clause(host, bench, site)
	params.update(since=add_to_date(before, minutes=-cint(minutes)), before=before)
	rows = frappe.db.sql(
		f"""select name, `timestamp` from `tabWolf Event`
		where event_type = 'deployment' and `timestamp` between %(since)s and %(before)s and {clause}
		order by `timestamp` desc limit 1""",
		params,
		as_dict=True,
	)
	return rows[0] if rows else None


def seen_when_resolved(rule, key, newest_at):
	"""True when the last resolved incident of (rule, key) was resolved after `newest_at`, the
	newest matching record: whoever resolved it had it in front of them. Any cooldown."""
	resolved_at = frappe.db.get_value(
		"Wolf Incident",
		{"alert_rule": rule, "group_key": key, "status": "Resolved", "merged_into": ("is", "not set")},
		"resolved_at",
		order_by="resolved_at desc",
	)
	return bool(resolved_at) and get_datetime(newest_at) <= get_datetime(resolved_at)


def open_incident(rule, key, scope, summary, started_at=None, newest_at=None):
	"""Create, update or reopen the incident for (rule, key).

	Returns (incident_name, kind) where kind is "fired", "reopened" or None when an
	already-open incident was just updated (no notification needed). Returns (None, None)
	when `newest_at` (the newest matching record, event rules) is not newer than the
	resolution of the just-resolved incident: whoever resolved it had already seen it.
	"""
	now = now_datetime()
	name = find_open(rule.name, key)
	kind = None
	if not name:
		from dodock_wolf.wolf.workflow import merge_target_for

		# Merged by hand into another open incident: keep feeding that one, notify nobody again.
		target = merge_target_for(rule.name, key)
		if target:
			frappe.db.set_value("Wolf Incident", target, "last_event_at", now, update_modified=False)
			live.incident_changed(target)
			return target, None
		if newest_at and seen_when_resolved(rule.name, key, newest_at):
			return None, None
		name = find_recently_resolved(rule.name, key, rule.cooldown_minutes)
		if name:
			kind = "reopened"
			frappe.db.set_value("Wolf Incident", name, {"status": "Open", "resolved_at": None, "resolved_by": None})
			from dodock_wolf.api import journal

			journal.incident_set(name, {"status": "Open"}, "reopened by its rule")
			# no Version records it: say it where the incident's activity is read
			frappe.get_doc("Wolf Incident", name).add_comment(
				"Info", f"Reopened by rule {rule.rule_name}: it matched again after the incident was resolved."
			)

	if name:
		frappe.db.set_value("Wolf Incident", name, {"last_event_at": now, "summary": summary})
		live.incident_changed(name)
		return name, kind

	settings = frappe.get_cached_doc("Wolf Settings")
	# the change that preceded the incident: a rule evaluates after the fact, and a deployment
	# made since the incident started (a fix, a migrate on restart) is not what came before it
	# made since the incident started (a fix, a migrate on restart) is not what came before it.
	# started_at can be early (a metric window's first sample): then the latest before now.
	where = (scope.get("host"), scope.get("bench"), scope.get("site"))
	minutes = cint(settings.deployment_window_minutes) or 30
	deploy = (started_at and latest_deployment(*where, minutes=minutes, before=min(get_datetime(started_at), now))) or (
		latest_deployment(*where, minutes=minutes, before=now)
	)
	doc = frappe.get_doc(
		{
			"doctype": "Wolf Incident",
			"title": f"{rule.rule_name}: {scope.get('label') or describe_group(rule.group_by, scope)}"[:255],
			"status": "Open",
			"severity": rule.severity,
			"alert_rule": rule.name,
			"group_key": key,
			"started_at": started_at or now,
			"last_event_at": now,
			"host": scope.get("host"),
			"bench": scope.get("bench"),
			"site": scope.get("site"),
			"summary": summary,
			"deployment_event": deploy.name if deploy else None,
			"deployment_at": deploy.timestamp if deploy else None,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name, "fired"


def resolve(name, reason="Condition cleared"):
	frappe.db.set_value(
		"Wolf Incident",
		name,
		{"status": "Resolved", "resolved_at": now_datetime(), "resolved_by": None, "summary": reason},
	)
	live.incident_changed(name)
	from dodock_wolf.api import journal

	journal.incident_set(name, {"status": "Resolved", "summary": reason}, "resolved automatically")


def link_events(incident, names):
	"""Link a rule's matching events to its incident. Events another incident took only because
	they share an IP or user with it (`incident_by_entity`, or outside that incident's scope) come
	over: a rule's evidence is its own."""
	if not names:
		return
	params = {"incident": incident, "names": tuple(names)}
	taken_from = [
		r[0]
		for r in frappe.db.sql(
			f"""select distinct e.incident from `tabWolf Event` e
			join `tabWolf Incident` i on i.name = e.incident
			where e.name in %(names)s and e.incident != %(incident)s
				and (e.incident_by_entity = 1 or {out_of_scope("e")})""",
			params,
		)
	]
	frappe.db.sql(
		f"""update `tabWolf Event` set incident = %(incident)s, incident_by_entity = 0
		where name in %(names)s and (coalesce(incident, '') = '' or incident = %(incident)s
			or incident_by_entity = 1 or exists (
			select 1 from `tabWolf Incident` i where i.name = `tabWolf Event`.incident
			and i.name != %(incident)s and {out_of_scope("`tabWolf Event`")}))""",
		params,
	)
	for other in taken_from:
		refresh_event_count(other)
	refresh_event_count(incident)


def refresh_event_count(incident):
	count = frappe.db.count("Wolf Event", {"incident": incident})
	frappe.db.set_value("Wolf Incident", incident, "event_count", count, update_modified=False)
	live.incident_changed(incident)


def out_of_scope(e):
	"""SQL: event `e` is linked to incident `i` outside i's own scope (an entity match took it)."""
	return f"""(coalesce(i.site, '') != coalesce({e}.site, '')
		or (coalesce(i.site, '') = '' and coalesce(i.bench, '') != '' and i.bench != coalesce({e}.bench, ''))
		or (coalesce(i.host, '') != '' and i.host != coalesce({e}.host, '')))"""


ENTITY_MINUTES = 60  # Wolf Settings.entity_correlation_minutes when unset
ENTITY_MAX_HOURS = 24  # an incident older than this takes no more events by entity
# attempts name the user the attacker chose, not the one who acted
ATTEMPT_CATEGORIES = ("frappe_failed_login", "ssh_failed_login", "sudo_failure", "password_reset_requested")


def correlation_keys(event_name, event):
	"""The (kind, value) pairs that tie this event to another scope's incident: its remote IP
	(`payload.ip`) when it is a public address, and its e-mail users unless the event is an
	attempt. A server's own or private address, "root" on two hosts or "Administrator" on two
	sites are not one party."""
	try:
		payload = json.loads(event.get("payload") or "{}")
	except (TypeError, ValueError):
		payload = {}
	from dodock_wolf.wolf.entities import normal_ip

	ip = normal_ip(payload.get("ip")) if isinstance(payload, dict) else None
	keys = []
	for kind, value in frappe.db.sql(
		"select kind, value from `tabWolf Event Entity` where event = %s and kind in ('ip', 'user')", event_name
	):
		if kind == "ip" and value == ip and ipaddress.ip_address(value).is_global:
			keys.append((kind, value))
		elif kind == "user" and "@" in value and event.get("category") not in ATTEMPT_CATEGORIES:
			keys.append((kind, value))
	return keys


def entity_incident(event_name, event):
	"""The open incident holding an event that shares a correlation key with this one, seen within
	Entity Correlation Minutes, whatever its source, host, bench or site (#72 step 5): a Suricata
	scan, a Wazuh SSH alert and a Frappe login from one IP read as one incident. Only incidents
	started in the last ENTITY_MAX_HOURS: a scanner that comes back every hour does not keep one
	incident growing for ever."""
	if event.get("event_type") != "security":
		return None
	settings = frappe.get_cached_doc("Wolf Settings")
	if not cint(settings.get("correlate_by_entity")):
		return None
	keys = correlation_keys(event_name, event)
	if not keys:
		return None
	minutes = cint(settings.get("entity_correlation_minutes")) or ENTITY_MINUTES
	at = get_datetime(event.get("timestamp") or now_datetime())
	params = {
		"event": event_name,
		"since": add_to_date(at, minutes=-minutes),
		"until": add_to_date(at, minutes=5),
		"started": add_to_date(now_datetime(), hours=-ENTITY_MAX_HOURS),
		"attempts": ATTEMPT_CATEGORIES,
	}
	match = []
	for n, (kind, value) in enumerate(keys):
		params[f"k{n}"], params[f"v{n}"] = kind, value
		match.append(f"(x.kind = %(k{n})s and x.value = %(v{n})s)")
	rows = frappe.db.sql(
		f"""select i.name from `tabWolf Event Entity` x
		join `tabWolf Event` e on e.name = x.event
		join `tabWolf Incident` i on i.name = e.incident
		where ({" or ".join(match)}) and x.event != %(event)s
			and (x.kind = 'ip' or coalesce(e.category, '') not in %(attempts)s)
			and coalesce(e.last_seen, e.`timestamp`) between %(since)s and %(until)s
			and i.status in ('Open', 'Acknowledged') and coalesce(i.merged_into, '') = ''
			and i.started_at >= %(started)s
		order by coalesce(e.last_seen, e.`timestamp`) desc
		limit 1""",
		params,
	)
	return rows[0][0] if rows else None


def adopt_related(incident, names):
	"""The other side of entity_incident, for an incident a rule just opened or reopened with its
	evidence (`names`): the security events sharing a correlation key with that evidence that no
	incident holds yet, within the bounds ingest uses (Entity Correlation Minutes before, 5 after;
	not for an incident older than ENTITY_MAX_HOURS; not info). They arrived before the incident
	opened: the rule runs every minute, nginx, Suricata and Wazuh report the same attack within one
	push, and would otherwise stay apart. They are marked `incident_by_entity`, and the incident
	starts at the earliest of them. Returns how many it took."""
	settings = frappe.get_cached_doc("Wolf Settings")
	if not names or not cint(settings.get("correlate_by_entity")):
		return 0
	started = frappe.db.get_value("Wolf Incident", incident, "started_at")
	if started and get_datetime(started) < add_to_date(now_datetime(), hours=-ENTITY_MAX_HOURS):
		return 0
	from dodock_wolf.wolf.entities import normal_ip

	evidence = {r.name: r for r in frappe.get_all(
		"Wolf Event", filters={"name": ("in", list(names)), "event_type": "security"},
		fields=["name", "category", "payload", "timestamp", "last_seen"])}  # fmt: skip
	if not evidence:
		return 0
	ips = {}
	for name, row in evidence.items():
		try:
			payload = json.loads(row.payload or "{}")
		except (TypeError, ValueError):
			payload = {}
		ips[name] = normal_ip(payload.get("ip")) if isinstance(payload, dict) else None
	keys = set()  # as correlation_keys, in one query for all the evidence
	for event, kind, value in frappe.db.sql(
		"select event, kind, value from `tabWolf Event Entity` where event in %(names)s and kind in ('ip', 'user')",
		{"names": tuple(evidence)},
	):
		if kind == "ip" and value == ips.get(event) and ipaddress.ip_address(value).is_global:
			keys.add((kind, value))
		elif kind == "user" and "@" in value and evidence[event].category not in ATTEMPT_CATEGORIES:
			keys.add((kind, value))
	if not keys:
		return 0
	times = [get_datetime(r.last_seen or r.timestamp) for r in evidence.values()]
	minutes = cint(settings.get("entity_correlation_minutes")) or ENTITY_MINUTES
	params = {
		"since": add_to_date(min(times), minutes=-minutes),
		"until": add_to_date(max(times), minutes=5),
		"attempts": ATTEMPT_CATEGORIES,
	}
	match = []
	for n, (kind, value) in enumerate(sorted(keys)):
		params[f"k{n}"], params[f"v{n}"] = kind, value
		match.append(f"(x.kind = %(k{n})s and x.value = %(v{n})s)")
	rows = frappe.db.sql(
		f"""select e.name, min(coalesce(e.last_seen, e.`timestamp`)) as seen from `tabWolf Event Entity` x
		join `tabWolf Event` e on e.name = x.event
		where ({" or ".join(match)}) and coalesce(e.incident, '') = '' and e.event_type = 'security'
			and e.severity != 'info'
			and (x.kind = 'ip' or coalesce(e.category, '') not in %(attempts)s)
			and coalesce(e.last_seen, e.`timestamp`) between %(since)s and %(until)s
		group by e.name
		order by seen
		limit 500""",
		params,
	)
	if not rows:
		return 0
	frappe.db.sql(
		"""update `tabWolf Event` set incident = %(incident)s, incident_by_entity = 1
		where name in %(names)s and coalesce(incident, '') = ''""",
		{"incident": incident, "names": tuple(r[0] for r in rows)},
	)
	earliest = get_datetime(rows[0][1])
	if not started or earliest < get_datetime(started):
		frappe.db.set_value("Wolf Incident", incident, "started_at", earliest, update_modified=False)
	refresh_event_count(incident)
	return len(rows)


def attach_to_open_incident(event_name, event):
	"""Correlate a freshly ingested event with an open incident: the one it is already linked to (a
	repeat folded into its record), or one sharing an IP or e-mail user with it (security events,
	entity_incident).

	Sharing a site, bench or host is not enough. An incident's evidence is what its rule matched
	(rules.py links it); the other events of its scope are context, which its timeline shows
	anyway. Attaching by scope made any event of a site evidence of the site's newest open
	incident, whatever that incident was about: 502 responses under "Server Script can run new
	code", and none under "502 spike after deployment"."""
	if event["severity"] == "info":
		return None
	current = frappe.db.get_value("Wolf Event", event_name, "incident")
	if current and frappe.db.get_value("Wolf Incident", current, "status") in OPEN:
		return _attach(event_name, event, current)
	incident = entity_incident(event_name, event)
	if incident:
		return _attach(event_name, event, incident, by_entity=True)
	return None


def _attach(event_name, event, incident, by_entity=None):
	values = {"incident": incident} if by_entity is None else {"incident": incident, "incident_by_entity": int(by_entity)}
	frappe.db.set_value("Wolf Event", event_name, values, update_modified=False)
	frappe.db.set_value("Wolf Incident", incident, "last_event_at", event["timestamp"], update_modified=False)
	refresh_event_count(incident)
	return incident


def incident_window(inc):
	"""(start, end, padding_minutes) of an incident's timeline: its start less the padding, to its
	resolution or now. Desk, the postmortem and the Wolf UI read the same window."""
	padding = cint(frappe.db.get_single_value("Wolf Settings", "timeline_padding_minutes")) or 30
	start = add_to_date(get_datetime(inc.started_at or inc.creation), minutes=-padding)
	end = get_datetime(inc.resolved_at) if inc.resolved_at else now_datetime()
	return start, end, padding


# What happened around an incident's events from other scopes: changes and health, not their noise.
HEALTH_TYPES = ("deployment", "error", "cron_failure", "worker_failure", "host_metric_alert")
HOST_WIDE_TYPES = ("deployment", "cron_failure", "worker_failure")  # of every site on a related host
MAX_RELATED_SCOPES = 10


def related_clause(inc):
	"""(" or (...)", params): deployments and health events of the scopes the incident's linked
	events came from beyond its own (timeline.related_scopes): a site's; a bench's on its host; on
	a host, its host-wide events and its benches' deployments and failed crons and workers, not
	the Error Logs of every site it serves."""
	linked = frappe.db.sql("select distinct host, bench, site from `tabWolf Event` where incident = %s", inc.name)
	scopes = timeline.related_scopes((inc.host, inc.bench, inc.site), linked, MAX_RELATED_SCOPES)
	parts, params = [], {}
	for n, (host, bench, site) in enumerate(scopes):
		if site:
			parts.append(f"`site` = %(rs_site{n})s")
		elif bench:
			parts.append(f"(`bench` = %(rs_bench{n})s" + (f" and `host` = %(rs_host{n})s)" if host else ")"))
		else:
			parts.append(f"(`host` = %(rs_host{n})s and (coalesce(`site`, '') = '' or `event_type` in %(host_wide_types)s))")
		params.update({f"rs_site{n}": site, f"rs_bench{n}": bench, f"rs_host{n}": host})
	if not parts:
		return "", {}
	params.update(health_types=HEALTH_TYPES, host_wide_types=HOST_WIDE_TYPES)
	return f" or (`event_type` in %(health_types)s and ({' or '.join(parts)}))", params


def get_timeline(incident, limit=300):
	"""Events linked to the incident, everything in its scope during its window, and the health
	events and deployments of the scopes its events came from (related_clause). Linked events come
	first under the limit: context never pushes evidence out."""
	inc = frappe.get_doc("Wolf Incident", incident) if isinstance(incident, str) else incident
	start, end, _padding = incident_window(inc)
	# an incident without any scope has no context of its own: "same scope" would mean every site
	clause, params = scope_clause(inc.host, inc.bench, inc.site) if (inc.host or inc.bench or inc.site) else ("1=0", {})
	related, related_params = related_clause(inc)
	params.update(related_params, incident=inc.name, start=start, end=end, limit=cint(limit))
	rows = frappe.db.sql(
		f"""select name, title, event_type, category, severity, source, `timestamp`, last_seen,
			`count`, host, bench, site, incident, duplicate_of, payload
		from `tabWolf Event`
		where incident = %(incident)s
			or (`timestamp` between %(start)s and %(end)s and ({clause}{related}))
		order by case when incident = %(incident)s then 0 else 1 end, `timestamp` desc
		limit %(limit)s""",
		params,
		as_dict=True,
	)
	return sorted(rows, key=lambda r: (get_datetime(r.timestamp), r.name))


def parse_payload(row):
	try:
		return json.loads(row.get("payload") or "{}")
	except ValueError:
		return {}
