"""Overlapping detectors at ingest (wolf/detectors.py): Wolf's own events dropped in `external`
mode while the external source reports, and a later event linked to the first as one finding in
`both` mode."""

import json

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from dodock_wolf.api import entities as entities_api
from dodock_wolf.wolf import detectors
from dodock_wolf.wolf.entities import normal_ip


class Dropper:
	"""`drop(event)` for one batch: whether an own-detector event goes, `external` mode only.

	The external source must have sent, in the last FALLBACK_MINUTES (by arrival), an alert that
	covers the detector and names the event's host under any of its names (Wolf Event Entity, so a
	Wazuh agent name, or a Suricata sensor's alert whose `dest_ip` is that host's address). That is
	read once per batch and host: an external alert later in the same batch counts from the next
	one, and a replayed spool is judged by what the external source sends now."""

	def __init__(self, settings=None):
		self.settings = settings or frappe.get_cached_doc("Wolf Settings")
		self.active = {}
		self.dropped = 0
		self._aliases = None

	def drop(self, event):
		if event.get("event_type") != "security":
			return False
		detector, side = detectors.detector_of(event.get("category"))
		if side != "own" or detectors.mode(self.settings, detector) != "external":
			return False
		if self._aliases is None:
			self._aliases = entities_api.aliases()
		host = self._aliases.host(event.get("host"))
		if not host:
			return False
		key = (detector, host)
		if key not in self.active:
			self.active[key] = covered(detector, host)
		if self.active[key]:
			self.dropped += 1
		return self.active[key]


def covered(detector, host):
	"""Whether the external source sent an alert covering `detector` about `host` lately."""
	rows = frappe.db.sql(
		"""select e.payload from `tabWolf Event Entity` x join `tabWolf Event` e on e.name = x.event
		where x.kind = 'host' and x.value = %(host)s and e.category in %(external)s and e.creation >= %(since)s
		order by e.creation desc
		limit 50""",
		{"host": host, "external": detectors.DETECTORS[detector]["external"],
		 "since": add_to_date(now_datetime(), minutes=-detectors.FALLBACK_MINUTES)},
	)  # fmt: skip
	for (payload,) in rows:
		try:
			if detectors.covers(detector, json.loads(payload or "{}")):
				return True
		except ValueError:
			continue
	return False


def record_dropped(agent, count):
	"""Own events an agent sent that gave way to an external source: counted on its Wolf Agent."""
	if agent and count:
		frappe.db.sql(
			"""update `tabWolf Agent` set own_events_dropped = coalesce(own_events_dropped, 0) + %(n)s,
			own_events_dropped_at = %(now)s where name = %(agent)s""",
			{"n": count, "now": now_datetime(), "agent": agent},
		)


def duplicate_of(data, payload):
	"""In `both` mode, the earlier event of the other side that this one is the same finding as."""
	detector, side = detectors.detector_of(data.get("category"))
	if not side or data.get("event_type") != "security":
		return None
	settings = frappe.get_cached_doc("Wolf Settings")
	if detectors.mode(settings, detector) != "both":
		return None
	ip = normal_ip(payload.get("ip")) if isinstance(payload, dict) else None
	if not ip:
		return None
	minutes = cint(settings.get("detector_match_minutes")) or 10
	at = get_datetime(data.get("timestamp") or now_datetime())
	rows = frappe.db.sql(
		"""select e.name, e.payload from `tabWolf Event` e
		join `tabWolf Event Entity` x on x.event = e.name and x.kind = 'ip' and x.value = %(ip)s
		where e.category in %(other)s and coalesce(e.duplicate_of, '') = ''
			and e.last_seen >= %(since)s and e.`timestamp` <= %(until)s
		order by e.last_seen desc
		limit 20""",
		{"ip": ip, "other": detectors.other_side(detector, side), "since": add_to_date(at, minutes=-minutes),
		 "until": add_to_date(at, minutes=minutes)},
	)  # fmt: skip
	for name, other in rows:
		try:
			other_payload = json.loads(other or "{}")
		except ValueError:
			other_payload = {}
		if detectors.same_finding(payload, other_payload):
			return name
	return None


def original_severities(rows):
	"""{original: severity} for the rows that are the same finding as an earlier event: an export
	skips a duplicate only when its original passed the same filter (a critical Wazuh alert linked
	to a warning auth.log event still goes to a collector that takes critical only)."""
	names = {r.get("duplicate_of") for r in rows if r.get("duplicate_of")}
	if not names:
		return {}
	return dict(frappe.db.sql("select name, severity from `tabWolf Event` where name in %s", (tuple(names),)))
