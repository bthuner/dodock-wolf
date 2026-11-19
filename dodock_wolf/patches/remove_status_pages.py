import frappe


def execute():
	"""Status pages were removed in 0.2 (v0.1.0 keeps them): drop the Wolf Status Page DocType.
	The Wolf Incident `public_title` column stays in the table, unused."""
	frappe.delete_doc("DocType", "Wolf Status Page", force=True, ignore_missing=True)
