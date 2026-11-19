from contextlib import contextmanager
from datetime import timedelta

import frappe

from dodock_wolf.wolf import rollups
from dodock_wolf.wolf.catalog import REMOVED_METRICS
from dodock_wolf.wolf.presets import REMOVED_PRESETS

# stored in English, like every comment Wolf writes
REASON = "Disabled: removed in 0.2: Frappe Cloud v2 and Pilot report host resources (#136)."

# Deleted one metric at a time, so each step is a range of the (metric_name, time) index; one
# transaction per step: a step holds a few tens of thousands of rows of one metric, even with 100 hosts
STEPS = (
	(rollups.RAW_TABLE, "`timestamp`", None, timedelta(hours=4)),
	(f"tab{rollups.ROLLUP_DOCTYPE}", "bucket_start", rollups.MINUTE, timedelta(hours=6)),
	(f"tab{rollups.ROLLUP_DOCTYPE}", "bucket_start", rollups.HOUR, timedelta(days=14)),
)


def execute():
	"""Host resource metrics (CPU, memory, swap, disk, load) were removed in 0.2 (v0.1.0 keeps them):
	Frappe Cloud v2 and Pilot report them (#136, step 2c).

	The enabled rules on them, and the enabled presets that watched them, are disabled with a
	comment saying why, not deleted: their history stays. The open incidents of every such rule,
	enabled or not, are resolved, since nothing evaluates them any more: left alone they would stay
	open for good. Their samples and rollups are deleted, oldest first, in bounded transactions:
	they were most of a host's rows, and the hour rollups would otherwise stay for a year (hour
	retention). What was done is counted in an Error Log."""
	rules = matching_rules()
	disabled = disable_rules(rules)
	resolved = resolve_incidents(rules)
	deleted = delete_samples()
	if not (disabled or resolved or any(deleted.values())):
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


def matching_rules():
	"""Names of the metric rules on a removed metric and of the removed presets, enabled or not."""
	names = set(frappe.get_all("Wolf Alert Rule", pluck="name",
	                           filters={"signal_type": "metric", "metric_name": ("in", sorted(REMOVED_METRICS))}))  # fmt: skip
	names |= set(frappe.get_all("Wolf Alert Rule", filters={"name": ("in", REMOVED_PRESETS), "is_preset": 1}, pluck="name"))
	return sorted(names)


def disable_rules(rules):
	"""Disable the enabled ones, with a comment. A rule already disabled is left alone: its user
	disabled it (the comment would say otherwise), or an earlier run did (no second comment)."""
	if not rules:
		return []
	names = frappe.get_all("Wolf Alert Rule", filters={"name": ("in", rules), "enabled": 1}, pluck="name", order_by="name")
	for name in names:
		# set_value, not save: validate refuses an enabled rule on a removed metric
		frappe.db.set_value("Wolf Alert Rule", name, "enabled", 0, update_modified=False)
		frappe.get_doc("Wolf Alert Rule", name).add_comment("Comment", REASON)
	frappe.db.commit()
	return names


@contextmanager
def _journal_in_migrate():
	"""journal.capture skips during migrate and install, so that what they sync (fixtures, presets,
	settings) is not recorded as people's decisions. These resolutions are decisions the upgrade
	makes for the user: the journal must keep them."""
	saved = frappe.flags.in_migrate
	frappe.flags.in_migrate = False
	try:
		yield
	finally:
		frappe.flags.in_migrate = saved


def resolve_incidents(rules):
	"""Resolve the open incidents of the rules (their evaluation stopped), with the reason."""
	from dodock_wolf.wolf import incidents, notify

	if not rules:
		return []
	names = frappe.get_all("Wolf Incident", pluck="name", order_by="name",
	                       filters={"alert_rule": ("in", rules), "status": ("in", ("Open", "Acknowledged"))})  # fmt: skip
	reason = REASON.replace("Disabled: ", "Resolved: its rule was disabled, ", 1)
	for name in names:
		with _journal_in_migrate():
			incidents.resolve(name, reason)
		rule = frappe.db.get_value("Wolf Incident", name, "alert_rule")
		# Close the alert on PagerDuty-style channels, as the engine does. Never the rule's
		# notify_on_resolve channels: an upgrade must not page or mail people.
		if notify.has_stateful(rule):
			notify.enqueue(name, "resolved", only_stateful=True)
	frappe.db.commit()
	return names


def delete_samples():
	"""Delete the rows of each removed metric, oldest first. With `metric_name = %s`, finding the
	oldest row and deleting up to a bound are ranges of the (metric_name, time) index of the
	samples and the (resolution, metric_name, bucket_start) one of the rollups, never a scan."""
	counts = {"samples": 0, "rollups": 0}
	for table, column, resolution, step in STEPS:
		where = "metric_name = %(metric)s" + (" and resolution = %(res)s" if resolution is not None else "")
		for metric in sorted(REMOVED_METRICS):
			args = {"metric": metric, "res": resolution}
			counts["samples" if resolution is None else "rollups"] += frappe.db.sql(
				f"select count(*) from `{table}` where {where}", args
			)[0][0]
			oldest = frappe.db.sql(f"select min({column}) from `{table}` where {where}", args)[0][0]
			while oldest is not None:
				frappe.db.sql(f"delete from `{table}` where {where} and {column} < %(upper)s", {**args, "upper": oldest + step})
				frappe.db.commit()
				oldest = frappe.db.sql(f"select min({column}) from `{table}` where {where}", args)[0][0]
	return counts
