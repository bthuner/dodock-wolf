"""Frappe application security: what makes a site change weaker or riskier (no frappe imports).

The handlers in local_signals.py feed documents in; this module decides what is worth an event:

- `weakened(before, after)`: System Settings changes that lower a defence (2FA off, password
  policy relaxed, lockout loosened, longer sessions, guests allowed to upload), one row each.
- `script_change(before, after, fields)`: whether a Server/Client Script change can run new code
  (created, enabled, or its code, type or trigger changed); a description edit is not one.
- `url_domain(url)`: the host a Webhook sends documents to.
- `docperm_change(before, after)`: the rights a Custom DocPerm save granted and revoked.
- `user_permission_widens(before, after, others)`: whether a User Permission change lets its user
  see more documents. User Permissions are allow lists: the first one for a DocType restricts the
  user to it, each further one adds documents, and removing the last lifts the restriction.
- `new_api_secret(value)`: a User save that writes a new API secret (Desk shows saved Password
  fields as asterisks, so an unchanged one never looks new). Read it in before_save: Frappe
  masks Password fields right after, so on_update only ever sees asterisks.
- `role_2fa_off(before, after)`: a Role save that turned its two-factor authentication off, or a
  role with it on deleted (`after` None).
- `called_method(path, form_dict, doctype_module)`: the whitelisted method a request runs, in
  Frappe's own order (`cmd` first, then the v2 and v1 method paths), for the signals read in
  after_request and the Role Permission Manager check.
- `identity_hash(value, key)`: a keyed hash of an account name a guest typed (a password reset
  request), so bursts can be counted per account without storing what may not be anyone's address.
- `reason_text(value)`: free text a user typed (an impersonation reason), on one line and short.
"""

import hashlib
import hmac
import re
from urllib.parse import urlsplit

# field, label, how it gets weaker: "off" (1 -> 0), "on" (0 -> 1), "lower", "higher", "longer" (HH:MM)
SETTINGS_RULES = [
	("enable_two_factor_auth", "Two-factor authentication", "off"),
	("enable_password_policy", "Password policy", "off"),
	("minimum_password_score", "Minimum password score", "lower"),
	("allow_consecutive_login_attempts", "Failed logins before lockout", "higher"),
	("allow_login_after_fail", "Lockout duration (seconds)", "lower"),
	("session_expiry", "Session expiry", "longer"),
	("deny_multiple_sessions", "One session per user", "off"),
	("disable_user_pass_login", "Password login disabled (SSO only)", "off"),
	("logout_on_password_reset", "Log out all sessions on password reset", "off"),
	("allow_guests_to_upload_files", "Guests may upload files", "on"),
]

SERVER_SCRIPT_FIELDS = ("script", "script_type", "reference_doctype", "doctype_event", "api_method",
                        "allow_guest", "event_frequency", "cron_format")  # fmt: skip
CLIENT_SCRIPT_FIELDS = ("script", "dt", "view")

# Custom DocPerm rights, in the Role Permission Manager's order; `if_owner` narrows them
DOCPERM_RIGHTS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export",
                  "import", "share", "print", "email", "select", "mask")  # fmt: skip
# roles every visitor or every logged-in user has: a right given to them is given to everyone
EVERYONE_ROLES = ("Guest", "All")
# what a User Permission allows, and whom: changing one moves access (is_default only
# preselects a value in forms)
USER_PERMISSION_TARGET = ("user", "allow", "for_value", "applicable_for")
# switches that narrow it when on: turning one off widens it
USER_PERMISSION_NARROWING = ("apply_to_all_doctypes", "hide_descendants")


def _number(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _minutes(hhmm):
	"""`HH:MM` (System Settings session expiry) -> minutes, or None."""
	try:
		hours, minutes = str(hhmm).strip().split(":")[:2]
		return int(hours) * 60 + int(minutes)
	except (AttributeError, TypeError, ValueError):
		return None


def _truthy(value):
	return bool(_number(value)) if _number(value) is not None else bool(value)


def weakened(before, after):
	"""Rows `{field, label, old, new}` for every System Settings change that lowers a defence.

	`before` is None for a first save: nothing is compared then.
	"""
	if not before:
		return []
	rows = []
	for field, label, rule in SETTINGS_RULES:
		old, new = before.get(field), after.get(field)
		if old == new:
			continue
		if rule == "off":
			worse = _truthy(old) and not _truthy(new)
		elif rule == "on":
			worse = not _truthy(old) and _truthy(new)
		elif rule == "longer":
			o, n = _minutes(old), _minutes(new)
			worse = o is not None and n is not None and n > o
		else:
			o, n = _number(old), _number(new)
			if o is None or n is None:
				continue
			# 0 failed attempts before lockout means no lockout at all
			worse = (n < o) if rule == "lower" else (n > o or (n == 0 and o > 0))
		if worse:
			rows.append({"field": field, "label": label, "old": old, "new": new})
	return rows


def script_change(before, after, fields):
	"""'created', 'enabled', 'changed' or None for a Server/Client Script save.

	A disabled script runs nothing: only an enabled one (or one being enabled) counts.
	"""
	disabled_field = "disabled" if "disabled" in after else None
	enabled_now = not _truthy(after.get(disabled_field)) if disabled_field else _truthy(after.get("enabled"))
	if not enabled_now:
		return None
	if not before:
		return "created"
	enabled_before = not _truthy(before.get(disabled_field)) if disabled_field else _truthy(before.get("enabled"))
	if not enabled_before:
		return "enabled"
	if any((before.get(f) or "") != (after.get(f) or "") for f in fields):
		return "changed"
	return None


def url_domain(url):
	try:
		host = urlsplit(str(url or "").strip()).hostname
	except ValueError:
		return None
	return host.lower() if host else None


def docperm_change(before, after):
	"""{"granted": [...], "revoked": [...]} for a Custom DocPerm save, or None when no right moved.

	A new rule grants every right it has. Clearing "only if creator" (if_owner) grants the rule's
	rights on every document, not only the user's own: it shows as "all documents" granted.
	"""
	before = before or {}
	granted = [r for r in DOCPERM_RIGHTS if _truthy(after.get(r)) and not _truthy(before.get(r))]
	revoked = [r for r in DOCPERM_RIGHTS if _truthy(before.get(r)) and not _truthy(after.get(r))]
	if before:
		owner_before, owner_after = _truthy(before.get("if_owner")), _truthy(after.get("if_owner"))
		if owner_before and not owner_after:
			granted.append("all documents")
		elif owner_after and not owner_before:
			revoked.append("all documents")
	if before and (before.get("role"), before.get("parent")) != (after.get("role"), after.get("parent")):
		# the rule moved to another role or DocType: everything it has is granted there
		granted = [r for r in DOCPERM_RIGHTS if _truthy(after.get(r))]
	if not granted and not revoked:
		return None
	return {"granted": granted, "revoked": revoked}


def user_permission_widens(before, after, others):
	"""True when a User Permission change lets its user see more documents.

	`others`: how many other User Permissions the user has for the same allowed DocType.
	- created: widens when the user already had some (one more allowed value); the first one
	  only restricts (ERPNext creates those for employees, for instance);
	- removed (`after` None): widens when it was the last one, which lifts the restriction;
	- edited: widens when it allows another value, user or DocType, or stops applying to every
	  DocType, or stops hiding descendants.
	"""
	if after is None:
		return others == 0
	if not before:
		return others > 0
	if any((before.get(f) or "") != (after.get(f) or "") for f in USER_PERMISSION_TARGET):
		return True
	return any(_truthy(before.get(f)) and not _truthy(after.get(f)) for f in USER_PERMISSION_NARROWING)


def new_api_secret(value):
	"""True when a save wrote a fresh API secret (not the asterisks Desk sends back)."""
	text = str(value or "")
	return bool(text) and set(text) != {"*"}


def excerpt(code, limit=300):
	"""The start of a script, for the event: enough to recognise it, not the whole program."""
	text = str(code or "")
	return text if len(text) <= limit else text[:limit] + "…"


ROLE_2FA_LABEL = "Two-factor authentication for the role"


def role_2fa_off(before, after):
	"""`{field, label, old, new}` when a Role save turned two-factor authentication off, or a role
	with it on was deleted (`after` None, `new` None), else None.

	A new role (no `before`) is not compared: creating a role without 2FA lowers nothing.
	"""
	if not before:
		return None
	old, new = before.get("two_factor_auth"), (after or {}).get("two_factor_auth")
	if _truthy(old) and not _truthy(new):
		return {"field": "two_factor_auth", "label": ROLE_2FA_LABEL, "old": old, "new": new}
	return None


# `/api/method/<m>` and `/api/v1/method/<m>` (v1); v2 names a method, or a DocType and one of its
# controller's methods
V1_METHOD_PATHS = ("/api/method/", "/api/v1/method/")
V2_METHOD_PATH = "/api/v2/method/"


def _scrub(text):
	"""frappe.scrub: `Sales Order` -> `sales_order`."""
	return str(text or "").replace(" ", "_").replace("-", "_").lower()


def doctype_module_path(app, module, doctype):
	"""The dotted path of a DocType's controller module, by Frappe's naming rule
	(frappe.modules.utils.get_module_name): `frappe.core.doctype.user.user` for User."""
	return f"{_scrub(app)}.{_scrub(module)}.doctype.{_scrub(doctype)}.{_scrub(doctype)}"


def called_method(path, form_dict=None, doctype_module=None):
	"""The dotted method a request runs, read in Frappe's own order, or None (a page, a resource, a file).

	1. `cmd` in the request's arguments: Frappe (app.py) runs it before looking at the path, so
	   `POST /api/method/frappe.ping` with `cmd=<m>` in the body runs `<m>`. A v1 call also sets it.
	2. `/api/v2/method/<m>`, or `/api/v2/method/<DocType>/<m>`: `<m>` of the DocType's controller
	   module, whose dotted path `doctype_module(doctype)` gives (None when unknown).
	3. `/api/method/<m>` and `/api/v1/method/<m>`: up to the first `/`, as v1 does
	   (`/api/method/<m>/x` runs `<m>`).
	"""
	cmd = str((form_dict or {}).get("cmd") or "").strip()
	if cmd:
		return cmd
	path = str(path or "")
	if path.startswith(V2_METHOD_PATH):
		# Frappe's routes ignore a trailing slash
		parts = path[len(V2_METHOD_PATH) :].removesuffix("/").split("/")
		if len(parts) == 1:
			return parts[0] or None
		if len(parts) == 2 and all(parts) and doctype_module:
			module = doctype_module(parts[0])
			return f"{module}.{parts[1]}" if module else None
		return None
	for prefix in V1_METHOD_PATHS:
		if path.startswith(prefix):
			return path[len(prefix) :].split("/")[0] or None
	return None


# the context a site's encryption key is derived under for identity_hash (links.derive_key)
IDENTITY_CONTEXT = b"dodock_wolf.identity.v1"


def identity_hash(value, key):
	"""16 hex characters of HMAC-SHA256(`key`, the lowercased account name), or None (no account,
	or no key).

	Keyed with a secret derived from the site's encryption key (IDENTITY_CONTEXT): a list of known
	e-mail addresses cannot be hashed to find who was targeted, and the same account gives the same
	hash on this site, so bursts still add up.
	"""
	text = str(value or "").strip().lower()
	if not text or not key:
		return None
	return hmac.new(str(key or "").encode(), text.encode(), hashlib.sha256).hexdigest()[:16]


_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def reason_text(value, limit=200):
	"""Free text a user typed, for an event: control characters and runs of spaces become one space,
	cut at `limit` characters (`excerpt`)."""
	text = " ".join(_CONTROL.sub(" ", str(value or "")).split())
	return excerpt(text, limit) if text else None
