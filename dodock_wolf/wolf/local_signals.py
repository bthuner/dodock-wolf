"""Signals captured on the site where Dodock Wolf itself is installed (doc_events)."""

import os

import frappe
from frappe.utils import cint

from dodock_wolf.wolf import app_security, events, geoip, links
from dodock_wolf.wolf.reputation import lines as setting_lines
from dodock_wolf.wolf.schema import fingerprint


def _settings():
	return frappe.get_cached_doc("Wolf Settings")


def _safe(fn):
	"""Never let observability break the observed operation."""

	def wrapper(doc, method=None):
		if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
			return
		try:
			fn(doc)
		except Exception:
			# Do not call frappe.log_error here: it would feed back into on_error_log.
			frappe.logger("dodock_wolf").exception("local signal failed")

	wrapper.__name__ = fn.__name__
	return wrapper


def on_scheduled_job_failed(job):
	"""Called from WolfScheduledJobType.log_status while the exception is being handled."""
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return
	try:
		if not cint(_settings().capture_scheduler_failures):
			return
		label = job.server_script or job.method
		events.emit(
			"cron_failure",
			f"Scheduled job failed: {label}",
			severity="critical",
			category="scheduled_job",
			source="scheduler",
			payload={
				"job": job.name,
				"method": job.method,
				"server_script": job.server_script,
				"frequency": job.frequency,
				"cron_format": job.cron_format,
				"log": job.scheduler_log.name if getattr(job, "scheduler_log", None) else None,
				"traceback": frappe.get_traceback()[-4000:],
			},
			dedupe_minutes=1,
		)
		# log_status runs after the job's rollback; persist our event explicitly.
		frappe.db.commit()
	except Exception:
		frappe.logger("dodock_wolf").exception("could not record scheduled job failure")


@_safe
def on_error_log(doc):
	if not cint(_settings().capture_error_logs):
		return
	title = doc.get("method") or doc.get("title") or "Error"
	if str(title).startswith("[Wolf]"):
		return
	trace = doc.get("error") or ""
	last_line = trace.strip().splitlines()[-1] if trace.strip() else title
	backup = is_backup_failure(title, trace)
	events.emit(
		"error",
		f"{title}: {last_line}"[:255],
		severity="critical" if backup else "warning",
		category="backup_failed" if backup else "traceback",
		source="frappe",
		payload={"error_log": doc.name, "reference": [doc.get("reference_doctype"), doc.get("reference_name")], "traceback": trace[-4000:]},
		fingerprint=fingerprint("error_log", title, last_line),
		dedupe_minutes=10,
	)


@_safe
def on_activity_log(doc):
	if doc.operation == "Impersonate":
		check_impersonation(doc, _settings())
		return
	if doc.operation != "Login":
		return
	settings = _settings()
	if (doc.user or "").lower() in decoy_users(settings):
		from dodock_wolf.api import threat

		threat.touched("user", doc.user, {"status": doc.status, "activity_log": doc.name})
		return  # a decoy account: the honeytoken event says it all
	if doc.status == "Failed" and cint(settings.capture_login_failures):
		events.emit(
			"security",
			f"Failed login for {doc.user or 'unknown user'} from {doc.ip_address or 'unknown IP'}",
			severity="warning",
			category="frappe_failed_login",
			source="frappe",
			payload={"user": doc.user, "ip": doc.ip_address, "activity_log": doc.name},
		)
	elif doc.status == "Success" and cint(settings.capture_admin_logins) and doc.ip_address:
		if not is_privileged(doc.user, settings):
			return
		previous = previous_login_ips(doc)
		if not previous or doc.ip_address in previous:
			return
		events.emit(
			"security",
			f"Privileged user {doc.user} logged in from new IP {doc.ip_address}",
			severity="warning",
			category="new_admin_ip",
			source="frappe",
			payload={"user": doc.user, "ip": doc.ip_address, "activity_log": doc.name},
		)
		check_new_country(doc, previous, settings)


IMPERSONATE = "frappe.core.doctype.user.user.impersonate"


def check_impersonation(doc, settings):
	"""`user_impersonated`: User → Impersonate opens a session as another user (Frappe 15:
	Administrator only; 16: whoever has the `impersonate` permission on User). Frappe inserts the
	Activity Log before it switches the session, so its owner is the impersonator; the reason
	comes with the same request.

	Only inside a call of Frappe's impersonate method: an Activity Log row inserted any other way
	(the REST API, Data Import, code) opens no session, and a `reason` argument proves nothing, as
	anyone can add one to their own request. Frappe fills the row's IP for logins and logouts only:
	the request's address is used.
	"""
	if not _app_security(settings) or request_method() != IMPERSONATE:
		return
	target, actor = doc.user, doc.owner or frappe.session.user
	ip = doc.get("ip_address") or getattr(frappe.local, "request_ip", None)
	privileged = is_privileged(target, settings) if target else False
	events.emit(
		"security",
		f"{actor} impersonated {'privileged user ' if privileged else ''}{target or 'unknown user'}"[:255],
		severity="critical" if privileged else "warning",
		category="user_impersonated",
		source="frappe",
		payload={
			"user": target, "by": actor, "reason": app_security.reason_text(frappe.form_dict.get("reason")),
			"ip": ip, "privileged": privileged, "activity_log": doc.name,
		},
		fingerprint=fingerprint("user_impersonated", actor, target),
	)  # fmt: skip


def check_new_country(doc, previous, settings):
	"""`admin_login_new_country` when the new IP's country differs from every earlier login's.

	Uses the offline database in Wolf Settings → GeoIP Database; never a network service.
	"""
	path = (settings.get("geoip_database") or "").strip()
	if not path or not cint(settings.get("capture_admin_countries")):
		return
	if not os.path.isabs(path):
		path = frappe.get_site_path(path)  # e.g. private/files/GeoLite2-Country.mmdb
	try:
		country = geoip.country(path, doc.ip_address)
		if not country:
			return
		known = {geoip.country(path, ip) for ip in previous} - {None}
	except (OSError, ValueError) as e:
		frappe.logger("dodock_wolf").warning(f"GeoIP lookup with {path} failed: {e}")
		return
	if not known or country in known:
		return  # no baseline yet (only private IPs so far), or a known country
	events.emit(
		"security",
		f"Privileged user {doc.user} logged in from a new country: {country} ({doc.ip_address})",
		severity="critical",
		category="admin_login_new_country",
		source="frappe",
		payload={
			"user": doc.user, "ip": doc.ip_address, "country": country,
			"known_countries": sorted(known), "activity_log": doc.name,
		},
	)  # fmt: skip


@_safe
def on_user_update(doc):
	settings = _settings()
	check_api_key(doc, settings)
	check_desk_access(doc, settings)
	check_password_by_other(doc, settings)
	if not cint(settings.capture_privileged_users) or not doc.enabled:
		return
	privileged = privileged_roles(settings)
	before = doc.get_doc_before_save()
	old = {r.role for r in before.roles} if before else set()
	added = sorted(({r.role for r in doc.roles} - old) & privileged)
	if not added:
		return
	events.emit(
		"security",
		f"{doc.name} was granted {', '.join(added)}",
		severity="critical" if "Administrator" in added or "System Manager" in added else "warning",
		category="privileged_user",
		source="frappe",
		payload={"user": doc.name, "roles": added, "by": frappe.session.user, "new_user": before is None},
	)


# --- Frappe application security (Wolf Settings → Flag risky application changes) ---


def _app_security(settings=None):
	return cint((settings or _settings()).get("capture_app_security"))


def _before(doc):
	before = doc.get_doc_before_save()
	return before.as_dict() if before else None


def on_user_before_save(doc, method=None):
	"""Frappe masks Password fields (`*****`) after before_save, so a new API secret is only
	visible here: note it for on_update, which records it once the save went through."""
	try:
		doc.flags.wolf_new_api_secret = app_security.new_api_secret(doc.get("api_secret"))
	except Exception:
		frappe.logger("dodock_wolf").exception("could not inspect the API secret")


def on_user_before_validate(doc, method=None):
	"""User.validate moves `new_password` aside and empties the field: only here is a password
	typed on the form (Desk, REST, Data Import) still visible. Only that one was set is kept."""
	try:
		doc.flags.wolf_password_set = bool(doc.get("new_password"))
	except Exception:
		frappe.logger("dodock_wolf").exception("could not inspect the new password")


def check_password_by_other(doc, settings):
	"""`credentials_reset_by_other`: a user's password set, on a save, by someone else.

	A new user's first password is not one: whoever creates an account gives it one.
	"""
	if not _app_security(settings) or not doc.flags.get("wolf_password_set"):
		return
	if frappe.session.user == doc.name or doc.get_doc_before_save() is None:
		return
	credentials_event(doc.name, frappe.session.user, "password", settings)


CREDENTIAL_KINDS = {"password": "Password", "otp_secret": "OTP secret", "ldap_password": "LDAP password"}


def credentials_event(target, actor, kind, settings):
	"""One `credentials_reset_by_other` event. Never carries the credential itself."""
	privileged = is_privileged(target, settings)
	events.emit(
		"security",
		f"{CREDENTIAL_KINDS[kind]} of {'privileged user ' if privileged else ''}{target} reset by {actor}"[:255],
		severity="critical" if privileged else "warning",
		category="credentials_reset_by_other",
		source="frappe",
		payload={"kind": kind, "user": target, "by": actor, "ip": getattr(frappe.local, "request_ip", None),
		         "privileged": privileged, "via": _via()},  # fmt: skip
		fingerprint=fingerprint("credentials_reset_by_other", kind, target, actor),
		dedupe_minutes=10,
	)


def check_api_key(doc, settings):
	"""`api_key_generated`: a User save wrote a new API secret (generate keys, or by hand)."""
	if not _app_security(settings) or not doc.flags.get("wolf_new_api_secret"):
		return
	privileged = is_privileged(doc.name, settings)
	events.emit(
		"security",
		f"API key generated for {'privileged user ' if privileged else ''}{doc.name}",
		severity="critical" if privileged else "warning",
		category="api_key_generated",
		source="frappe",
		payload={"user": doc.name, "api_key": doc.get("api_key"), "privileged": privileged, "by": frappe.session.user},
	)


def check_desk_access(doc, settings):
	"""`permission_change`: a Website user (portal: customer, supplier) now has desk access.

	Frappe derives user_type from the roles on each save: a desk role makes a System User.
	"""
	if not _app_security(settings):
		return
	before = doc.get_doc_before_save()
	if not before or before.get("user_type") != "Website User" or doc.get("user_type") != "System User":
		return
	added = sorted({r.role for r in doc.roles} - {r.role for r in before.roles})
	events.emit(
		"security",
		f"Website user {doc.name} given desk access" + (f" ({', '.join(added)})" if added else ""),
		severity="warning",
		category="permission_change",
		source="frappe",
		payload={"kind": "desk_access", "user": doc.name, "roles": added, "by": frappe.session.user, "via": _via()},
		fingerprint=fingerprint("permission_change", "desk_access", doc.name),
		dedupe_minutes=10,
	)


def _script_event(doc, kind, fields, category, label):
	if not _app_security():
		return
	change = app_security.script_change(_before(doc), doc.as_dict(), fields)
	if not change:
		return
	critical = kind == "server" and (doc.get("script_type") in ("API", "Scheduler Event") or cint(doc.get("allow_guest")))
	target = doc.get("api_method") or doc.get("reference_doctype") or doc.get("dt") or doc.get("event_frequency") or ""
	events.emit(
		"security",
		f"{label} {doc.name} {change}" + (f" ({target})" if target else ""),
		severity="critical" if critical else "warning",
		category=category,
		source="frappe",
		payload={
			"script": doc.name, "change": change, "script_type": doc.get("script_type"),
			"reference_doctype": doc.get("reference_doctype") or doc.get("dt"), "api_method": doc.get("api_method"),
			"allow_guest": cint(doc.get("allow_guest")), "event_frequency": doc.get("event_frequency"),
			"by": frappe.session.user, "excerpt": app_security.excerpt(doc.get("script")),
		},
	)  # fmt: skip


@_safe
def on_server_script(doc):
	_script_event(doc, "server", app_security.SERVER_SCRIPT_FIELDS, "server_script_change", "Server Script")


@_safe
def on_client_script(doc):
	_script_event(doc, "client", app_security.CLIENT_SCRIPT_FIELDS, "client_script_change", "Client Script")


@_safe
def on_console_log(doc):
	"""System Console runs arbitrary Python (or SQL) as the user: record each run."""
	if not _app_security():
		return
	events.emit(
		"security",
		f"System Console run by {doc.owner}" + (" (committed)" if cint(doc.get("committed")) else ""),
		severity="warning",
		category="console_execution",
		source="frappe",
		payload={
			"console_log": doc.name, "by": doc.owner, "type": doc.get("type"), "committed": cint(doc.get("committed")),
			"excerpt": app_security.excerpt(doc.get("script")),
		},
	)  # fmt: skip


# Role Permission Manager (Desk): `add` inserts a Custom DocPerm, but `update`, `remove` and
# `reset` write it with raw SQL, so no doc event fires. They are read from the request instead.
PERMISSION_MANAGER = "frappe.core.page.permission_manager.permission_manager."
PERMISSION_ACTIONS = {"add": "added", "update": "changed", "remove": "removed", "reset": "reset to standard"}


RESET_PASSWORD = "frappe.core.doctype.user.user.reset_password"
RESET_OTP_SECRET = "frappe.twofactor.reset_otp_secret"
RESET_LDAP_PASSWORD = "frappe.integrations.doctype.ldap_settings.ldap_settings.reset_password"


def _doctype_module(doctype):
	"""The dotted path of a DocType's controller module, for a `/api/v2/method/<DocType>/<m>` call,
	from Frappe's own cached maps (frappe.modules.utils.get_doctype_module and module_app): nothing
	imported and nothing thrown, as a guest's request may name any DocType. None when unknown."""
	try:
		modules = frappe.cache.get_value(
			"doctype_modules", generator=lambda: dict(frappe.qb.from_("DocType").select("name", "module").run())
		)
		module = (modules or {}).get(doctype)
		app = module and (getattr(frappe.local, "module_app", None) or {}).get(frappe.scrub(module))
		return app_security.doctype_module_path(app, module, doctype) if app else None
	except Exception:
		return None


def request_method():
	"""The whitelisted method the current request runs, in Frappe's own order (app_security.
	called_method), or None outside a method call."""
	path = getattr(getattr(frappe.local, "request", None), "path", "")
	return app_security.called_method(path, frappe.form_dict, _doctype_module)


def after_request(response=None, request=None):
	"""hooks.py after_request: runs after the request's commit, so each signal commits its own event.

	It also runs when the request failed (a refused or rate-limited call): each check says which
	answers count.
	"""
	try:
		method = app_security.called_method(getattr(request, "path", ""), frappe.form_dict, _doctype_module)
		if not method:
			return
		if method.startswith(PERMISSION_MANAGER):
			permission_manager_call(method, response)
		elif method == RESET_PASSWORD:
			password_reset_call(response)
		elif method == RESET_OTP_SECRET:
			otp_reset_call(response, "otp_secret")
		elif method == RESET_LDAP_PASSWORD:
			otp_reset_call(response, "ldap_password")
	except Exception:
		frappe.logger("dodock_wolf").exception("could not record a request signal")


def permission_manager_call(method, response):
	action = PERMISSION_ACTIONS.get(method.rsplit(".", 1)[-1])
	if not action or getattr(response, "status_code", None) != 200 or not _app_security():
		return
	args = frappe.form_dict
	doctype = args.get("doctype") or args.get("parent")
	role = args.get("role")
	detail = {k: args.get(k) for k in ("permlevel", "ptype", "value", "if_owner") if args.get(k) is not None}
	subject = f"{role} on {doctype}" if role else doctype
	events.emit(
		"security",
		f"Permission rule {action}: {subject}"[:255],
		severity="warning",
		category="permission_change",
		source="frappe",
		payload={"doctype": doctype, "role": role, "action": action, **detail, "by": frappe.session.user},
		fingerprint=fingerprint("permission_change", doctype, role),
		dedupe_minutes=10,
	)
	frappe.db.commit()


# a guest's reset requests: one event per address and account in the window, up to this many
# accounts per address; past it, one event for the address (`many_accounts`)
RESET_WINDOW_MINUTES = 10
RESET_ACCOUNTS_PER_IP = 20


def password_reset_call(response):
	"""`password_reset_requested` for each call of the "Forgot password" method by a guest,
	answered or refused (unknown account, rate limit): bursts mean account enumeration or a
	takeover attempt.

	The account is whatever the visitor typed: it is kept as a keyed hash (app_security.identity_hash),
	and by name only when it is an existing user. A decoy user is a honeytoken touch instead.
	A signed-in user's requests (Desk's Reset Password button) are not a guest's: one event per user
	in the window, with `by`, so an administrator inviting users does not look like a burst.
	"""
	typed = str(frappe.form_dict.get("user") or "").strip()
	if not typed:
		return
	settings = _settings()
	if typed.lower() in decoy_users(settings):
		from dodock_wolf.api import threat

		threat.touched("user", typed, {"via": "password reset"})
		frappe.db.commit()
		return
	if not cint(settings.capture_login_failures):
		return
	ip = getattr(frappe.local, "request_ip", None)
	status = getattr(response, "status_code", None)
	by = frappe.session.user
	if by and by != "Guest":
		title = f"Password reset requested by signed-in user {by} from {ip or 'unknown IP'}"
		payload = {"by": by, "signed_in": True, "ip": ip, "status": status}
		key = ("by", by)
	else:
		site_key = frappe.conf.get("encryption_key")  # never created from a guest's request
		user_hash = app_security.identity_hash(typed, links.derive_key(site_key, app_security.IDENTITY_CONTEXT)) if site_key else None
		if user_hash and not _new_reset_account(ip, user_hash):
			title = f"Password reset requested for many accounts from {ip or 'unknown IP'}"
			payload = {"user_hash": None, "many_accounts": True, "ip": ip, "status": status}
			key = ("many accounts",)
		else:
			user = frappe.db.exists("User", typed) or None
			title = f"Password reset requested for {user or 'an unknown account'} from {ip or 'unknown IP'}"
			payload = {"user_hash": user_hash, "user_exists": bool(user), "ip": ip, "status": status}
			if user:
				payload["user"] = user
			key = (user_hash,)
	events.emit(
		"security",
		title[:255],
		severity="info",
		category="password_reset_requested",
		source="frappe",
		payload=payload,
		# one row per address and account (`count` the repeats): rows count the accounts an address
		# asked for (presets)
		fingerprint=fingerprint("password_reset_requested", ip, *key),
		dedupe_minutes=RESET_WINDOW_MINUTES,
		enrich=False,  # a guest can send many: no reputation or CrowdSec lookup for an info event
	)
	frappe.db.commit()


def _new_reset_account(ip, account):
	"""True when `account` gets an event of its own: it is among the first RESET_ACCOUNTS_PER_IP
	accounts this address asked a reset for in the window. Kept in the cache, in a set that never
	holds more than that and expires RESET_WINDOW_MINUTES after its first account."""
	key = frappe.cache.make_key(f"wolf_password_reset|{ip or ''}")
	pipe = frappe.cache.pipeline()
	pipe.sismember(key, account)
	pipe.scard(key)
	known, size = pipe.execute()
	if known:
		return True
	if size >= RESET_ACCOUNTS_PER_IP:
		return False
	pipe = frappe.cache.pipeline()
	pipe.sadd(key, account)
	if not size:
		pipe.expire(key, RESET_WINDOW_MINUTES * 60)
	pipe.execute()
	return True


def otp_reset_call(response, kind):
	"""`credentials_reset_by_other` when someone reset another user's OTP secret (System Managers
	may): the next login registers a new authenticator, whoever holds the password. Or their LDAP
	password (LDAP Settings → Reset Password, System Managers only): it is set in the directory, so
	no User save shows it."""
	if getattr(response, "status_code", None) != 200:
		return
	settings = _settings()
	target, actor = str(frappe.form_dict.get("user") or "").strip(), frappe.session.user
	if not _app_security(settings) or not target or target == actor:
		return
	credentials_event(target, actor, kind, settings)
	frappe.db.commit()


def _permission_manager_request():
	"""True inside a Role Permission Manager call: after_request records those."""
	if getattr(frappe.local, "request", None) is None:
		return False
	method = request_method()
	return bool(method) and method.startswith(PERMISSION_MANAGER)


def _via():
	"""How a change came in, for the event: Data Import, a request path, or neither."""
	if frappe.flags.in_import:
		return "data import"
	path = getattr(getattr(frappe.local, "request", None), "path", None)
	return path or "background job or console"


def _standard_rule(doc):
	"""The DocType's own rule a new Custom DocPerm copies, if any: Frappe copies every standard
	rule into Custom DocPerm before the first custom change, and a copy grants nothing."""
	key = {"parent": doc.get("parent"), "role": doc.get("role"), "permlevel": cint(doc.get("permlevel")),
	       "if_owner": cint(doc.get("if_owner"))}  # fmt: skip
	return frappe.db.get_value("DocPerm", key, [*app_security.DOCPERM_RIGHTS, "if_owner", "role", "parent"], as_dict=True)


def _docperm_event(doc, action, change):
	parent, role = doc.get("parent"), doc.get("role")
	granted = change.get("granted") or []
	everyone = role in app_security.EVERYONE_ROLES and bool(granted)
	title = f"Permission rule {action}: {role} on {parent}"
	if granted:
		title += f", grants {', '.join(granted)}"
	elif change.get("revoked"):
		title += f", removes {', '.join(change['revoked'])}"
	events.emit(
		"security",
		title[:255],
		severity="critical" if everyone else "warning",
		category="permission_change",
		source="frappe",
		payload={
			"kind": "custom_docperm", "doctype": parent, "role": role, "action": action, "permlevel": doc.get("permlevel"),
			"if_owner": cint(doc.get("if_owner")), **change, "everyone": everyone, "by": frappe.session.user, "via": _via(),
		},
		# only the same change again is merged (a Data Import repeating a row): another right, or
		# a grant after a removal, is an event of its own
		fingerprint=fingerprint("permission_change", "custom_docperm", parent, role, action, ",".join(granted),
		                        ",".join(change.get("revoked") or [])),
		dedupe_minutes=10,
	)  # fmt: skip


@_safe
def on_custom_docperm(doc):
	"""Custom DocPerm saved outside the Role Permission Manager: Data Import, the REST API, code."""
	if not _app_security() or _permission_manager_request():
		return
	before = _before(doc)
	reference = before or _standard_rule(doc)
	change = app_security.docperm_change(reference, doc.as_dict())
	if change:
		_docperm_event(doc, "changed" if before else "added", change)


@_safe
def on_custom_docperm_trash(doc):
	if not _app_security() or _permission_manager_request():
		return
	rights = [r for r in app_security.DOCPERM_RIGHTS if cint(doc.get(r))]
	if rights:
		_docperm_event(doc, "removed", {"granted": [], "revoked": rights})


def _user_permission_event(doc, before, after):
	others = frappe.db.count("User Permission", {"user": doc.user, "allow": doc.allow, "name": ("!=", doc.name)})
	if not app_security.user_permission_widens(before, after, others):
		return
	if after is None:
		action, title = "removed", f"User Permission removed: {doc.user} no longer restricted on {doc.allow}"
	elif before:
		action, title = "changed", f"User Permission changed: {doc.user} on {doc.allow} {doc.for_value}"
	else:
		action, title = "added", f"User Permission added: {doc.user} may also see {doc.allow} {doc.for_value}"
	previous = {k: before.get(k) for k in app_security.USER_PERMISSION_TARGET + app_security.USER_PERMISSION_NARROWING} if before else None
	events.emit(
		"security",
		title[:255],
		severity="warning",
		category="permission_change",
		source="frappe",
		payload={
			"kind": "user_permission", "action": action, "user": doc.user, "allow": doc.allow, "for_value": doc.for_value,
			"applicable_for": doc.get("applicable_for"), "previous": previous, "other_values": others,
			"by": frappe.session.user, "via": _via(),
		},
		fingerprint=fingerprint("permission_change", "user_permission", action, doc.user, doc.allow, doc.for_value),
		dedupe_minutes=10,
	)  # fmt: skip


@_safe
def on_user_permission(doc):
	"""`permission_change` when a User Permission lets its user see more (app_security)."""
	if _app_security():
		_user_permission_event(doc, _before(doc), doc.as_dict())


@_safe
def on_user_permission_trash(doc):
	if _app_security():
		_user_permission_event(doc, doc.as_dict(), None)


@_safe
def on_role_profile(doc):
	"""A Role Profile change re-grants its roles to every user who has the profile."""
	if not _app_security():
		return
	before = _before(doc)
	roles = sorted({r.role for r in doc.get("roles") or []})
	old = sorted({r.get("role") for r in (before or {}).get("roles") or []})
	added = sorted(set(roles) - set(old))
	if before and not added:
		return  # roles only removed, or nothing that grants more
	events.emit(
		"security",
		f"Role Profile {doc.name} {'created' if not before else 'now grants ' + ', '.join(added)}"[:255],
		severity="warning",
		category="permission_change",
		source="frappe",
		payload={"role_profile": doc.name, "roles": roles, "added": added, "by": frappe.session.user},
	)


@_safe
def on_system_settings(doc):
	"""`security_settings_weakened`: a System Settings save lowered a defence."""
	if not _app_security():
		return
	rows = app_security.weakened(_before(doc), doc.as_dict())
	if not rows:
		return
	events.emit(
		"security",
		f"Security settings weakened: {', '.join(r['label'] for r in rows)}"[:255],
		severity="critical",
		category="security_settings_weakened",
		source="frappe",
		payload={"changes": rows, "by": frappe.session.user},
	)


@_safe
def on_role(doc):
	"""`security_settings_weakened`: a Role's two-factor authentication turned off. Its users then
	log in with their password alone (when System Settings enables 2FA at all)."""
	_role_2fa_event(doc, _before(doc), doc.as_dict())


@_safe
def on_role_trash(doc):
	"""The same when a role with two-factor authentication on is deleted: its users lose it too."""
	_role_2fa_event(doc, doc.as_dict(), None)


def _role_2fa_event(doc, before, after):
	settings = _settings()
	if not _app_security(settings):
		return
	row = app_security.role_2fa_off(before, after)
	if not row:
		return
	deleted = after is None
	privileged = doc.name in privileged_roles(settings)
	events.emit(
		"security",
		(f"Security settings weakened: role {doc.name} with two-factor authentication deleted" if deleted else
		 f"Security settings weakened: two-factor authentication off for role {doc.name}")[:255],
		severity="critical" if privileged else "warning",
		category="security_settings_weakened",
		source="frappe",
		payload={
			"kind": "role_2fa", "role": doc.name, "changes": [row], "privileged_role": privileged,
			**({"deleted": True} if deleted else {}),
			"system_2fa": cint(frappe.db.get_single_value("System Settings", "enable_two_factor_auth")),
			"by": frappe.session.user, "via": _via(),
		},
		fingerprint=fingerprint("security_settings_weakened", "role_2fa", doc.name, "deleted" if deleted else ""),
		dedupe_minutes=10,
	)  # fmt: skip


@_safe
def on_webhook(doc):
	"""`webhook_external`: a Webhook created, enabled or pointed at another host sends documents out."""
	if not _app_security() or not cint(doc.get("enabled")):
		return
	before = _before(doc)
	domain = app_security.url_domain(doc.get("request_url"))
	if before and cint(before.get("enabled")) and app_security.url_domain(before.get("request_url")) == domain:
		return
	events.emit(
		"security",
		f"Webhook {doc.name} sends {doc.get('webhook_doctype')} to {domain or 'an unknown host'}"[:255],
		severity="warning",
		category="webhook_external",
		source="frappe",
		payload={
			"webhook": doc.name, "doctype": doc.get("webhook_doctype"), "event": doc.get("webhook_docevent"),
			"domain": domain, "previous_domain": app_security.url_domain((before or {}).get("request_url")),
			"by": frappe.session.user,
		},
	)  # fmt: skip


def after_migrate_marker():
	"""`bench migrate` usually means a deployment: record it for correlation."""
	try:
		events.emit("deployment", f"bench migrate on {frappe.local.site}", severity="info", category="migrate", source="frappe")
	except Exception:
		frappe.logger("dodock_wolf").exception("could not record migrate deployment")


def decoy_users(settings):
	return {u.lower() for u in setting_lines(settings.get("honeytoken_users"))}


def privileged_roles(settings):
	return {r.strip() for r in (settings.privileged_roles or "").splitlines() if r.strip()}


def is_privileged(user, settings):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles & privileged_roles(settings))


def previous_login_ips(doc):
	"""IPs of this user's earlier successful logins (latest 500)."""
	rows = frappe.get_all(
		"Activity Log",
		filters={"user": doc.user, "operation": "Login", "status": "Success", "name": ("!=", doc.name)},
		fields=["ip_address"],
		limit=500,
		order_by="creation desc",
	)
	return {r.ip_address for r in rows if r.ip_address}


BACKUP_TRACE_MARKERS = ("frappe/utils/backups.py", "frappe.utils.backups", "offsite_backup_utils")


def is_backup_failure(title, trace=""):
	"""Error Logs of failed backups. Frappe's S3/Dropbox/Google Drive integrations name the
	backup in the title or method ("Dropbox Backup Failed", "...take_backups_..."); a
	traceback through frappe/utils/backups.py is a failed `bench backup` / scheduled backup."""
	if "backup" in str(title or "").lower():
		return True
	tail = (trace or "")[-4000:]
	return any(m in tail for m in BACKUP_TRACE_MARKERS)
