"""The setup checklist (#23): from a fresh install to a first test alert, what is done and what is
next, each step read from what Wolf already knows (no flag to tick by hand).

Pure: `steps(facts)` takes plain facts gathered by api/onboarding.py, so it is unit tested
without a bench. The text is in the reader's language (wolf/i18n.py), built per request.
"""

from dodock_wolf.wolf.i18n import _, fmt

DOCS = "https://bthuner.github.io/dodock-wolf"


def _step(id, done, title, detail, label=None, href=None):
	return {"id": id, "done": bool(done), "title": title, "detail": detail,
	        "action": {"label": label, "href": href} if label and href else None}  # fmt: skip


def steps(facts):
	"""The checklist, in the order to do it. `facts`:

	- agents: registered host agents; fresh: those reporting now;
	- setup_reported, setup_failing: reporting agents that sent their host setup, and those with a
	  failed check (wolf-agent doctor, run every hour);
	- scheduler_enabled, tick_seconds: Frappe's scheduler and its tick (rules run at that pace);
	- rules: enabled alert rules; channels: enabled channel rows on enabled rules;
	- tested: a test notification that a channel accepted;
	- docs: the documentation's base URL (the language's own pages), scheduler_anchor the id of
	  its "Scheduler pace" section.
	"""
	docs = facts.get("docs") or DOCS
	agents, fresh = facts.get("agents", 0), facts.get("fresh", 0)
	reported, failing = facts.get("setup_reported", 0), facts.get("setup_failing", 0)
	tick = facts.get("tick_seconds")
	out = [
		_step("agent", agents,
		      _("Install the agent on a host"),
		      (_("1 agent registered") if agents == 1 else fmt(_("{0} agents registered"), agents)) if agents else _("No host agent has registered with this site yet."),
		      _("How to install it"), f"{docs}/install/wolf-agent"),  # fmt: skip
		_step("reporting", fresh,
		      _("The agent reports"),
		      fmt(_("{0} of {1} reporting"), fresh, agents) if agents else _("Waiting for a first agent."),
		      _("Monitoring"), "/wolf/monitoring"),  # fmt: skip
		_step("host_setup", reported and not failing,
		      _("Each host gives the agent what it needs"),
		      (fmt(_("{0} host to fix") if failing == 1 else _("{0} hosts to fix"), failing) if failing
		       else _("Every reporting agent has what it needs.") if reported
		       else _("Agents check their host every hour; none has reported yet.")),
		      _("Monitoring"), "/wolf/monitoring"),  # fmt: skip
		_step("scheduler", facts.get("scheduler_enabled") and tick and tick <= 60,
		      _("Rules run every minute"),
		      (_("The scheduler is disabled: no rule runs.") if not facts.get("scheduler_enabled")
		       else fmt(_("Frappe's scheduler ticks every {0} s: set scheduler_tick_interval to 60."), tick)
		       if tick and tick > 60 else _("The scheduler runs every minute.")),
		      _("Scheduler pace"), f"{docs}/install/wolf-app#{facts.get('scheduler_anchor') or 'scheduler-pace'}"),  # fmt: skip
		_step("rules", facts.get("rules", 0),
		      _("Alert rules are on"),
		      (_("1 rule enabled") if facts.get("rules") == 1 else fmt(_("{0} rules enabled"), facts.get("rules", 0))) if facts.get("rules") else _("No alert rule is enabled."),
		      _("Alert rules"), "/app/wolf-alert-rule"),  # fmt: skip
		_step("channel", facts.get("channels", 0),
		      _("A rule tells someone"),
		      (fmt(_("{0} enabled channels"), facts["channels"]) if facts.get("channels", 0) > 1
		       else _("1 enabled channel") if facts.get("channels") else _("No enabled rule has an enabled channel: incidents show in Wolf only.")),
		      _("Channels"), f"{docs}/alerts/channels"),  # fmt: skip
		_step("test", facts.get("tested"),
		      _("A test notification reached its channel"),
		      (_("A channel accepted a test notification.") if facts.get("tested")
		       else _("Open a rule with a channel and use Send test notification.")),
		      _("Alert rules"), "/app/wolf-alert-rule"),  # fmt: skip
	]
	return out


def summary(items):
	return {"done": sum(1 for s in items if s["done"]), "total": len(items), "steps": items}
