"""Translation for the pure modules (wolf/*), which import nothing from Frappe at load time.

    from dodock_wolf.wolf.i18n import _, fmt

    _("Two-factor authentication is off")       # the reader's language in a request
    fmt(_("{0} of {1} hosts"), shown, total)    # placeholders filled safely

`_` is frappe._ when Frappe is there (a request: the user's language; a job: the system's) and
the English otherwise (the unit tests, the agent). Frappe's extractor reads the `_("...")`
literals of every module into dodock_wolf/locale/main.pot.

Translate text when it is shown, never in what is stored or cached for everyone: a stored
English string stays English, and a cached value is shared by readers of every language.
"""

import re

_PLACEHOLDER = re.compile(r"\{(\d+)\}")


def _(text):
	if not text:
		return text
	try:
		import frappe
	except ImportError:
		return text
	if not getattr(frappe.local, "site", None):
		return text  # no site: nothing to translate with
	return frappe._(text)


def N_(text):
	"""A literal marked for the extractor (`N_` is one of Frappe's keywords) and left English: for
	tables built when a module loads, translated with `_` per request where they are shown."""
	return text


def fmt(template, *args):
	"""`template` with `{0}`, `{1}`... filled; a placeholder it has no value for stays as it is, so a
	translation that adds one never raises, as str.format would."""
	return _PLACEHOLDER.sub(lambda m: str(args[int(m.group(1))]) if int(m.group(1)) < len(args) else m.group(0), template)
