"""Overlapping detectors at ingest (wolf/detectors.py): Wolf's own events dropped in `external`
mode while the external source reports, and a later event linked to the first as one finding in
`both` mode."""

import json

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from dodock_wolf.wolf import detectors
from dodock_wolf.wolf.entities import normal_ip


class Dropper:
	"""`drop(event)` for one batch: whether an own-detector event goes, `external` mode only. Whether
	the external source reported from a host is read once per batch."""

	def __init__(self, settings=None):
		self.settings = settings or frappe.get_cached_doc("Wolf Settings")
		self.active = {}
		self.dropped = 0

	def drop(self, event):
		if event.get("event_type") != "security":
			return False
		detector, side = detectors.detector_of(event.get("category"))
		if side != "own" or detectors.mode(self.settings, detector) != "external":
			return False
		key = (detector, event.get("host") or "")
		if key not in self.active:
			self.active[key] = bool(frappe.db.sql(
				"""select 1 from `tabWolf Event` where category in %(external)s and coalesce(host, '') = %(host)s
				and creation >= %(since)s limit 1""",
				{"external": detectors.DETECTORS[detector]["external"], "host": key[1],
				 "since": add_to_date(now_datetime(), minutes=-detectors.FALLBACK_MINUTES)},
			))  # fmt: skip
		if self.active[key]:
			self.dropped += 1
		return self.active[key]


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
