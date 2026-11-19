from datetime import timedelta

import frappe

from dodock_wolf.wolf import rollups
from dodock_wolf.wolf.catalog import REMOVED_METRICS
from dodock_wolf.wolf.presets import REMOVED_PRESETS

# stored in English, like every comment Wolf writes
REASON = "Disabled: removed in 0.2: Frappe Cloud v2 and Pilot report host resources (#136)."

# one transaction per step: a step holds at most a few hundred thousand rows, even with 100 hosts
STEPS = (
	(rollups.RAW_TABLE, "`timestamp`", None, timedelta(hours=1)),
	(f"tab{rollups.ROLLUP_DOCTYPE}", "bucket_start", rollups.MINUTE, timedelta(hours=1)),
	(f"tab{rollups.ROLLUP_DOCTYPE}", "bucket_start", rollups.HOUR, timedelta(days=3)),
)


def execute():
	"""Host resource metrics (CPU, memory, swap, disk, load) were removed in 0.2 (v0.1.0 keeps them):
	Frappe Cloud v2 and Pilot report them (#136, step 2c).

	The rules on them, and the presets that watched them, are disabled with a comment saying why,
	not deleted: their history stays. Their open incidents are resolved, since nothing evaluates
	them any more: left alone they would stay open for good. Their samples and rollups are deleted,
	oldest first, in bounded transactions: they were most of a host's rows, and the hour rollups
	would otherwise stay for a year (hour retention). What was done is counted in an Error Log."""
	disabled = disable_rules()
	resolved = resolve_incidents(disabled)
	deleted = delete_samples()
	if not (disabled or any(deleted.values())):
		return
	message = (
		f"Host resource metrics were removed in Dodock Wolf 0.2: {len(disabled)} alert rule(s) on them "
		f"were disabled ({', '.join(disabled) or 'none'}), {len(resolved)} open incident(s) of theirs were "
		f"resolved ({', '.join(resolved) or 'none'}), and {deleted['samples']} sample(s) and "
		f"{deleted['rollups']} rollup(s) of them were deleted. Read host resources in Frappe Cloud v2 "
		"or Pilot, or stay on Dodock Wolf v0.1.0."
	)
	print(message)
	frappe.log_error(title="Dodock Wolf 0.2: host resource metrics removed", message=message)


def disable_rules():
	"""Names of the rules disabled: those on a removed metric, and the removed presets."""
	names = set(frappe.get_all("Wolf Alert Rule", filters={"metric_name": ("in", sorted(REMOVED_METRICS))}, pluck="name"))
	names |= set(frappe.get_all("Wolf Alert Rule", filters={"name": ("in", REMOVED_PRESETS), "is_preset": 1}, pluck="name"))
	for name in sorted(names):
		frappe.db.set_value("Wolf Alert Rule", name, "enabled", 0, update_modified=False)
		frappe.get_doc("Wolf Alert Rule", name).add_comment("Comment", REASON)
	frappe.db.commit()
	return sorted(names)


def resolve_incidents(rules):
	"""Resolve the open incidents of the disabled rules (their evaluation stopped), with the reason."""
	from dodock_wolf.wolf import incidents

	if not rules:
		return []
	names = frappe.get_all("Wolf Incident", pluck="name", order_by="name",
	                       filters={"alert_rule": ("in", rules), "status": ("in", ("Open", "Acknowledged"))})  # fmt: skip
	for name in names:
		incidents.resolve(name, REASON.replace("Disabled: ", "Resolved: its rule was disabled, ", 1))
	frappe.db.commit()
	return names


def delete_samples():
	params = {"metrics": tuple(sorted(REMOVED_METRICS))}
	counts = {"samples": 0, "rollups": 0}
	for table, column, resolution, step in STEPS:
		where = "metric_name in %(metrics)s" + (" and resolution = %(res)s" if resolution is not None else "")
		args = {**params, "res": resolution}
		counts["samples" if resolution is None else "rollups"] += frappe.db.sql(
			f"select count(*) from `{table}` where {where}", args
		)[0][0]
		oldest = frappe.db.sql(f"select min({column}) from `{table}` where {where}", args)[0][0]
		while oldest is not None:
			frappe.db.sql(f"delete from `{table}` where {where} and {column} < %(upper)s", {**args, "upper": oldest + step})
			frappe.db.commit()
			oldest = frappe.db.sql(f"select min({column}) from `{table}` where {where}", args)[0][0]
	return counts
