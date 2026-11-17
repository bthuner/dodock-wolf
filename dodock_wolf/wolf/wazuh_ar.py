"""Approved blocks through Wazuh active response (no frappe imports; #72 step 6).

Wolf still proposes and a Wolf Manager still approves each block (wolf/response.py). With
**Block With** set to `wazuh` or `both`, Wolf asks the Wazuh manager's API to run a named active
response command on the Wazuh agent of the attacked host:

- `POST /security/user/authenticate` with basic auth gives a JWT (`data.token`);
- `GET /agents?select=id,name,ip` finds the agent: by one of the host's names or addresses;
- `PUT /active-response?agents_list=<id>` with `{"command": <name>, "alert": {"data": {"srcip": <ip>}}}`.

The command must be a named one, defined by an `<active-response>` block in the manager's
ossec.conf, whose name Wazuh suffixes with its timeout: `firewall-drop86400` drops for 24 h and
Wazuh removes the rule by itself. A script started with `!` would never be removed, so it is
refused: every block Wolf approves expires. Tried against a Wazuh 4.9.2 manager and agent.
"""

import ipaddress
import re

_COMMAND = re.compile(r"^[A-Za-z0-9_.-]*?[A-Za-z_.-](\d+)$")
MAX_SECONDS = 168 * 3600  # Wolf's longest block


class WazuhError(Exception):
	pass


def command_seconds(command):
	"""The timeout Wazuh appended to a named command (`firewall-drop86400` → 86400), or None."""
	m = _COMMAND.match(str(command or "").strip())
	return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def command_error(command):
	"""None when Wolf can use the command, else why not."""
	command = str(command or "").strip()
	if not command:
		return "set the Wazuh active response command, for example firewall-drop86400"
	if command.startswith("!"):
		return "a script (!name) is never removed: use a named command with a timeout, such as firewall-drop86400"
	seconds = command_seconds(command)
	if not seconds:
		return f"{command} has no timeout: Wazuh names commands with their timeout, such as firewall-drop86400"
	if seconds > MAX_SECONDS:
		return f"{command} blocks for longer than {MAX_SECONDS // 3600} h, Wolf's longest block"
	return None


def find_agent(agents, names, addresses):
	"""The id of the Wazuh agent that is the host: by name first, then by an address only one agent
	has (hosts behind one NAT, or agents reporting `any`, share addresses). `agents` are `{id, name,
	ip}` rows from GET /agents; the manager (000) never runs a block."""
	names = {str(n).strip().lower() for n in names if n}
	addresses = {str(a).strip() for a in addresses if a}
	usable = [a for a in agents if str(a.get("id")) != "000"]
	for agent in usable:
		if str(agent.get("name") or "").strip().lower() in names:
			return str(agent["id"])
	by_address = [a for a in usable if str(a.get("ip") or "").strip() in addresses]
	return str(by_address[0]["id"]) if len(by_address) == 1 else None


def safe_url(url):
	"""https://, or http:// to this machine only: the API password goes with every login."""
	url = str(url or "").strip().lower()
	if url.startswith("https://"):
		return True
	host = url.removeprefix("http://").split("/")[0].rsplit(":", 1)[0].strip("[]") if url.startswith("http://") else ""
	return host in ("localhost", "127.0.0.1", "::1")


def block_body(command, ip):
	ipaddress.ip_address(ip)  # a block names one address, nothing else goes into the command
	return {"command": command, "alert": {"data": {"srcip": ip}}}


def applied(answer, agent_id):
	"""(ok, detail) from the PUT /active-response answer."""
	data = (answer or {}).get("data") or {}
	if str(agent_id) in [str(i) for i in data.get("affected_items") or []]:
		return True, f"sent to Wazuh agent {agent_id}"
	failed = data.get("failed_items") or []
	why = (failed[0].get("error") or {}).get("message") if failed and isinstance(failed[0], dict) else None
	return False, why or (answer or {}).get("message") or "Wazuh did not accept the command"
