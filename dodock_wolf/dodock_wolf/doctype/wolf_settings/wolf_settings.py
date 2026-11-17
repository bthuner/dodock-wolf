# Copyright (c) 2026, Dodock Wolf contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WolfSettings(Document):
	def validate(self):
		if (self.get("block_with") or "wolf_agent") in ("wazuh", "both"):
			from dodock_wolf.wolf import wazuh_ar

			if not self.get("wazuh_api_url") or not self.get("wazuh_api_user"):
				frappe.throw("Blocking with Wazuh needs the Wazuh API URL and user")
			if not str(self.wazuh_api_url).startswith(("https://", "http://")):
				frappe.throw("The Wazuh API URL must start with https:// or http://")
			error = wazuh_ar.command_error(self.get("wazuh_ar_command"))
			if error:
				frappe.throw(error)

	@frappe.whitelist()
	def regenerate_registration_token(self):
		frappe.only_for(("System Manager", "Wolf Manager"))
		token = frappe.generate_hash(length=32)
		self.registration_token = token
		self.save()
		return token

	@frappe.whitelist()
	def get_install_command(self):
		frappe.only_for(("System Manager", "Wolf Manager"))
		token = self.get_password("registration_token", raise_exception=False)
		if not token:
			frappe.throw("Set or regenerate the registration token first")
		url = (self.public_url or frappe.utils.get_url()).rstrip("/")
		return f"curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh | sudo WOLF_URL={url} WOLF_TOKEN={token} bash"
