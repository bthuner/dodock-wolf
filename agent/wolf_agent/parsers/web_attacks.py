"""Web attack probes in nginx access logs (scanners, injection attempts, exposed files).

`classify(method, target, status, user_agent)` returns the names of the probe rules a
request matches. The nginx parser aggregates matches per (site, client address) and ships
`security` events:

- `web_attack_probe`: requests that look like a scanner or an injection attempt
  (warning; critical once a client sends `CRITICAL_THRESHOLD` of them in one interval);
- `web_sensitive_file_exposed`: a request for a secret-bearing file (`.env`, `.git/`,
  database dumps, private keys) answered with a 2xx: the file was probably served (critical).

Patterns are deliberately conservative: a Frappe site never serves these paths, so a match
is a probe, not a false positive from normal traffic.

Two Frappe rules are rates, not single requests (RATE_RULES): one call is normal, a burst from one
client in one minute is not.

- `frappe_auth_abuse` (`/api/method` and `/api/v2/method`): the guest endpoints that tell whether an account exists or take a
  credential outside the login page: password reset (GHSA-3vqc-c545-w7jg), login links, sign-up,
  personal data deletion confirmation (GHSA-c2xv-c53h-qvr5), the OAuth2 token endpoint (whose
  password grant skipped two-factor authentication, GHSA-h3mh-9vmc-cpfg), LDAP and key or token
  logins. Failed logins on the login page are the site's own `frappe_failed_login`.
- `frappe_api_forbidden`: `/api/method`, `/api/resource` or `/api/v2` answered 403, on several
  methods: methods tried without the right to call them. 401 is left out: it also means "session
  expired", as after a deploy.

Both count from one client over a sliding window of RATE_WINDOW minutes.

A SQL injection carried in a header (GHSA-vp4r-5v6w-r962, `X-Frappe-Request-Id`) or a request body
is not in an access log: Suricata sees those.
"""

import re
from urllib.parse import unquote_plus

# rule -> regex over the decoded, lower-cased request target (path and query)
_RULES = [
	# secret-bearing files: also checked for a 2xx answer (see SENSITIVE_RULES)
	("env_file", r"(?:^|/)\.env(?:\.[\w-]+)?/?(?:$|[?#])"),
	("vcs_metadata", r"(?:^|/)\.(?:git|svn|hg)(?:/|$)"),
	("secret_file", r"(?:^|/)(?:id_(?:rsa|dsa|ecdsa|ed25519)|\.htpasswd|\.aws/(?:credentials|config)|\.ssh/|"
	 r"site_config\.json|common_site_config\.json|wp-config\.php(?:\.bak|~)?|\.ds_store|"
	 r"\.git-credentials|\.npmrc|\.pypirc|\.netrc|\.docker/config\.json|(?:docker-)?compose(?:\.[\w-]+)?\.ya?ml|"
	 r"\.vscode/sftp\.json|sftp-config\.json|\.kube/config|credentials\.json|secrets\.(?:ya?ml|json)|"
	 r"storage/logs/laravel\.log)/?(?:$|[?#])"),
	("backup_dump", r"(?:^|/)[\w.-]*\.(?:sql|sql\.gz|sqlite3?|bak|old|tar\.gz|tgz|zip)(?:$|[?#])"),
	# CMS / admin panels that do not exist on a Frappe bench
	("cms_probe", r"(?:^|/)(?:wp-(?:login|admin|includes|content)|xmlrpc\.php|wordpress/|joomla|"
	 r"administrator/index\.php|phpmyadmin|pma/|adminer(?:\.php)?|phpinfo\.php|server-status|"
	 r"vendor/phpunit|cgi-bin/|boaform|hnap1|actuator/|solr/admin|manager/html|console/|"
	 r"_ignition/|telescope/|owa/|autodiscover/autodiscover\.xml)"),
	# edge appliances and servers scanned for their known vulnerabilities (Fortinet, Palo Alto,
	# Ivanti/Pulse, Citrix, Cisco ASA, F5, Exchange, Confluence/Struts, GeoServer, Jenkins, .NET
	# debug pages). Matched on the path only and from its root: a DocType or a web page may well be
	# called Jenkins (/app/jenkins/…, /blog/jenkins/…), and a query string names any path
	("appliance_probe", r"^/(?:remote/(?:login|fgt_lang|logincheck)|api/v2/cmdb/|global-protect/|ssl-vpn/|"
	 r"dana-na/|dana-cached/|vpns?/(?:index\.html|\.\./)|citrix/|nf/auth/|[+ ]cscoe[+ ]/|[+ ]cscol[+ ]/|mgmt/tm/|tmui/|"
	 r"ecp/default\.aspx|mapi/nspi|ews/exchange\.asmx|autodiscover/autodiscover\.json|"
	 r"pages/createpage-entervariables\.action|setup/setupadministrator\.action|[\w-]+\.action(?:$|;)|"
	 r"geoserver/|jenkins/|elmah\.axd|trace\.axd|_profiler/|debug/pprof|web\.config/?$|"
	 r"gponform/|setup\.cgi|wls-wsat/|_wpeprivate/)"),
	("path_traversal", r"(?:\.\./|\.\.\\|/etc/(?:passwd|shadow|hosts)|c:\\windows|/proc/self/)"),
	("sql_injection", r"(?:union(?:\s|/\*.*?\*/)+(?:all\s+)?select|"
	 r"'\s*(?:or|and)\s*'?\d+'?\s*=\s*'?\d+|\bsleep\s*\(\s*\d+\s*\)|benchmark\s*\(|"
	 r"information_schema|waitfor\s+delay|;\s*drop\s+table)"),
	("xss", r"(?:<script|javascript:|onerror\s*=|onload\s*=|<svg[^>]*on\w+\s*=|document\.cookie)"),
	("command_injection", r"(?:;\s*(?:cat|wget|curl|uname|bash|sh)\b|;\s*id(?:\s|;|$)|\$\(|`[^`]*`|\|\s*(?:sh|bash)\b|"
	 r"\$\{jndi:|/bin/(?:sh|bash)|^/shell\?cd\s)"),
	("template_injection", r"(?:\{\{.*?\}\}|\$\{.*?\}|<%.*?%>)"),
]
_COMPILED = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in _RULES]

# Frappe's guest endpoints that check an account or take a credential, outside the login page
_FRAPPE_AUTH = re.compile(
	r"^/api/(?:v2/)?method/(?:"
	r"frappe\.core\.doctype\.user\.user\.(?:reset_password|sign_up|update_password)|"
	r"frappe\.www\.login\.(?:send_login_link|login_via_key|login_via_token)|"
	r"frappe\.website\.doctype\.personal_data_deletion_request\.personal_data_deletion_request\.confirm_deletion|"
	r"frappe\.integrations\.oauth2\.get_token|"
	r"frappe\.integrations\.doctype\.ldap_settings\.ldap_settings\.login"
	r")(?:$|[?/])"
)
_FRAPPE_API = re.compile(r"^/api/(?:method|resource|v2)/")
# rule -> (requests, distinct paths) from one client within RATE_WINDOW minutes before it is a
# probe: one call is normal; a forbidden storm also needs several methods (a page polling one
# forbidden resource is not someone trying methods)
RATE_RULES = {"frappe_auth_abuse": (10, 1), "frappe_api_forbidden": (20, 5)}
RATE_WINDOW = 2

# Known offensive tooling identifying itself in the User-Agent.
_SCANNER_UA = re.compile(
	r"(?:sqlmap|nikto|nmap|masscan|zgrab|nuclei|wpscan|dirbuster|gobuster|feroxbuster|ffuf|"
	r"fuzz faster u fool|wfuzz|acunetix|nessus|openvas|qualys|hydra|jaeles|whatweb|httpx|interactsh|"
	r"dirsearch|katana|arachni|skipfish|commix|xsstrike|projectdiscovery|l9explore|l9tcpid|w3af)",
	re.IGNORECASE,
)

# Frappe serves user attachments (/files, /private/files) and authorized backup downloads
# (/backups, System Manager only): a .zip or .sql.gz there is normal traffic.
_DUMP_ALLOWED_PREFIXES = ("/files/", "/private/files/", "/backups/", "/assets/")
SENSITIVE_RULES = {"env_file", "vcs_metadata", "secret_file", "backup_dump"}
_FILE_PREFIXES = ("/assets/", "/files/", "/private/files/")
CRITICAL_THRESHOLD = 50
MAX_TARGET = 300

# MITRE ATT&CK techniques per rule, kept in the payload so a SOC can pivot on them.
ATTACK_TECHNIQUES = {
	"env_file": "T1552.001",
	"vcs_metadata": "T1213",
	"secret_file": "T1552.004",
	"backup_dump": "T1530",
	"cms_probe": "T1595.003",
	"path_traversal": "T1190",
	"sql_injection": "T1190",
	"xss": "T1189",
	"command_injection": "T1190",
	"template_injection": "T1190",
	"scanner_user_agent": "T1595.002",
	"appliance_probe": "T1595.002",
	"frappe_auth_abuse": "T1110",
	# frappe_api_forbidden: methods tried without the right to call them is no exploit of its own
}


def _decode(target):
	"""Percent-decode twice (double encoding is a classic evasion) and lower-case."""
	text = target or ""
	for _ in range(2):
		decoded = unquote_plus(text)
		if decoded == text:
			break
		text = decoded
	return text.lower()


def classify(method, target, status=None, user_agent=None):
	"""Probe rule names matched by one request (empty list for normal traffic)."""
	decoded = _decode(target)
	path = decoded.split("?", 1)[0]
	matched = []
	for name, rx in _COMPILED:
		# file and CMS rules look at the path only: a query string such as
		# `?file=report.zip` is not a probe for a backup
		subject = path if name in SENSITIVE_RULES or name in ("cms_probe", "appliance_probe") else decoded
		if not rx.search(subject):
			continue
		if name == "backup_dump" and path.startswith(_DUMP_ALLOWED_PREFIXES):
			continue
		# static assets and user files are named freely (Font Awesome's joomla.svg)
		if name == "cms_probe" and path.startswith(_FILE_PREFIXES):
			continue
		matched.append(name)
	if user_agent and _SCANNER_UA.search(user_agent):
		matched.append("scanner_user_agent")
	if _FRAPPE_AUTH.search(path):
		if "grant_type=refresh_token" not in decoded:  # an app keeping its session, when the grant is in the URL
			matched.append("frappe_auth_abuse")
	elif status == 403 and _FRAPPE_API.search(path):  # 401 is also "session expired" after a deploy
		matched.append("frappe_api_forbidden")
	return matched


# Frappe routes that answer 200 with a page for any sub-path (Desk, the Wolf UI, the API's own
# errors): a 2xx there is an HTML page, not the file the probe asked for
CATCH_ALL_PREFIXES = ("/app/", "/wolf/", "/desk/", "/api/", "/helpdesk/", "/crm/", "/hrms/", "/insights/", "/drive/")


def exposed(rules, status, target=""):
	"""True when a secret-bearing file was answered with a 2xx outside a catch-all route."""
	if not (status and 200 <= status < 300 and SENSITIVE_RULES.intersection(rules)):
		return False
	path = _decode(target).split("?", 1)[0]
	return not path.startswith(CATCH_ALL_PREFIXES)
