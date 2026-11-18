"""Human-validated response: what Wolf may propose, and what it refuses (no frappe imports).

Wolf proposes; a Wolf Manager confirms each action; nothing runs on its own.

- `block_ip`: proposed for the public addresses in an incident's security events, whatever
  their source (Wolf, Suricata, Wazuh), for the attacked host: applied by the Wolf Agent on that
  host, as an nftables entry that expires by itself (1 to 168 hours), and/or by Wazuh active
  response on its Wazuh agent (Wolf Settings → Block With; the duration is the Wazuh command's
  timeout).
  Loopback, private, link-local and reserved addresses are never proposed nor accepted. On a host
  whose web traffic comes through a proxy (`block_proxy`: a Press app server behind its proxy),
  only SSH events propose a block: a web client's packets come from the proxy there, so blocking
  its address would stop nothing. `held_blocks` lists those, for the Response panel to say where to
  block instead.
- `disable_user`, `logout_sessions`, `revoke_api_keys`: proposed for the users named by the
  site's own security events, applied on the Wolf site itself. Administrator, Guest and the
  approver are refused, so a click cannot lock everyone out.
"""

import ipaddress

ACTIONS = ("block_ip", "disable_user", "logout_sessions", "revoke_api_keys")
USER_ACTIONS = ("disable_user", "logout_sessions", "revoke_api_keys")
EXECUTORS = ("wolf_agent", "wazuh")
BLOCK_WITH = {"wolf_agent": ("wolf_agent",), "wazuh": ("wazuh",), "both": ("wolf_agent", "wazuh")}
LABELS = {
	"block_ip": "Block {target} for {hours} h on {host}",
	"disable_user": "Disable user {target}",
	"logout_sessions": "Log out every session of {target}",
	"revoke_api_keys": "Revoke the API keys of {target}",
}
DEFAULT_HOURS = 24
MAX_HOURS = 168
PROTECTED_USERS = {"administrator", "guest"}
# categories whose payload `user` is the account at risk or misused (not the one who acted)
USER_CATEGORIES = {"frappe_failed_login", "new_admin_ip", "admin_login_new_country", "privileged_user", "api_key_generated",
                   "api_key_new_ip"}
MAX_PROPOSALS = 20


def blockable(address):
	"""(True, None) for a public unicast address, else (False, why)."""
	try:
		ip = ipaddress.ip_address(str(address).strip())
	except ValueError:
		return False, "not an IP address"
	if getattr(ip, "ipv4_mapped", None):
		ip = ip.ipv4_mapped
	if ip.is_loopback or ip.is_unspecified:
		return False, "a loopback or unspecified address"
	if ip.is_private or ip.is_link_local:
		return False, "a private or link-local address: block it on your own network instead"
	if ip.is_multicast or ip.is_reserved or not ip.is_global:
		return False, "a reserved or non-global address"
	return True, None


def check(action, target, approver=None, hours=None):
	"""None when the action may run, else the reason it is refused."""
	if action not in ACTIONS:
		return f"unknown action {action!r}"
	if not target:
		return "no target"
	if action == "block_ip":
		ok, why = blockable(target)
		if not ok:
			return f"{target} is {why}"
		if hours is not None and not (1 <= int(hours) <= MAX_HOURS):
			return f"duration must be 1 to {MAX_HOURS} hours"
		return None
	user = str(target).strip().lower()
	if user in PROTECTED_USERS:
		return f"{target} is protected"
	if approver and user == str(approver).lower():
		return "you cannot apply this to your own account"
	return None


# alerts that name the host they are about, not the one that read them (a Wazuh manager, a sensor)
EXTERNAL_CATEGORIES = {"hids_alert", "network_ids_alert"}


def attacked_host(event, sender_kind, sender_hostname):
	"""The host a block is for. Suricata and Wazuh alerts, and whatever an integration posts, name
	the host they are about; any other agent's event is about its own host, whatever its `host`
	says: a compromised agent cannot point a block at another machine."""
	if sender_kind == "integration" or event.get("category") in EXTERNAL_CATEGORIES or not sender_hostname:
		return event.get("host")
	return sender_hostname


def executors(block_with, wolf_agent, wazuh):
	"""Who can apply a block on a host: its Wolf Agent (when it has one) and/or Wazuh (when set
	up), as Block With asks."""
	wanted = BLOCK_WITH.get(block_with or "wolf_agent", BLOCK_WITH["wolf_agent"])
	return [e for e in wanted if (e == "wolf_agent" and wolf_agent) or (e == "wazuh" and wazuh)]


def suggest(events, block_with="wolf_agent", wazuh=False):
	"""Proposals `{action, target, agent, host, bench, site, reason, executors}` from an incident's
	events.

	`events`: dicts with event_type, category, host, bench, site, payload (a dict), and for blocks
	`block_host` (the attacked host, canonical) and `block_agent` (the Wolf Agent on it, or None).
	A block is proposed once per address and host, when someone can apply it there.
	"""
	out, seen = [], set()

	def add(action, target, ev, reason, **extra):
		key = (action, target, extra.get("host") if action == "block_ip" else None)
		if key in seen or len(out) >= MAX_PROPOSALS or check(action, target):
			return
		seen.add(key)
		out.append({"action": action, "target": target, "agent": ev.get("agent"), "host": ev.get("host"),
		            "bench": ev.get("bench"), "site": ev.get("site"), "reason": reason, **extra})  # fmt: skip

	for ev in events:
		if ev.get("event_type") != "security":
			continue
		payload = ev.get("payload") or {}
		ip = payload.get("ip")
		who = executors(block_with, ev.get("block_agent"), wazuh) if ip and ev.get("block_host") and not _through_proxy(ev) else []
		if who:
			add("block_ip", str(ip), ev, f"{ev.get('category')}: {ev.get('title') or ip}", host=ev["block_host"],
			    agent=ev.get("block_agent") if "wolf_agent" in who else None, executors=who)  # fmt: skip
		user = payload.get("user")
		if user and ev.get("category") in USER_CATEGORIES and not ev.get("agent"):
			for action in USER_ACTIONS:
				add(action, str(user), ev, f"{ev.get('category')}: {ev.get('title') or user}")
	return out


# the categories whose address reaches the host itself, not through its web proxy: SSH (the auth
# log, Wazuh), and a network IDS alert on the packet's own source
DIRECT_CATEGORIES = ("ssh_failed_login", "ssh_root_login", "ssh_login_after_failures", "ssh_accepted", "hids_alert")


def _direct(ev):
	payload = ev.get("payload") or {}
	if ev.get("category") == "network_ids_alert":
		return bool(payload.get("ip")) and payload.get("ip") == payload.get("src_ip")  # not an X-Forwarded-For client
	return ev.get("category") in DIRECT_CATEGORIES


def _through_proxy(ev):
	return bool(ev.get("block_proxy")) and not _direct(ev)


def held_blocks(events):
	"""`{target, host, via_proxy}` for each address a block is not proposed for because it reached
	that host through a proxy."""
	# an address also seen on SSH gets its block proposed there: nothing to explain
	direct = {(str((e.get("payload") or {}).get("ip")), e.get("block_host")) for e in events if _direct(e)}
	out, seen = [], set(direct)
	for ev in events:
		ip = (ev.get("payload") or {}).get("ip")
		if ev.get("event_type") != "security" or not ip or not _through_proxy(ev) or not blockable(ip)[0]:
			continue
		via = ev["block_proxy"]
		key = (str(ip), ev.get("block_host"))
		if key not in seen and len(out) < MAX_PROPOSALS:
			seen.add(key)
			out.append({"target": str(ip), "host": ev.get("block_host"), "via_proxy": str(via)})
	return out


def label(action, target, hours=None, host=None, executors=None, wazuh_hours=None):
	text = LABELS[action].format(target=target, hours=hours or DEFAULT_HOURS, host=host or "its host")
	if action == "block_ip" and executors and "wazuh" in executors:
		if list(executors) == ["wazuh"]:
			text += " with Wazuh"
		else:  # each applies its own duration: the hours asked, and Wazuh's command timeout
			text += f" with the Wolf Agent, and for {wazuh_hours or hours or DEFAULT_HOURS} h with Wazuh"
	return text
