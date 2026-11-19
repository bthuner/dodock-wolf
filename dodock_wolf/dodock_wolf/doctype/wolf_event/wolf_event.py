# Copyright (c) 2026, Dodock Wolf contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WolfEvent(Document):
	pass


def on_doctype_update():
	# Whether an incident holds an event of a type (the home page's security incidents) reads
	# that incident's events of that type only. Sites that had the DocType: patches/event_incident_index.
	frappe.db.add_index("Wolf Event", ["incident", "event_type"])
