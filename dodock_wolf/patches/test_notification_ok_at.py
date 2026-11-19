import frappe

from dodock_wolf.api.onboarding import test_accepted_at


def execute():
	"""Sites that already sent a test notification keep the setup checklist's last step done
	(Wolf Settings → Test Notification Accepted At), from the delivery that recorded it."""
	at = frappe.db.sql("select max(`at`) from `tabWolf Delivery` where kind = 'test' and ok = 1")[0][0]
	if at and not test_accepted_at():
		frappe.db.set_single_value("Wolf Settings", "test_notification_ok_at", at)
