from dodock_wolf.dodock_wolf.doctype.wolf_event.wolf_event import on_doctype_update


def execute():
	"""Add the (incident, event_type) index to Wolf Event on sites that had the DocType: Frappe
	runs on_doctype_update only when it syncs a changed DocType, which this one is not."""
	on_doctype_update()
