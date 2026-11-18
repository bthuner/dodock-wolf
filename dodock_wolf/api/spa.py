"""Boot data for the Wolf UI (/wolf). The page embeds it; the SPA can reload it after login."""

import functools
import os

import frappe

from dodock_wolf import __version__, satellite
from dodock_wolf.wolf import access, events, spa


def get_boot_data():
	user = frappe.session.user
	return spa.boot(
		user=user,
		full_name=frappe.utils.get_fullname(user),
		roles=frappe.get_roles(user),
		time_zone=events.system_tz(),
		server_version=__version__,
		is_satellite=satellite.is_satellite(),
		restricted=access.grants(user) is not None,
		lang=frappe.local.lang,
		messages=ui_messages(frappe.local.lang),
		socketio={
			"site": frappe.local.site,
			"port": frappe.conf.socketio_port,
			"dev_server": getattr(frappe.local, "dev_server", False),
		},
	)


@functools.cache
def _catalog_keys():
	"""The app's own strings (locale/main.pot), as Frappe keys its translations: `msgid`, or
	`msgid:context`."""
	from babel.messages.pofile import read_po

	path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locale", "main.pot")
	if not os.path.exists(path):
		return frozenset()
	with open(path, "rb") as f:
		return frozenset(m.id if not m.context else f"{m.id}:{m.context}" for m in read_po(f) if m.id)


def ui_messages(lang):
	"""The Wolf UI's translations for `lang`: what Desk's __() would show for the app's own strings
	(Frappe's French included, as Desk merges it), not the thousands of other apps' strings."""
	if not lang or lang == "en":
		return {}
	from frappe.translate import get_all_translations

	keys = _catalog_keys()
	return {key: text for key, text in get_all_translations(lang).items() if key in keys and text}


def ui_built():
	"""The frontend build writes www/wolf.html; without it /wolf is a 404 (bench build skipped it)."""
	return os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), "www", "wolf.html"))


def boot_session(bootinfo):
	"""hooks.py: tells Desk whether to offer the Wolf UI."""
	bootinfo.wolf_ui = ui_built()


@frappe.whitelist()
def get_boot():
	frappe.only_for(spa.READ_ROLES)
	return get_boot_data()
