import frappe


def execute():
	"""Digests were removed in 0.2 (v0.1.0 keeps them): notifications always go out at once. Drop the
	Wolf Digest Item DocType, with what was still queued; the Wolf Alert Channel `digest` column stays
	in the table, unused."""
	frappe.delete_doc("DocType", "Wolf Digest Item", force=True, ignore_missing=True)
