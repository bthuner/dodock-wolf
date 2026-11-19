"""The setup checklist for the Wolf UI (wolf/onboarding.py): what Wolf needs before it can wake
someone, read from what it already knows. Managers only: every step is configuration."""

import frappe

from dodock_wolf.api.ui import agent_cutoff
from dodock_wolf.wolf import health, inventory, onboarding
from dodock_wolf.wolf.spa import MANAGER_ROLES

# the docs site's pages in the reader's language, and the id of the scheduler section there
DOCS = {"fr": (onboarding.DOCS + "/fr", "rythme-du-planificateur")}


def test_accepted_at():
	"""Wolf Settings → Test Notification Accepted At, or None. Read raw: get_single_value turns an
	empty Datetime into datetime(1, 1, 1), which is true."""
	rows = frappe.db.sql("select value from `tabSingles` where doctype = 'Wolf Settings' and field = 'test_notification_ok_at'")
	return rows[0][0] if rows and rows[0][0] else None


def facts():
	_silence, cutoff = agent_cutoff()
	agents = [a for a in frappe.get_all("Wolf Agent", fields=["kind", "status", "last_seen", "setup_checked_at", "setup_failed"])
	          if (a.kind or "agent") == "agent" and a.status != "Disabled"]  # an empty kind is a host agent (api/scope.py)
	fresh = [a for a in agents if inventory.agent_state(a.status, a.last_seen, cutoff) == "fresh"]
	reported = [a for a in fresh if a.setup_checked_at]
	rules = frappe.get_all("Wolf Alert Rule", filters={"enabled": 1}, pluck="name")
	# the rows that hear a firing incident: escalation rows only hear an escalation (channels.select)
	channels = frappe.db.count("Wolf Alert Channel", {"parent": ("in", rules), "parenttype": "Wolf Alert Rule",
	                                                  "parentfield": "channels", "enabled": 1}) if rules else 0  # fmt: skip
	docs, anchor = DOCS.get((frappe.local.lang or "en").split("-")[0], (onboarding.DOCS, "scheduler-pace"))
	return {
		"agents": len(agents), "fresh": len(fresh),
		"setup_reported": len(reported), "setup_failing": sum(1 for a in reported if a.setup_failed),
		# the two cheap reads of health.get_health, not the queues it also reads
		"scheduler_enabled": health.scheduler_inactive_reason() is None, "tick_seconds": health.scheduler_tick_seconds(),
		"rules": len(rules), "channels": channels,
		# kept on Wolf Settings: deliveries are purged with the events (tasks.purge_old_data)
		"tested": bool(test_accepted_at()),
		"docs": docs, "scheduler_anchor": anchor,
	}  # fmt: skip


@frappe.whitelist()
def get_onboarding():
	frappe.only_for(MANAGER_ROLES)
	return onboarding.summary(onboarding.steps(facts()))
