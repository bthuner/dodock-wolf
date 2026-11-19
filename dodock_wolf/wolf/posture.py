"""Security posture of a site: weighted checks and a score (no frappe imports).

Each check is `pass`, `fail` or `unknown`, with the evidence it read and the fix. The score is
the weight of the checks that passed over the weight of all checks: a check Wolf cannot read
(no agent on the host, a remote site whose settings Wolf cannot see, a stale sample) counts as
not passed, so a site never looks safer because Wolf knows less about it. `coverage` says how
much of the weight Wolf could read at all.

Facts come from two places (api/security.py gathers them):
- the site Wolf runs on: its System Settings, roles and site config;
- for other sites, the agent's `site_setting` samples: the same System Settings and the
  System Manager role's two-factor flag, read from each site's database;
- the agent's latest samples for any site: `site_config_risks`, `exposed_services` on the
  hosts serving it, `backup_age_hours`, `tls_days_left` and `hsts_max_age_days`.

The versions of Frappe and ERPNext come from the agent's `app_version` samples for the site's
benches (and, on the Wolf site, from its own packages); the advisories from GitHub
(wolf/advisories.py, api/advisories.py).

SPF and DMARC are read from DNS by the site itself, for the domains its outgoing Email
Accounts send from (api/security.py); other sites' mail domains are unknown to Wolf.
"""

from dodock_wolf.wolf import advisories
from dodock_wolf.wolf.i18n import _, fmt

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
MIN_PASSWORD_SCORE = 3
MAX_LOGIN_ATTEMPTS = 10
MAX_BACKUP_HOURS = 26
MIN_TLS_DAYS = 14
MIN_HSTS_DAYS = 180  # browsers' preload list asks a year; six months is the usual floor
STRICT_DMARC = ("quarantine", "reject")

# id, label, weight, fix: label and fix are read when a row is built, in the reader's language
CHECKS = [
	("two_factor", lambda: _("Two-factor authentication for System Managers"), 3,
	 lambda: _("System Settings → Enable Two Factor Auth, and tick Two Factor Authentication on the System Manager role.")),
	("password_policy", lambda: _("Password policy"), 2,
	 lambda: fmt(_("System Settings → Enable Password Policy, minimum score {0} or more."), MIN_PASSWORD_SCORE)),
	("login_lockout", lambda: _("Lockout after failed logins"), 1,
	 lambda: fmt(_("System Settings → Allow Consecutive Login Attempts between 1 and {0}."), MAX_LOGIN_ATTEMPTS)),
	("guest_uploads", lambda: _("Guests cannot upload files"), 1, lambda: _("System Settings → untick Allow Guests to Upload Files.")),
	("site_config", lambda: _("No development settings in site_config.json"), 3,
	 lambda: _("Remove developer_mode and allow_tests, use https:// in host_name, list allowed origins in allow_cors.")),
	("exposure", lambda: _("Bench services not listening beyond loopback"), 3,
	 lambda: _("Bind MariaDB, Redis, socket.io and gunicorn to 127.0.0.1 (or a private address) and keep a firewall in front.")),
	("backup", lambda: fmt(_("A backup newer than {0} h"), MAX_BACKUP_HOURS), 2, lambda: _("Check the scheduler and the backup job (bench backup).")),
	("tls", lambda: fmt(_("TLS certificates valid for {0} days or more"), MIN_TLS_DAYS), 2,
	 lambda: _("Renew the certificate (bench setup lets-encrypt).")),
	("hsts", lambda: fmt(_("HSTS for {0} days or more"), MIN_HSTS_DAYS), 1,
	 lambda: _("Add `add_header Strict-Transport-Security \"max-age=31536000\" always;` to the site's HTTPS server block in nginx.")),
	("spf", lambda: _("SPF for the mail domain, ending in -all or ~all"), 1,
	 lambda: _("Publish one TXT record `v=spf1 <your senders> -all` on the domain the site sends email from.")),
	("dmarc", lambda: _("DMARC policy quarantine or reject"), 1,
	 lambda: _("Publish `v=DMARC1; p=quarantine; rua=mailto:...` at _dmarc.<domain> (after a while at p=none to check reports).")),
	("advisories", lambda: _("No published security advisory applies to Frappe or ERPNext"), 3,
	 lambda: _("Update the bench (bench update) to the version the evidence names, or a later one of the same line.")),
]  # fmt: skip


def _row(check_id, status, evidence):
	label, weight, fix = next(c[1:] for c in CHECKS if c[0] == check_id)
	return {"id": check_id, "label": label(), "weight": weight, "status": status, "evidence": evidence,
	        "fix": fix() if status == FAIL else None}  # fmt: skip


def _num(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _pair(name, text):
	"""`name: text`, with the reader's punctuation (French puts a space before the colon)."""
	return fmt(_("{0}: {1}"), name, text)


def check_settings(settings, system_manager_2fa):
	"""The four System Settings checks. `settings` is None for a site Wolf cannot read."""
	if settings is None:
		why = _("no recent site_setting sample: the agent reads them from the site's database (MariaDB or Postgres client on its host)")
		return [_row(c, UNKNOWN, why) for c in ("two_factor", "password_policy", "login_lockout", "guest_uploads")]
	rows = []
	on = bool(_num(settings.get("enable_two_factor_auth")))
	if on and system_manager_2fa:
		rows.append(_row("two_factor", PASS, _("enabled, and required for the System Manager role")))
	else:
		rows.append(_row("two_factor", FAIL, _("disabled in System Settings") if not on else _("enabled, but not required for System Managers")))
	score = _num(settings.get("minimum_password_score")) or 0
	if bool(_num(settings.get("enable_password_policy"))) and score >= MIN_PASSWORD_SCORE:
		rows.append(_row("password_policy", PASS, fmt(_("enabled, minimum score {0}"), f"{score:g}")))
	else:
		policy_on = _num(settings.get("enable_password_policy"))
		rows.append(_row("password_policy", FAIL, _("disabled in System Settings") if not policy_on else fmt(_("minimum score {0}"), f"{score:g}")))
	attempts = _num(settings.get("allow_consecutive_login_attempts"))
	if attempts is not None and 1 <= attempts <= MAX_LOGIN_ATTEMPTS:
		text = _("locked after 1 failed login") if attempts == 1 else fmt(_("locked after {0} failed logins"), f"{attempts:g}")
		rows.append(_row("login_lockout", PASS, text))
	else:
		text = _("no lockout") if not attempts else fmt(_("{0} attempts allowed"), f"{attempts:g}")
		rows.append(_row("login_lockout", FAIL, text))
	uploads = bool(_num(settings.get("allow_guests_to_upload_files")))
	rows.append(_row("guest_uploads", FAIL if uploads else PASS, _("guests may upload files") if uploads else _("guests may not upload")))
	return rows


def check_site_config(findings=None, risks=None):
	"""`findings` (settings names, read on the site itself) win over the agent's `risks` count."""
	if findings is not None:
		if findings:
			return _row("site_config", FAIL, ", ".join(findings))
		return _row("site_config", PASS, _("none of developer_mode, allow_tests, plain-HTTP host_name, allow_cors *"))
	if risks is None:
		return _row("site_config", UNKNOWN, _("no recent site_config_risks sample from an agent"))
	if risks:
		if risks == 1:
			return _row("site_config", FAIL, _("1 risky setting reported by the agent (see the insecure_site_config event)"))
		return _row("site_config", FAIL, fmt(_("{0} risky settings reported by the agent (see the insecure_site_config event)"), f"{risks:g}"))
	return _row("site_config", PASS, _("the agent found no risky setting"))


def check_exposure(per_host):
	"""`per_host`: {host: exposed_services} for the hosts serving the site (None when unknown)."""
	known = {h: v for h, v in (per_host or {}).items() if v is not None}
	if not known:
		return _row("exposure", UNKNOWN, _("no recent exposed_services sample from the agent on this site's hosts"))
	exposed = {h: v for h, v in known.items() if v}
	if exposed:
		hosts = "; ".join(_pair(h, _("1 service") if v == 1 else fmt(_("{0} services"), f"{v:g}")) for h, v in sorted(exposed.items()))
		return _row("exposure", FAIL, fmt(_("{0} (see the service_exposed events; a firewall may still block them)"), hosts))
	return _row("exposure", PASS, fmt(_("nothing beyond loopback on {0}"), ", ".join(sorted(known))))


def check_backup(age_hours):
	if age_hours is None:
		return _row("backup", UNKNOWN, _("no recent backup_age_hours sample"))
	if age_hours <= MAX_BACKUP_HOURS:
		return _row("backup", PASS, fmt(_("newest backup {0} h old (recency only, not a restore test)"), f"{age_hours:.1f}"))
	return _row("backup", FAIL, fmt(_("newest backup {0} h old"), f"{age_hours:.1f}"))


def check_tls(days_left):
	if days_left is None:
		return _row("tls", UNKNOWN, _("no recent tls_days_left sample"))
	days = f"{days_left:.0f}"
	if days_left >= MIN_TLS_DAYS:
		return _row("tls", PASS, fmt(_("the first certificate to expire has {0} days left"), days))
	if days == "1":
		return _row("tls", FAIL, _("a certificate expires in 1 day"))
	return _row("tls", FAIL, fmt(_("a certificate expires in {0} days"), days))


def check_hsts(per_domain):
	"""`per_domain`: {domain: max-age in days} from the agent's latest samples (0: no header)."""
	if not per_domain:
		return _row("hsts", UNKNOWN, _("no recent hsts_max_age_days sample (the agent reads it with the TLS check)"))
	short = {d: v for d, v in per_domain.items() if v < MIN_HSTS_DAYS}
	if short:
		return _row("hsts", FAIL, "; ".join(_pair(d, _("no header") if not v else _days(v)) for d, v in sorted(short.items())))
	return _row("hsts", PASS, fmt(_("{0}: {1} days or more"), ", ".join(sorted(per_domain)), f"{min(per_domain.values()):g}"))


def _days(value):
	return _("1 day") if value == 1 else fmt(_("{0} days"), f"{value:g}")


def spf_verdict(records):
	"""(ok, why) for a domain's TXT records."""
	spf = [r.strip() for r in records if r.strip().lower().startswith("v=spf1")]
	if not spf:
		return False, _("no SPF record")
	if len(spf) > 1:
		return False, fmt(_("{0} SPF records: receivers treat that as an error"), len(spf))
	terms = spf[0].lower().split()[1:]
	last = next((t for t in reversed(terms) if t.lstrip("+-~?") == "all"), None)
	if last in ("-all", "~all"):
		return True, fmt(_("ends in {0}"), last)
	if last is None:
		redirect = next((t for t in terms if t.startswith("redirect=")), None)
		if redirect:
			return True, fmt(_("delegated with {0} (not followed)"), redirect)
		return False, _("no all term: any other sender passes as neutral")
	if last in ("all", "+all"):
		return False, fmt(_("ends in {0}: any sender is accepted"), last)
	return False, fmt(_("ends in {0}: neutral"), last)


def dmarc_verdict(records, subdomain=False):
	"""(ok, why) for the TXT records of _dmarc.<domain>; `subdomain` reads sp= when present."""
	dmarc = [r.strip() for r in records if r.strip().lower().startswith("v=dmarc1")]
	if not dmarc:
		return False, _("no DMARC record")
	if len(dmarc) > 1:
		return False, fmt(_("{0} DMARC records: receivers ignore them all"), len(dmarc))
	tags = dict((k.strip().lower(), v.strip().lower()) for k, _eq, v in (t.partition("=") for t in dmarc[0].split(";")) if k.strip())
	policy = (tags.get("sp") if subdomain else None) or tags.get("p") or "none"
	pct = tags.get("pct", "100")
	if policy in STRICT_DMARC:
		if pct != "100":
			return True, fmt(_("p={0}, applied to {1}% of messages"), policy, pct)
		return True, f"p={policy}"
	return False, fmt(_("p={0}: reports only, spoofed mail is still delivered"), policy)


def _mail_check(check_id, per_domain):
	"""`per_domain`: {domain: (ok, why)} or {domain: None} when DNS could not tell."""
	if not per_domain:
		return _row(check_id, UNKNOWN, _("no outgoing Email Account on this site, or another site's mail domain"))
	if any(v is None for v in per_domain.values()):
		failed = ", ".join(sorted(d for d, v in per_domain.items() if v is None))
		return _row(check_id, UNKNOWN, fmt(_("DNS did not answer for {0}"), failed))
	bad = {d: why for d, (ok, why) in per_domain.items() if not ok}
	if bad:
		return _row(check_id, FAIL, "; ".join(_pair(d, why) for d, why in sorted(bad.items())))
	return _row(check_id, PASS, "; ".join(_pair(d, why) for d, (_ok, why) in sorted(per_domain.items())))


def check_spf(per_domain):
	return _mail_check("spf", per_domain)


def check_dmarc(per_domain):
	return _mail_check("dmarc", per_domain)


def check_advisories(versions, sources):
	"""`versions`: {app: {(major, minor, patch)}} for the apps advisories cover.
	`sources`: None when the check is off, else {app: {"advisories": [...] or None, "why": str}}
	("why" says why there is no usable list: never fetched, failing, too old)."""
	if sources is None:
		return _row("advisories", UNKNOWN, _("the advisory check is off in Wolf Settings"))
	versions = {app: v for app, v in (versions or {}).items() if v}
	if not versions:
		return _row("advisories", UNKNOWN, _("no app_version sample from an agent on this site's benches"))
	affected, unknown, clear = [], [], []
	for app in sorted(versions):
		source = sources.get(app) or {}
		for version in sorted(versions[app]):
			if source.get("advisories") is None:
				unknown.append(_pair(f"{app} {advisories.fmt(version)}", source.get("why") or _("advisories not fetched yet")))
				continue
			result = advisories.assess(app, version, source["advisories"])
			if result["status"] == "affected":
				ids = ", ".join(a["id"] for a in result["found"][:3] if a.get("id"))
				affected.append(f"{advisories.summary(result)}" + (f" ({ids}{', ...' if len(result['found']) > 3 else ''})" if ids else ""))
			elif result["status"] == "unknown":
				unknown.append(result["why"])
			else:
				clear.append(f"{app} {result['version']}")
	if affected:
		return _row("advisories", FAIL, "; ".join(affected + unknown))
	if unknown:
		return _row("advisories", UNKNOWN, "; ".join(unknown + [fmt(_("{0}: no advisory applies"), c) for c in clear]))
	return _row("advisories", PASS, fmt(_("{0}: no published advisory applies"), ", ".join(clear)))


def score(rows):
	"""`{score, coverage, passed, failed, unknown}`: score and coverage in 0..100."""
	total = sum(r["weight"] for r in rows) or 1
	passed = sum(r["weight"] for r in rows if r["status"] == PASS)
	known = sum(r["weight"] for r in rows if r["status"] != UNKNOWN)
	count = {s: sum(1 for r in rows if r["status"] == s) for s in (PASS, FAIL, UNKNOWN)}
	return {
		"score": round(100 * passed / total),
		"coverage": round(100 * known / total),
		"passed": count[PASS], "failed": count[FAIL], "unknown": count[UNKNOWN],
	}  # fmt: skip


def evaluate(facts):
	"""All checks and the score from a facts dict (see api/security.py for its keys)."""
	rows = check_settings(facts.get("settings"), facts.get("system_manager_2fa"))
	rows.append(check_site_config(facts.get("site_config_findings"), facts.get("site_config_risks")))
	rows.append(check_exposure(facts.get("exposed_services")))
	rows.append(check_backup(facts.get("backup_age_hours")))
	rows.append(check_tls(facts.get("tls_days_left")))
	rows.append(check_hsts(facts.get("hsts_max_age_days")))
	rows.append(check_spf(facts.get("spf")))
	rows.append(check_dmarc(facts.get("dmarc")))
	rows.append(check_advisories(facts.get("app_versions"), facts.get("advisories")))
	return {"checks": rows, **score(rows)}
