"""Human-validated response actions (wolf/response.py): suggest, approve, apply, audit.

- `get_response(incident)`: what Wolf proposes from the incident's security events, and the
  actions already taken (Wolf Response Action rows).
- `approve(...)` (POST, Wolf Manager / System Manager): the confirmation. It records a Wolf
  Response Action per executor and a comment on the incident. User actions apply at once on
  this site. A `block_ip` for the Wolf Agent waits for its next push (`pending_for_agent`),
  which applies it on its host and reports back (`record_results`); agents only act when their
  own config allows it (`response.enabled`, off by default). One for Wazuh runs at once through
  the manager's API (api/wazuh_ar.py).
- `expire_actions` (hourly): blocks whose time is over are marked Expired (the nftables entry
  expires by itself on the host).
"""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from dodock_wolf.api import entities as entities_api
from dodock_wolf.api import wazuh_ar as wazuh_ar_api
from dodock_wolf.wolf import events, response, wazuh_ar
from dodock_wolf.wolf.spa import MANAGER_ROLES

EVENT_LIMIT = 500
RESULT_LENGTH = 500


def _incident(name):
	doc = frappe.get_doc("Wolf Incident", name)
	if not frappe.has_permission("Wolf Incident", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc


def _events(incident):
	rows = frappe.get_all(
		"Wolf Event",
		filters={"incident": incident, "event_type": "security"},
		fields=["event_type", "category", "title", "agent", "host", "bench", "site", "payload"],
		order_by="timestamp desc",
		limit=EVENT_LIMIT,
	)
	aliases = entities_api.aliases()
	senders = {r.name: r for r in frappe.get_all("Wolf Agent", fields=["name", "hostname", "kind"],
	                                             filters={"name": ("in", list({r.agent for r in rows if r.agent}) or [""])})}  # fmt: skip
	agents = _wolf_agents(aliases)
	for r in rows:
		try:
			r["payload"] = json.loads(r.payload) if r.payload else {}
		except ValueError:
			r["payload"] = {}
		# the attacked host, under its canonical name (a Wazuh agent name or an FQDN resolves to it):
		# for a Suricata or Wazuh alert the host it names, else the sending agent's own
		# (response.attacked_host); and the Wolf Agent running there
		sender = senders.get(r.agent) or frappe._dict()
		r["block_host"] = aliases.host(response.attacked_host(r, sender.kind or ("agent" if r.agent else None), sender.hostname))
		r["block_agent"] = agents.get(r["block_host"])
	return rows


def _wolf_agents(aliases):
	"""{canonical host: Wolf Agent} for the active agents that can apply a block on their host."""
	rows = frappe.get_all("Wolf Agent", filters={"status": ("!=", "Disabled")}, fields=["name", "hostname", "kind"],
	                      order_by="last_seen asc")  # fmt: skip
	# satellites and integrations never apply anything; the latest seen agent of a host wins
	return {aliases.host(r.hostname): r.name for r in rows if r.hostname and (r.kind or "agent") == "agent"}


def _actions(incident):
	return frappe.get_all(
		"Wolf Response Action",
		filters={"incident": incident},
		fields=["name", "action", "target", "status", "agent", "executor", "host", "duration_hours", "approved_by",
		        "approved_at", "applied_at", "expires_at", "result", "reason"],  # fmt: skip
		order_by="creation desc",
	)


def _is_manager():
	return frappe.session.user == "Administrator" or bool(set(frappe.get_roles()) & set(MANAGER_ROLES))


def _key(action, target, host, executor=None, aliases=None):
	"""A block is one address on one host by one executor; a user action, one user."""
	if action != "block_ip":
		return (action, str(target), None, None)
	canonical = (aliases or entities_api.aliases()).host(host)  # rows before #72 step 6 kept the agent's hostname
	return (action, str(target), canonical, executor or "wolf_agent")


def _proposals(doc):
	"""What Wolf proposes for this incident now (approve() only accepts one of these). A block is
	proposed for the executors that have not applied it yet: a failed Wazuh half can be retried
	while the Wolf Agent's half waits."""
	aliases = entities_api.aliases()
	taken = {_key(a.action, a.target, a.host, a.executor, aliases) for a in _actions(doc.name)
	         if a.status in ("Approved", "Applied")}  # fmt: skip
	settings = frappe.get_cached_doc("Wolf Settings")
	proposals = []
	for p in response.suggest(_events(doc.name), settings.get("block_with") or "wolf_agent", wazuh_ar_api.enabled(settings)):
		if p["action"] == "block_ip":
			p["executors"] = [e for e in p["executors"] if _key("block_ip", p["target"], p["host"], e, aliases) not in taken]
			if not p["executors"]:
				continue
			if "wolf_agent" not in p["executors"]:
				p["agent"] = None
		elif _key(p["action"], p["target"], None) in taken:
			continue
		if p["action"] in response.USER_ACTIONS and not frappe.db.exists("User", p["target"]):
			continue  # a failed login for an unknown name: nothing to disable
		p["label"] = response.label(p["action"], p["target"], _hours(p, settings), p["host"], p.get("executors"),
		                            wazuh_hours=_wazuh_hours(settings))  # fmt: skip
		proposals.append(p)
	return proposals


def _wazuh_seconds(settings):
	return wazuh_ar.command_seconds(settings.get("wazuh_ar_command")) or 0


def _wazuh_hours(settings):
	return max(round(_wazuh_seconds(settings) / 3600), 1)


def _hours(p, settings, asked=None):
	"""The Wolf Agent's block duration (the one asked for), or Wazuh's command timeout when only
	Wazuh applies it."""
	if p["action"] != "block_ip":
		return None
	if p.get("executors") == ["wazuh"]:
		return _wazuh_hours(settings)
	return cint(asked) or response.DEFAULT_HOURS


def _protected_user(user):
	"""A System Manager can only be acted on by another System Manager (or Administrator)."""
	if "System Manager" not in frappe.get_roles(user):
		return False
	return frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles()


@frappe.whitelist()
def get_response(incident):
	doc = _incident(incident)
	from dodock_wolf.wolf import window

	tz = events.system_tz()
	actions = []
	for a in _actions(doc.name):
		for field in ("approved_at", "applied_at", "expires_at"):
			a[field] = window.to_utc(a[field], tz) if a[field] else None  # the UI reads UTC ISO strings
		actions.append(a)
	return {
		"proposals": _proposals(doc),
		"actions": actions,
		"can_approve": _is_manager(),
		"default_hours": response.DEFAULT_HOURS,
		"max_hours": response.MAX_HOURS,
	}


def _apply_user_action(action, user):
	if action == "disable_user":
		frappe.db.set_value("User", user, "enabled", 0)
		from frappe.sessions import clear_sessions

		clear_sessions(user=user, force=True)
		return "user disabled and logged out"
	if action == "logout_sessions":
		from frappe.sessions import clear_sessions

		clear_sessions(user=user, force=True)
		return "every session logged out"
	if action == "revoke_api_keys":
		doc = frappe.get_doc("User", user)
		doc.api_key = None
		doc.api_secret = ""  # an empty Password field removes the stored secret
		doc.flags.ignore_permissions = True
		doc.save()
		return "API key and secret removed"
	raise ValueError(action)


@frappe.whitelist(methods=["POST"])
def approve(incident, action, target, agent=None, duration_hours=None, reason=None, host=None):
	"""The Wolf Manager's confirmation of one proposed action. A block names its host (or, from
	older links and pages, the Wolf Agent that applies it) and gets one row per executor."""
	if not _is_manager():
		frappe.throw(_("Only a Wolf Manager can approve a response action."), frappe.PermissionError)
	doc = _incident(incident)
	settings = frappe.get_cached_doc("Wolf Settings")
	# only what Wolf proposed from this incident's own events: no free-form action on any user or host
	proposal = next((p for p in _proposals(doc) if p["action"] == action and p["target"] == target and (
		action != "block_ip" or (host and _key(action, target, host) == _key(action, target, p["host"]))
		or (not host and agent and p.get("agent") == agent))), None)  # fmt: skip
	hours = _hours(proposal, settings, duration_hours) if proposal else None
	refused = response.check(action, target, frappe.session.user, hours)
	if refused:
		frappe.throw(refused, frappe.ValidationError)
	if not proposal:
		frappe.throw(_("Wolf did not propose this action for this incident (or it was already approved)."),
		             frappe.ValidationError)  # fmt: skip
	if action in response.USER_ACTIONS and _protected_user(target):
		frappe.throw(_("{0} is a System Manager: only a System Manager can approve this.").format(target),
		             frappe.PermissionError)  # fmt: skip
	if action in response.USER_ACTIONS and not frappe.db.exists("User", target):
		frappe.throw(_("User {0} does not exist on this site.").format(target), frappe.ValidationError)
	now = now_datetime()
	common = {"doctype": "Wolf Response Action", "incident": doc.name, "action": action, "target": target,
	          "host": doc.host, "bench": doc.bench, "site": doc.site, "status": "Approved",
	          "approved_by": frappe.session.user, "approved_at": now, "reason": (reason or "")[:500] or None}  # fmt: skip
	rows = []
	if action == "block_ip":
		for executor in proposal["executors"]:
			wazuh = executor == "wazuh"
			row = frappe.get_doc({**common, "executor": executor, "host": proposal["host"],
			                      "duration_hours": _wazuh_hours(settings) if wazuh else hours,
			                      "agent": None if wazuh else proposal["agent"],
			                      # Wazuh removes it when its command's timeout runs out, to the second
			                      "expires_at": add_to_date(now, seconds=_wazuh_seconds(settings)) if wazuh else add_to_date(now, hours=hours)})  # fmt: skip
			row.insert(ignore_permissions=True)
			rows.append(row)
		if any(r.executor == "wazuh" for r in rows):
			# the approval is recorded and journaled before Wolf calls out: whatever happens next, a
			# block Wazuh applied has its row
			frappe.db.commit()
			for row in rows:
				if row.executor == "wazuh":
					wazuh_ar_api.apply_block(row)  # Applied or Failed at once
					frappe.db.commit()
	else:
		row = frappe.get_doc(common).insert(ignore_permissions=True)
		try:
			row.result = _apply_user_action(action, target)
			row.status, row.applied_at = "Applied", now_datetime()
		except Exception as e:
			row.status, row.result = "Failed", str(e)[:RESULT_LENGTH]
		row.save(ignore_permissions=True)
		rows.append(row)
	what = response.label(action, target, hours, proposal["host"], proposal.get("executors"), wazuh_hours=_wazuh_hours(settings))
	notes = []
	for row in rows:
		by = {"wazuh": "Wazuh", "wolf_agent": "the Wolf Agent"}.get(row.get("executor")) if action == "block_ip" else None
		by = f"{by}, {row.duration_hours} h" if by else None
		state = {"Approved": "approved, waiting for the agent", "Applied": f"applied: {row.result}",
		         "Failed": f"failed: {row.result}"}[row.status]  # fmt: skip
		notes.append(f"{row.name}{f' ({by})' if by else ''} {state}")
	if action == "block_ip":
		from dodock_wolf.api import crowdsec

		sent = crowdsec.apply_block(rows[0])  # the same block for every CrowdSec bouncer, when set up
		if sent:
			notes.append(sent)
	doc.add_comment("Comment", f"Response action ({what}): {'; '.join(notes)}.")
	out = rows[0].as_dict()
	out["also"] = [r.as_dict() for r in rows[1:]]
	return out


def pending_for_agent(agent, now=None):
	"""Approved, unexpired blocks for this agent: what the push response hands it."""
	now = now or now_datetime()
	rows = frappe.get_all(
		"Wolf Response Action",
		filters={"agent": agent, "action": "block_ip", "status": "Approved", "expires_at": (">", now)},
		fields=["name", "target", "expires_at"],
		limit=100,
	)
	return [{"id": r.name, "action": "block_ip", "ip": r.target,
	         "seconds": max(int((r.expires_at - now).total_seconds()), 60)} for r in rows]  # fmt: skip


def record_results(agent, results):
	"""`[{id, ok, detail}]` sent by an agent about its actions (protocol §2)."""
	for item in results or []:
		if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
			continue  # a string id only: anything else would act as a filter
		row = frappe.db.get_value("Wolf Response Action", item["id"], ["agent", "status", "incident"], as_dict=True)
		if not row or row.agent != agent or row.status != "Approved":
			continue  # only the agent it was given to, once
		ok = bool(item.get("ok"))
		detail = str(item.get("detail") or ("applied" if ok else "failed"))[:RESULT_LENGTH]
		frappe.db.set_value("Wolf Response Action", item["id"], {
			"status": "Applied" if ok else "Failed", "result": detail, "applied_at": now_datetime() if ok else None,
		})  # fmt: skip
		from dodock_wolf.api import journal

		journal.capture("response_action", "Wolf Response Action", item["id"],
		                {"status": "Applied" if ok else "Failed", "result": detail, "agent": agent},
		                f"{item['id']} reported by {agent}: {'applied' if ok else 'failed'}")  # fmt: skip
		if row.incident:
			frappe.get_doc("Wolf Incident", row.incident).add_comment(
				"Comment", f"Response action {item['id']} {'applied' if ok else 'failed'} on the host: {detail}"
			)


def expire_actions(now=None):
	"""Scheduler (hourly)."""
	now = now or now_datetime()
	names = frappe.get_all(
		"Wolf Response Action",
		filters={"action": "block_ip", "status": ("in", ("Approved", "Applied")), "expires_at": ("<=", now)},
		pluck="name",
	)
	from dodock_wolf.api import journal

	for name in names:
		frappe.db.set_value("Wolf Response Action", name, "status", "Expired")
		journal.capture("response_action", "Wolf Response Action", name, {"status": "Expired"}, f"{name} expired")
	return names
