"""The setup checklist for the Wolf UI (wolf/onboarding.py): what Wolf needs before it can wake
someone, read from what it already knows. Managers only: every step is configuration."""

import frappe

from dodock_wolf.api.ui import agent_cutoff
from dodock_wolf.wolf import health, inventory, onboarding
from dodock_wolf.wolf.spa import MANAGER_ROLES

# the docs site's pages in the reader's language, and the id of the scheduler section there
DOCS = {"fr": (onboarding.DOCS + "/fr", "rythme-du-planificateur")}


def facts():
	_silence, cutoff = agent_cutoff()
	agents = frappe.get_all("Wolf Agent", filters={"kind": ("not in", ("satellite", "integration"))},
	                        fields=["status", "last_seen", "setup_checked_at", "setup_failed"])  # fmt: skip
	fresh = [a for a in agents if inventory.agent_state(a.status, a.last_seen, cutoff) == "fresh"]
	reported = [a for a in fresh if a.setup_checked_at]
	scheduler = (health.safe_health() or {}).get("scheduler") or {}
	rules = frappe.get_all("Wolf Alert Rule", filters={"enabled": 1}, pluck="name")
	channels = frappe.db.count("Wolf Alert Channel", {"parent": ("in", rules), "parenttype": "Wolf Alert Rule",
	                                                  "enabled": 1}) if rules else 0  # fmt: skip
	docs, anchor = DOCS.get((frappe.local.lang or "en").split("-")[0], (onboarding.DOCS, "scheduler-pace"))
	return {
		"agents": len(agents), "fresh": len(fresh),
		"setup_reported": len(reported), "setup_failing": sum(1 for a in reported if a.setup_failed),
		"scheduler_enabled": bool(scheduler.get("enabled")), "tick_seconds": scheduler.get("tick_seconds"),
		"rules": len(rules), "channels": channels,
		"tested": bool(frappe.db.exists("Wolf Delivery", {"kind": "test", "ok": 1})),
		"docs": docs, "scheduler_anchor": anchor,
	}  # fmt: skip


@frappe.whitelist()
def get_onboarding():
	frappe.only_for(MANAGER_ROLES)
	return onboarding.summary(onboarding.steps(facts()))
