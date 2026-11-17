"""Wazuh active response for approved blocks (wolf/wazuh_ar.py): the manager's API, from this site.

- `enabled(settings)`: Block With is `wazuh` or `both`, and the API and command are set.
- `apply_block(row)`: after approval, finds the Wazuh agent of the row's host (by its names and
  addresses in Wolf Entity Alias, and its Wolf Agent's last address) and runs the command there.
  The row becomes Applied or Failed at once; the journal records it (on_response_action).
- `test_connection()`: a Wolf Manager's check from Wolf Settings.
"""

import frappe
import requests
from frappe.utils import now_datetime

from dodock_wolf.wolf import entities, wazuh_ar
from dodock_wolf.wolf.spa import MANAGER_ROLES

TIMEOUT = 15


def _settings():
	return frappe.get_cached_doc("Wolf Settings")


def enabled(settings=None):
	settings = settings or _settings()
	return (settings.get("block_with") or "wolf_agent") in ("wazuh", "both") and bool(settings.get("wazuh_api_url"))


class Client:
	def __init__(self, settings):
		self.base = settings.wazuh_api_url.rstrip("/")
		self.verify = bool(settings.get("wazuh_verify_tls", 1))
		user, password = settings.get("wazuh_api_user"), settings.get_password("wazuh_api_password", raise_exception=False)
		if not user or not password:
			raise wazuh_ar.WazuhError("set the Wazuh API user and password")
		try:
			r = requests.post(f"{self.base}/security/user/authenticate", auth=(user, password), timeout=TIMEOUT, verify=self.verify)
		except requests.RequestException as e:
			raise wazuh_ar.WazuhError(f"Wazuh API unreachable: {type(e).__name__}") from e
		if r.status_code != 200:
			raise wazuh_ar.WazuhError(f"Wazuh API login refused (HTTP {r.status_code})")
		self.token = (r.json().get("data") or {}).get("token")
		if not self.token:
			raise wazuh_ar.WazuhError("Wazuh API login gave no token")

	def call(self, method, path, **kw):
		try:
			r = requests.request(method, f"{self.base}{path}", headers={"Authorization": f"Bearer {self.token}"},
			                     timeout=TIMEOUT, verify=self.verify, **kw)  # fmt: skip
		except requests.RequestException as e:
			raise wazuh_ar.WazuhError(f"Wazuh API unreachable: {type(e).__name__}") from e
		try:
			body = r.json()
		except ValueError:
			body = {}
		if r.status_code >= 400:
			raise wazuh_ar.WazuhError(f"Wazuh API {method} {path.split('?')[0]}: HTTP {r.status_code} {body.get('detail') or ''}".strip())
		return body

	def agents(self):
		data = self.call("GET", "/agents", params={"select": "id,name,ip", "limit": 100000}).get("data") or {}
		return data.get("affected_items") or []

	def run(self, agent_id, command, ip):
		return self.call("PUT", "/active-response", params={"agents_list": agent_id, "wait_for_complete": "true"},
		                 json=wazuh_ar.block_body(command, ip))  # fmt: skip


def host_names_and_addresses(host):
	"""What a host is called and where it is: its aliases (names and addresses) and its Wolf
	Agents' last address."""
	canonical = entities.normal_name(host)
	names, addresses = {canonical}, set()
	for alias in frappe.get_all("Wolf Entity Alias", filters={"kind": "host", "canonical": canonical}, pluck="alias"):
		(addresses if entities.normal_ip(alias) else names).add(alias)
	for row in frappe.get_all("Wolf Agent", filters={"hostname": host}, fields=["last_ip"]):
		if row.last_ip:
			addresses.add(row.last_ip)
	return names, addresses


def apply_block(row):
	"""Run the approved block on the host's Wazuh agent; sets the row's status and result."""
	settings = _settings()
	command = (settings.get("wazuh_ar_command") or "").strip()
	try:
		error = wazuh_ar.command_error(command)
		if error:
			raise wazuh_ar.WazuhError(error)
		client = Client(settings)
		names, addresses = host_names_and_addresses(row.host)
		agent_id = wazuh_ar.find_agent(client.agents(), names, addresses)
		if not agent_id:
			raise wazuh_ar.WazuhError(f"no Wazuh agent is {row.host} (by name or address); add a Wolf Entity Alias")
		row.wazuh_agent_id = agent_id
		ok, detail = wazuh_ar.applied(client.run(agent_id, command, row.target), agent_id)
	except wazuh_ar.WazuhError as e:
		ok, detail = False, str(e)
	row.status = "Applied" if ok else "Failed"
	row.result = f"{detail} ({command})"[:500] if ok else detail[:500]
	row.applied_at = now_datetime() if ok else None
	row.save(ignore_permissions=True)
	return row


@frappe.whitelist(methods=["POST"])
def test_connection():
	"""Log in to the Wazuh API and list its agents: what a block would need."""
	frappe.only_for(MANAGER_ROLES)
	settings = _settings()
	error = wazuh_ar.command_error(settings.get("wazuh_ar_command"))
	try:
		agents = [a for a in Client(settings).agents() if str(a.get("id")) != "000"]
	except wazuh_ar.WazuhError as e:
		return {"ok": False, "detail": str(e)}
	return {"ok": not error, "detail": error or f"{len(agents)} Wazuh agents can run {settings.wazuh_ar_command}",
	        "agents": [a.get("name") for a in agents][:50]}  # fmt: skip
