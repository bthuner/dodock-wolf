"""Assessment of Wolf's own heartbeat (docs/protocol.md §4).

Kept free of frappe imports so it can be unit tested without a bench. The agent
watchdog (agent/wolf_agent/watchdog.py) mirrors `assess`; keep the two in sync.

The problems are English by default: agents put them in their own alerts and report_stall
stores them. Pass `_` (wolf.i18n._) for the reader's language, as health.for_display does.
"""

from datetime import timezone
from zoneinfo import ZoneInfo

from dodock_wolf.wolf.i18n import fmt

STALE_MINUTES = 5


def to_utc_iso(dt, tz_name):
	"""Naive datetime in the site time zone → `YYYY-MM-DDTHH:MM:SSZ`, or None."""
	if dt is None:
		return None
	return dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_seconds(then, now):
	"""Signed age in seconds: negative when `then` lies in the future."""
	if then is None:
		return None
	return int((now - then).total_seconds())


def _english(text):
	return text


def _context(health, _):
	scheduler = health.get("scheduler") or {}
	queues = health.get("queues") or {}
	notes = []
	if scheduler.get("enabled") is False:
		notes.append(fmt(_("scheduler disabled ({0})"), scheduler.get("reason") or _("unknown reason")))
	if queues.get("error"):
		notes.append(fmt(_("job queue unreachable: {0}"), queues["error"]))
	elif queues.get("workers") == 0:
		notes.append(_("no background worker running"))
	return notes


def assess(health, stale_minutes=STALE_MINUTES, _=_english):
	"""Return the problems found in a health dict, as short sentences (empty = healthy).

	Only lasting conditions raise a problem: a paused scheduler, a Redis blip or a burst of
	pushes during a deployment is normal for a minute or two.
	"""
	if not isinstance(health, dict):
		return []
	return [p for p in (staleness(health, stale_minutes, _), ingest_backlog(health, stale_minutes, _)) if p]


def _limit(stale_minutes):
	return max(float(stale_minutes or STALE_MINUTES), 0.1) * 60


def staleness(health, stale_minutes=STALE_MINUTES, _=_english):
	"""Rules (or scheduled jobs) not run for `stale_minutes`, with context; None if fresh."""
	if not isinstance(health, dict):
		return None
	limit = _limit(stale_minutes)
	rules_age = (health.get("rules") or {}).get("age_seconds")
	job_age = (health.get("scheduler") or {}).get("age_seconds")
	rules = rules_age is not None
	age = rules_age if rules else job_age
	if age is None:
		return None

	if age >= limit:
		template = _("alert rules not evaluated for {0} min") if rules else _("scheduled jobs not evaluated for {0} min")
		problem = fmt(template, int(age // 60))
	elif age <= -limit:
		# A time-zone change leaves stored times in the future: the scheduler then
		# considers nothing due until that time is reached.
		template = (_("last run of alert rules is {0} min in the future (time zone changed?)") if rules
		            else _("last run of scheduled jobs is {0} min in the future (time zone changed?)"))  # fmt: skip
		problem = fmt(template, int(-age // 60))
	else:
		return None
	notes = _context(health, _)
	return problem + (f"; {', '.join(notes)}" if notes else "")


def ingest_backlog(health, stale_minutes=STALE_MINUTES, _=_english):
	"""Queued pushes waiting `stale_minutes` for a worker; None otherwise.

	Agents get their answer before a queued push is stored, so their heartbeat stays fresh
	while the telemetry waits in Redis, and rules see none of it.
	"""
	if not isinstance(health, dict):
		return None
	queues = health.get("queues") or {}
	age = queues.get("ingest_backlog_seconds")
	if not isinstance(age, (int, float)) or age < _limit(stale_minutes):
		return None
	problem = fmt(_("pushes waiting {0} min in the {1} queue, not stored yet"), int(age // 60), queues.get("ingest_queue") or "ingest")
	if queues.get("workers") == 0:
		problem += "; " + _("no background worker running")
	return problem
