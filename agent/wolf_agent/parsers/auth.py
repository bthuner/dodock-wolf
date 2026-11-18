"""Auth log parser (auth.log, /var/log/secure or `journalctl -o cat`) → `security` events.

sshd: failed logins (`ssh_failed_login`), root logins (`ssh_root_login`) and a successful
login from an address that failed `BRUTE_FORCE_MIN_FAILURES` times in the last hour
(`ssh_login_after_failures`: the brute force probably worked).
sudo: wrong passwords and users outside sudoers (`sudo_failure`).
shadow-utils: new accounts (`account_created`) and users added to an admin group
(`admin_group_change`), the classic persistence and privilege escalation steps. A service account a
package adds (a system UID, 1-999, and a no-login shell: nologin or false) is `service_account_created`,
at info: no one can log in with it, and every package install that adds a service user would alert.
Giving an account a login shell later (`usermod -s`, `chsh`) or UID 0 (`usermod -u 0`) is
`account_created` too.
"""

import re
import time

from ..util import event, fingerprint, log_minute, parse_log_timestamp, utc_iso

_IP = r"(?P<ip>[0-9a-fA-F:.]+)"
_FAILED_RE = re.compile(
	r"Failed (?:password|publickey|keyboard-interactive/pam|none) for (?P<invalid>invalid user )?(?P<user>\S+) from " + _IP
)
_INVALID_RE = re.compile(r"Invalid user (?P<user>\S*) from " + _IP)
_ACCEPTED_RE = re.compile(r"Accepted (?P<method>\S+) for (?P<user>\S+) from " + _IP)
_REPEATED_RE = re.compile(r"message repeated (?P<n>\d+) times")
_SUDO_AUTH_RE = re.compile(r"pam_unix\(sudo(?:-i)?:auth\): authentication failure;.*?\bruser=(?P<user>\S*)")
_SUDO_INCORRECT_RE = re.compile(r"sudo(?:\[\d+\])?:\s+(?P<user>\S+) : (?P<n>\d+) incorrect password attempts?")
_SUDO_NOT_ALLOWED_RE = re.compile(
	r"sudo(?:\[\d+\])?:\s+(?P<user>\S+) : (?:user NOT in sudoers|command not allowed)"
)
_USERADD_RE = re.compile(r"useradd(?:\[\d+\])?: new user: name=(?P<user>[^,\s]+)(?:, UID=(?P<uid>\d+))?")
# the shell field is the one right before the closing `from=`: an earlier field (home) can hold
# commas and a fake ", shell=..."
_USERADD_SHELL_RE = re.compile(r", shell=(?P<shell>[^,\s]+), from=\S*\s*$")
# usermod -s / chsh give an account a shell; usermod -u 0 makes it a second root
_SHELL_CHANGE_RE = re.compile(
	r"(?:usermod(?:\[\d+\])?: change user '(?P<user>[^']+)' shell from '[^']*' to '(?P<shell>[^']*)'|"
	r"chsh(?:\[\d+\])?: changed user '(?P<user2>[^']+)' shell to '(?P<shell2>[^']*)')"
)
_UID_CHANGE_RE = re.compile(r"usermod(?:\[\d+\])?: change user '(?P<user>[^']+)' UID from '\d+' to '(?P<uid>\d+)'")
# exact paths only: a script named nologin elsewhere is a shell like any other
NO_LOGIN_SHELLS = {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false"}
SYSTEM_UID_MAX = 999  # UID_MIN is 1000 on Debian, Ubuntu and RHEL (login.defs)
_GROUP_ADD_RE = re.compile(
	r"(?:usermod|gpasswd)(?:\[\d+\])?: (?:add '(?P<user>[^']+)' to (?:shadow )?group '(?P<group>[^']+)'|"
	r"user (?P<user2>\S+) added by \S+ to group (?P<group2>\S+))"
)
ADMIN_GROUPS = {"sudo", "wheel", "admin", "root", "adm", "docker", "lxd"}
CRITICAL_THRESHOLD = 20
MAX_SAMPLES = 3
# a successful login after this many failures from the same address within the hour
BRUTE_FORCE_MIN_FAILURES = 5
FAILURE_MEMORY_SECONDS = 3600
MAX_TRACKED_ADDRESSES = 5000

# what each kind means for a SOC, and how it is shipped
_KINDS = {
	"ssh_failed_login": ("warning", "T1110"),
	"ssh_root_login": ("warning", "T1078.003"),
	"ssh_login_after_failures": ("critical", "T1110"),
	"sudo_failure": ("warning", "T1548.003"),
	"account_created": ("warning", "T1136.001"),
	"service_account_created": ("info", "T1136.001"),
	"admin_group_change": ("critical", "T1098"),
}


def parse_line(line):
	"""Return `{kind, ip, user, count, timestamp}` for interesting sshd lines, else None."""
	line = line.rstrip("\n")
	repeated = _REPEATED_RE.search(line)
	count = int(repeated.group("n")) if repeated else 1
	ts = parse_log_timestamp(line)

	m = _ACCEPTED_RE.search(line)
	if m:
		if m.group("user") == "root":
			return {"kind": "ssh_root_login", "ip": m.group("ip"), "user": "root", "count": count, "timestamp": ts}
		return {"kind": "ssh_accepted", "ip": m.group("ip"), "user": m.group("user"), "count": count, "timestamp": ts}

	if "sudo" in line:
		m = _SUDO_INCORRECT_RE.search(line)
		if m:
			n = int(m.group("n"))
			return {"kind": "sudo_failure", "ip": None, "user": m.group("user"), "count": n, "timestamp": ts}
		m = _SUDO_NOT_ALLOWED_RE.search(line)
		if m:
			return {"kind": "sudo_failure", "ip": None, "user": m.group("user"), "count": count, "timestamp": ts}
		# the pam line precedes "N incorrect password attempts": counted through the latter
		if _SUDO_AUTH_RE.search(line):
			return None

	m = _USERADD_RE.search(line)
	if m:
		uid = int(m.group("uid")) if m.group("uid") else None
		shell_m = _USERADD_SHELL_RE.search(line)
		shell = shell_m.group("shell") if shell_m else None
		# UID 0 (a second root), any account with a shell to log in with, or a line we cannot read
		# that far stays account_created
		service = uid is not None and 0 < uid <= SYSTEM_UID_MAX and shell in NO_LOGIN_SHELLS
		return {
			"kind": "service_account_created" if service else "account_created", "ip": None, "user": m.group("user"),
			"count": 1, "timestamp": ts, "uid": uid, "shell": shell,
		}  # fmt: skip

	# an existing account (a service one, say) given a login shell or UID 0: as good as a new account
	m = _SHELL_CHANGE_RE.search(line)
	if m:
		shell = m.group("shell") or m.group("shell2")
		if shell in NO_LOGIN_SHELLS:
			return None
		return {"kind": "account_created", "ip": None, "user": m.group("user") or m.group("user2"), "count": 1,
		        "timestamp": ts, "shell": shell, "change": "shell"}  # fmt: skip
	m = _UID_CHANGE_RE.search(line)
	if m:
		if m.group("uid") != "0":
			return None
		return {"kind": "account_created", "ip": None, "user": m.group("user"), "count": 1, "timestamp": ts,
		        "uid": 0, "change": "uid"}  # fmt: skip

	m = _GROUP_ADD_RE.search(line)
	if m:
		group = m.group("group") or m.group("group2")
		if group in ADMIN_GROUPS:
			user = m.group("user") or m.group("user2")
			return {"kind": "admin_group_change", "ip": None, "user": user, "count": 1, "timestamp": ts, "group": group}
		return None

	# "Invalid user X from IP" is logged before "Failed password for invalid user X";
	# count only the former so an attempt isn't counted twice.
	m = _INVALID_RE.search(line)
	if m:
		return {"kind": "ssh_failed_login", "ip": m.group("ip"), "user": m.group("user"), "count": count, "timestamp": ts}

	m = _FAILED_RE.search(line)
	if m and not m.group("invalid"):
		return {"kind": "ssh_failed_login", "ip": m.group("ip"), "user": m.group("user"), "count": count, "timestamp": ts}
	return None


class AuthParser:
	def __init__(self, host, log_file=None, clock=time.monotonic, **_):
		self.host, self.log_file = host, log_file
		self.clock = clock
		self.groups = {}
		# address -> [failures, last failure (clock)]: survives drains so a brute force
		# spread over several push intervals is still recognised when it succeeds
		self.failures = {}

	def _note_failure(self, ip, count):
		now = self.clock()
		entry = self.failures.get(ip)
		if entry is None or now - entry[1] > FAILURE_MEMORY_SECONDS:
			if entry is None and len(self.failures) >= MAX_TRACKED_ADDRESSES:
				self._prune(now)
				if len(self.failures) >= MAX_TRACKED_ADDRESSES:
					return
			entry = self.failures[ip] = [0, now]
		entry[0] += count
		entry[1] = now

	def _prune(self, now):
		for ip in [ip for ip, (_, last) in self.failures.items() if now - last > FAILURE_MEMORY_SECONDS]:
			del self.failures[ip]

	def _failures_before(self, ip):
		entry = self.failures.get(ip)
		if entry is None or self.clock() - entry[1] > FAILURE_MEMORY_SECONDS:
			return 0
		return entry[0]

	def feed(self, line):
		parsed = parse_line(line)
		if not parsed:
			return
		kind, ip = parsed["kind"], parsed["ip"]
		if kind == "ssh_failed_login":
			self._note_failure(ip, parsed["count"])
		elif kind in ("ssh_accepted", "ssh_root_login"):
			failures = self._failures_before(ip)
			if failures >= BRUTE_FORCE_MIN_FAILURES:
				self._group("ssh_login_after_failures", ip, parsed, line, failures=failures)
				self.failures.pop(ip, None)
			if kind == "ssh_accepted":
				return
		self._group(kind, ip, parsed, line)

	def _group(self, kind, ip, parsed, line, failures=None):
		# per-user kinds group by user, the network ones by address
		key = (log_minute(parsed["timestamp"]), kind, ip if ip else parsed["user"])
		g = self.groups.get(key)
		if not g:
			g = self.groups[key] = {"count": 0, "users": [], "timestamp": parsed["timestamp"], "samples": []}
		g["count"] += 1 if failures is not None else parsed["count"]
		if failures is not None:
			g["failures_before"] = max(g.get("failures_before", 0), failures)
		for extra in ("uid", "shell", "group", "change"):
			if parsed.get(extra) is not None:
				g[extra] = parsed[extra]
		if parsed["user"] not in g["users"] and len(g["users"]) < 10:
			g["users"].append(parsed["user"])
		if len(g["samples"]) < MAX_SAMPLES:
			g["samples"].append(line.strip()[:1000])

	def _describe(self, kind, subject, g):
		severity, _ = _KINDS[kind]
		users = ", ".join(g["users"][:3])
		if kind == "ssh_root_login":
			return f"Root SSH login from {subject}", severity
		if kind == "ssh_login_after_failures":
			return f"SSH login as {users} from {subject} after {g['failures_before']} failed attempts", severity
		if kind == "sudo_failure":
			return f"{g['count']} failed sudo attempt(s) by {subject}", severity
		if kind == "account_created" and g.get("change") == "shell":
			return f"{subject} can now log in (shell {g.get('shell')})", severity
		if kind == "account_created" and g.get("change") == "uid":
			return f"{subject} given UID 0 (root)", "critical"
		if kind == "account_created":
			return f"New system account {subject}", severity
		if kind == "service_account_created":
			return f"New service account {subject} (no login shell)", severity
		if kind == "admin_group_change":
			return f"{subject} added to admin group {g.get('group')}", severity
		severity = "critical" if g["count"] >= CRITICAL_THRESHOLD else "warning"
		return f"{g['count']} failed SSH login(s) from {subject}", severity

	def drain(self, now=None):
		ts = utc_iso(now)
		events = []
		self._prune(self.clock())
		for (_, kind, subject), g in self.groups.items():
			title, severity = self._describe(kind, subject, g)
			payload = {
				"count": g["count"],
				"users": g["users"],
				"sample_lines": g["samples"],
				"log_file": self.log_file,
				"attack_techniques": [_KINDS[kind][1]],
			}
			if kind.startswith("ssh_"):
				payload["ip"] = subject
			for extra in ("failures_before", "uid", "shell", "group", "change"):
				if extra in g:
					payload[extra] = g[extra]
			events.append(
				event(
					"security",
					kind,
					severity,
					g["timestamp"] or ts,
					self.host,
					title,
					fingerprint(self.host, kind, subject),
					payload,
					source="sshd" if kind.startswith("ssh_") else "auth",
				)
			)
		self.groups = {}
		return [], events
