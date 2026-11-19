import frappe


def execute():
	"""Digests were removed in 0.2 (v0.1.0 keeps them): notifications always go out at once. Drop the
	Wolf Digest Item DocType, with what was still queued; the Wolf Alert Channel `digest` column stays
	in the table, unused. What is dropped is counted in an Error Log, so the operator knows."""
	pending = 0
	if frappe.db.table_exists("Wolf Digest Item"):
		pending = frappe.db.sql("select count(*) from `tabWolf Digest Item`")[0][0]
	if pending:
		message = (
			f"Digests were removed in Dodock Wolf 0.2: {pending} pending digest item(s) were dropped "
			"at the upgrade and will not be sent. Channels that used hourly digests now send every "
			"alert at once."
		)
		print(message)
		frappe.log_error(title="Dodock Wolf 0.2: pending digests dropped", message=message)
	frappe.delete_doc("DocType", "Wolf Digest Item", force=True, ignore_missing=True)
