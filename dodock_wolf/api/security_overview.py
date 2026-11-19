"""The Wolf UI's home page (`/wolf`): the security of the bench at a glance (#136, step 2b).

One read, `get_overview()`, with a panel per question, each within the reader's access and
each failing on its own (a panel that cannot be read says so; the others still show):

- `scores`: the stored `security_score` of each site (api/security.record_security_scores,
  hourly), its age and the change from about 24 h earlier. The posture is not recomputed here.
- `incidents`: open or acknowledged incidents holding a security event, as the incident access
  rules let the reader see them. None on a satellite, which keeps no incidents.
- `responses`: response actions waiting for their agent or satellite, and those that failed in
  the last days. Managers only (the ones who approve them, api/response.py).
- `journal`: the tamper-evident journal's signing. Managers only (api/journal.get_status).
- `agents`: the agents' states and the hosts whose setup checks found something to fix.
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from dodock_wolf import satellite
from dodock_wolf.api import dashboard, security
from dodock_wolf.api import journal as journal_api
from dodock_wolf.api.scope import UNRESOLVED
from dodock_wolf.api.ui import READ_ROLES, agent_cutoff
from dodock_wolf.wolf import access, events, response, rollups, security_overview, storage, window
from dodock_wolf.wolf.spa import MANAGER_ROLES

SCORE_METRIC = "security_score"
SCORE_LOOKBACK = timedelta(days=7)  # an older score is not the site's current one
# "about 24 h earlier": the newest score of this window
BEFORE_SINCE, BEFORE_UNTIL = timedelta(hours=25), timedelta(hours=23)
NEWEST = 5
FAILED_DAYS = 7
SAVEPOINT = "wolf_security_overview"


def _manager():
	return frappe.session.user == "Administrator" or bool(set(frappe.get_roles()) & set(MANAGER_ROLES))


def _panel(read):
	"""A panel's answer, or what stopped it: {"forbidden": true} or {"error": ...}. Inside a
	savepoint, so a failed statement (which aborts a Postgres transaction) spares the others."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		out = read()
	except frappe.PermissionError:
		frappe.db.rollback(save_point=SAVEPOINT)
		return {"forbidden": True}
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		# a GET request's transaction is rolled back: the Error Log is inserted after it
		frappe.log_error(title="Wolf security overview", defer_insert=True)
		return {"error": _("Wolf could not read this panel: the reason is in the Error Log.")}
	frappe.db.release_savepoint(SAVEPOINT)
	return out


def _scores(now, tz):
	allowed, params = access.sql_condition("Wolf Metric Rollup")  # samples have the same columns
	where = ["metric_name = %(metric)s", "coalesce(site, '') != ''", *([allowed.removeprefix(" and ")] if allowed else [])]
	params = {**params, "metric": SCORE_METRIC}

	def newest(since, until):
		rows = rollups.aggregate(where, params, ["site"], [], "last", storage.HOUR, since, until, [SCORE_METRIC])
		# a score is stored with its site's host too, so a host grant reaches it: keep the sites
		# the reader may open by site, as the Security page does (api/security.list_sites)
		return {r.site: r for r in rows if access.visible("Wolf Metric Sample", {"site": r.site})}

	current = newest(now - SCORE_LOOKBACK, now)
	before = newest(now - BEFORE_SINCE, now - BEFORE_UNTIL)
	rows = security_overview.score_rows(
		security.list_sites(),
		{site: (r.value, get_datetime(r.last_at)) for site, r in current.items()},
		{site: r.value for site, r in before.items()},
		now,
	)
	for r in rows:
		r["at"] = window.to_utc(r["at"], tz) if r["at"] else None
	return {
		"sites": rows,
		"late_hours": security_overview.SCORE_LATE.total_seconds() / 3600,
		"lookback_days": SCORE_LOOKBACK.days,
	}


def _incidents(tz):
	allowed, params = access.sql_condition("Wolf Incident", table="i")
	params["unresolved"] = UNRESOLVED
	# merged incidents are counted in the one they went into, as everywhere else (api/scope.py)
	where = f"""i.status in %(unresolved)s and coalesce(i.merged_into, '') = ''
		and exists (select 1 from `tabWolf Event` e where e.incident = i.name and e.event_type = 'security'){allowed}"""
	counts = frappe.db.sql(
		f"select i.severity, i.status, count(*) as n from `tabWolf Incident` i where {where} group by i.severity, i.status",
		params,
		as_dict=True,
	)
	newest = frappe.db.sql(
		f"""select i.name, i.title, i.status, i.severity, i.site, i.bench, i.host, i.started_at
		from `tabWolf Incident` i where {where} order by i.started_at desc, i.name desc limit {NEWEST}""",
		params,
		as_dict=True,
	)
	by_status = dict.fromkeys(UNRESOLVED, 0)
	for r in counts:
		by_status[r.status] = by_status.get(r.status, 0) + cint(r.n)
	return {
		"by_severity": security_overview.severity_counts((r.severity, r.n) for r in counts),
		"by_status": by_status,
		"newest": [
			{"name": r.name, "title": r.title, "status": r.status, "severity": r.severity or "info",
			 "site": r.site, "bench": r.bench, "host": r.host, "started_at": window.to_utc(r.started_at, tz)}  # fmt: skip
			for r in newest
		],
	}


def _label(r):
	# a user action with an agent waits for a satellite: its user is named with the site (api/response.py)
	remote = r.action in response.USER_ACTIONS and r.agent
	try:
		return response.label(r.action, r.target, r.duration_hours, r.host, [r.executor] if r.executor else None, translate=True,
		                      site=r.site if remote else None)  # fmt: skip
	except KeyError:
		return f"{r.action} {r.target}"


def _responses(now, tz):
	allowed, params = access.sql_condition("Wolf Response Action")
	params.update(since=add_to_date(now, days=-FAILED_DAYS), now=now)
	# Approved is the state of an action waiting for the agent or satellite that applies it
	# (api/response.pending_for_agent, which skips an expired one); one applied on this site or by
	# Wazuh leaves it at once
	waiting_now = "status = 'Approved' and expires_at > %(now)s"
	waiting, failed = frappe.db.sql(
		f"""select sum(case when {waiting_now} then 1 else 0 end),
			sum(case when status = 'Failed' and modified >= %(since)s then 1 else 0 end)
		from `tabWolf Response Action` where status in ('Approved', 'Failed'){allowed}""",
		params,
	)[0]
	newest = frappe.db.sql(
		f"""select name, action, target, status, executor, agent, host, site, duration_hours, incident, result, modified
		from `tabWolf Response Action`
		where (({waiting_now}) or (status = 'Failed' and modified >= %(since)s)){allowed}
		order by modified desc, name desc limit {NEWEST}""",
		params,
		as_dict=True,
	)
	return {
		"waiting": cint(waiting),
		"failed": cint(failed),
		"failed_days": FAILED_DAYS,
		"newest": [
			{"name": r.name, "label": _label(r), "status": r.status, "incident": r.incident, "host": r.host, "site": r.site,
			 "result": r.result if r.status == "Failed" else None, "at": window.to_utc(r.modified, tz)}  # fmt: skip
			for r in newest
		],
	}


def _journal(now, tz):
	s = journal_api.signing()
	state = security_overview.journal_state(s["last_seq"], s["last_at"], s["pending"],
	                                        get_datetime(s["oldest_pending_at"]) if s["oldest_pending_at"] else None, now)  # fmt: skip
	return {
		**state,
		"last_at": window.to_utc(get_datetime(state["last_at"]), tz) if state["last_at"] else None,
		"oldest_pending_at": window.to_utc(state["oldest_pending_at"], tz) if state["oldest_pending_at"] else None,
		"key": s["key"],
		"late_minutes": int(security_overview.SIGNING_LATE.total_seconds() // 60),
	}


def _agents(tz):
	silence, cutoff = agent_cutoff()
	return {**security_overview.agent_summary(dashboard.monitored_agents(tz, cutoff)), "silence_minutes": silence}


@frappe.whitelist()
def get_overview():
	"""The home page's panels, each within the reader's access; see the module docstring."""
	frappe.only_for(READ_ROLES)
	now, tz = now_datetime(), events.system_tz()
	manager = _manager()
	central = not satellite.is_satellite()  # a satellite keeps no incidents, so no response either
	return {
		"restricted": access.grants() is not None,
		"scores": _panel(lambda: _scores(now, tz)),
		"incidents": _panel(lambda: _incidents(tz)) if central else None,
		"responses": _panel(lambda: _responses(now, tz)) if manager and central else None,
		"journal": _panel(lambda: _journal(now, tz)) if manager else None,
		"agents": _panel(lambda: _agents(tz)),
		"checked_at": window.to_utc(now, tz),
		"time_zone": tz,
	}
