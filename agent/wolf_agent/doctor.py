"""`wolf-agent doctor`: what this host gives the agent, and what to fix. Read-only.

Every way the agent can collect less without saying so, checked from where it runs: the config and
the Wolf site, each bench's logs, Redis and nginx log, the Press job database or the Pilot export,
the auth log or journal, response actions, the daemon's own folders. Run it as the agent's user
(`sudo -u wolf-agent wolf-agent doctor`): root reads what the daemon cannot.

Each check is `{area, status, title, fix}`, status one of ok / warn / fail / info. A check that
raises is reported as failed, never stops the others. Nothing is written: no tail state, no spool,
no SQLite file (the Press job database is opened the way the daemon opens it).
"""

import grp
import json
import os
import pwd
import shutil
import stat
import subprocess
import time

from . import pilot, press
from .config import press_settings, resolve_auth_log, section
from .parsers.nginx import parse_line as parse_nginx_line
from .redis_queue import RedisClient
from .tailer import JournalTailer
from .watchdog import DEFAULT_STALE_MINUTES

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
AGENT_USER = "wolf-agent"
NGINX_SAMPLE_BYTES = 64 * 1024


def item(area, status, title, fix=None):
	return {"area": area, "status": status, "title": title, "fix": fix}


def run(cfg, config_path, live=True, collector_factory=None, euid=None):
	"""The checks for this host, in report order."""
	euid = os.geteuid() if euid is None else euid
	if collector_factory is None:
		from .collector import Collector

		def collector_factory(c):
			return Collector(c, state_path=None, sync_checks=True)

	# what the daemon works from: its log sources and, on Press, the benches it rediscovers
	seen = {"paths": [], "benches": list(cfg.get("benches") or []), "error": None}
	try:
		collector = collector_factory(cfg)
		try:
			seen["paths"] = sorted({s.tailer.path for s in collector.sources})
			seen["benches"] = list(collector.benches)
		finally:
			collector.close()
	except Exception as e:  # what the daemon itself would hit at start
		seen["error"] = f"{type(e).__name__}: {e}"
	out = []
	if seen["error"]:
		out.append(item("logs", FAIL, f"the collector cannot start: {seen['error']}",
		                "fix the config (benches, extra_logs) or run with -v for the traceback"))  # fmt: skip
	for area, fn in (
		("agent", lambda: _identity(cfg, config_path, euid)),
		("wolf site", lambda: _site(cfg, live)),
		("logs", lambda: _sources(seen["paths"])),
		("benches", lambda: _benches(cfg, seen["benches"])),
		("platform", lambda: _platform(cfg)),
		("host signals", lambda: _auth(cfg)),
		("response", lambda: _response(cfg)),
		("daemon", lambda: _daemon(cfg)),
	):
		try:
			out += fn()
		except Exception as e:  # a broken check is a finding, not a crash
			out.append(item(area, FAIL, f"check failed: {type(e).__name__}: {e}"))
	return out


def exit_code(checks):
	return 1 if any(c["status"] == FAIL for c in checks) else 0


def render(checks):
	marks = {OK: "  ok ", WARN: " WARN", FAIL: " FAIL", INFO: "  -- "}
	lines, area = [], None
	for c in checks:
		if c["area"] != area:
			area = c["area"]
			lines.append(f"\n{area}")
		lines.append(f"{marks[c['status']]}  {c['title']}")
		if c["fix"] and c["status"] in (WARN, FAIL):
			lines.append(f"        fix: {c['fix']}")
	counts = {s: sum(c["status"] == s for c in checks) for s in (FAIL, WARN, OK)}
	lines.append(f"\n{counts[FAIL]} failed, {counts[WARN]} warning(s), {counts[OK]} ok")
	return "\n".join(lines).lstrip("\n")


def presence(path):
	"""`ok`, `missing` or `denied`: os.path.exists says False for both of the last two, and a folder
	the agent cannot enter (a 0750 home) is not one that is gone."""
	try:
		os.stat(path)
	except FileNotFoundError:
		return "missing"
	except PermissionError:
		return "denied"
	except OSError:
		return "missing"
	return "ok" if os.access(path, os.R_OK) else "denied"


DENIED_FIX = f"give {AGENT_USER} access: add it to the group of the user who owns the folder (frappe...)"


def _redact(url):
	"""A Redis URL without its password, for the report."""
	if "@" not in url:
		return url
	scheme, _, rest = url.partition("://")
	return f"{scheme}://***@{rest.rpartition('@')[2]}"


def _agent_uid():
	try:
		return pwd.getpwnam(AGENT_USER).pw_uid
	except KeyError:
		return None


# --- the agent itself ---------------------------------------------------------------------------


def _identity(cfg, config_path, euid):
	out = []
	agent_uid = _agent_uid()
	if euid == 0 and agent_uid is not None:
		out.append(item("agent", WARN, "running as root: this reads what the daemon cannot",
		                f"sudo -u {AGENT_USER} wolf-agent --config {config_path} doctor"))  # fmt: skip
	elif agent_uid is not None and euid != agent_uid:
		out.append(item("agent", INFO, f"running as uid {euid}, not {AGENT_USER}: results may differ from the daemon's"))
	registered = cfg.get("url") and cfg.get("agent_id") and cfg.get("agent_secret")
	if registered:
		out.append(item("agent", OK, f"registered as {cfg['agent_id']} with {cfg['url']}, host {cfg.get('hostname')}"))
	else:
		out.append(item("agent", FAIL, "not registered", "sudo wolf-agent register --url https://<wolf-site> --token <token>"))
	try:
		st = os.stat(config_path)
	except OSError:
		return out
	if st.st_mode & 0o077:
		out.append(item("agent", WARN, f"{config_path} is mode {stat.S_IMODE(st.st_mode):o}: it holds the agent secret",
		                f"chmod 0600 {config_path}"))  # fmt: skip
	if agent_uid is not None and st.st_uid != agent_uid:
		out.append(item("agent", WARN, f"{config_path} is not owned by {AGENT_USER}: the daemon may not read it",
		                f"chown {AGENT_USER}: {config_path}"))  # fmt: skip
	return out


def _site(cfg, live):
	if not live:
		return [item("wolf site", INFO, "not contacted (--offline)")]
	if not (cfg.get("url") and cfg.get("agent_id") and cfg.get("agent_secret")):
		return []
	from .shipper import AuthError, RejectedError, Shipper, TransportError

	try:
		answer = Shipper(cfg).status()
	except AuthError as e:
		return [item("wolf site", FAIL, f"the Wolf site rejects this agent's credentials: {e}",
		             "register this host again (wolf-agent register ... --token <token>)")]  # fmt: skip
	except (RejectedError, TransportError) as e:
		return [item("wolf site", FAIL, f"cannot reach {cfg['url']}: {e}",
		             "check DNS, the firewall and verify_tls; the agent spools meanwhile")]  # fmt: skip
	out = [item("wolf site", OK, f"{cfg['url']} answers for {answer.get('agent') or cfg['agent_id']}")]
	health = answer.get("health")
	if isinstance(health, dict):
		from .watchdog import assess

		problems = assess(health)
		out.append(item("wolf site", WARN if problems else OK,
		                "Wolf's own health: " + ("; ".join(problems) if problems else "healthy"),
		                "open the Wolf site's System Health page" if problems else None))  # fmt: skip
	return out


# --- logs and benches ---------------------------------------------------------------------------


def _sources(paths):
	"""The log files the daemon would tail, from a collector built like `wolf-agent check` does."""
	out, missing = [], []
	for path in paths:
		if path.startswith("journal:"):
			continue  # checked with the host signals
		state = presence(path)
		if state == "missing":
			missing.append(path)
		elif state == "denied":
			out.append(item("logs", FAIL, f"cannot read {path} (permission denied, on it or a folder above)", DENIED_FIX))
	readable = len(paths) - len(missing) - len(out) - sum(p.startswith("journal:") for p in paths)
	out.insert(0, item("logs", OK if readable else WARN, f"{readable} log file(s) readable",
	                   None if readable else "no log is read: check the benches below"))  # fmt: skip
	if missing:
		shown = ", ".join(_short(p) for p in missing[:6]) + (" ..." if len(missing) > 6 else "")
		out.append(item("logs", INFO, f"{len(missing)} not written yet (read once they appear): {shown}"))
	return out


def _short(path):
	"""`<bench>/<file>` for a bench log, the file name otherwise."""
	parent = os.path.basename(os.path.dirname(path))
	if parent == "logs":
		return f"{os.path.basename(os.path.dirname(os.path.dirname(path)))}/{os.path.basename(path)}"
	return os.path.basename(path)


def _benches(cfg, benches):
	if not benches and press.is_proxy(press_settings(cfg)["agent_dir"]):
		return [item("benches", INFO, "a Press proxy server: no bench here, its access log names the sites")]
	if not benches:
		return [item("benches", WARN, "no bench in the config: only host metrics and the auth log are collected",
		             "sudo wolf-agent register ... --bench /path/to/bench, or wolf-agent discover")]  # fmt: skip
	out = []
	for bench in benches:
		name, path = bench.get("name"), bench.get("path") or ""
		state = presence(path)
		if state == "denied":
			out.append(item("benches", FAIL, f"{name}: cannot enter {path} (permission denied)", DENIED_FIX))
			continue
		if state == "missing" or not os.path.isdir(path):
			out.append(item("benches", FAIL, f"{name}: {path} is gone", "re-register, or remove the bench from the config"))
			continue
		out.append(item("benches", OK, f"{name}: {len(bench.get('sites') or [])} site(s), {bench.get('platform') or 'generic'}"))
		out += _site_configs(bench)
		if bench.get("redis_queue"):
			out.append(_redis(name, bench["redis_queue"]))
		for log in _as_list(bench.get("nginx_access_log")):
			out.append(_nginx(name, log))
	return out


def _as_list(value):
	return [value] if isinstance(value, str) else list(value or [])


def _site_configs(bench):
	unreadable = []
	for site in bench.get("sites") or []:
		path = os.path.join(bench["path"], "sites", site, "site_config.json")
		if os.path.exists(path) and not os.access(path, os.R_OK):
			unreadable.append(site)
	if not unreadable:
		return []
	# Press and Pilot keep them 0600 for the bench user on purpose: unknown, not broken
	known = bench.get("platform") in ("press", "pilot")
	return [item("benches", INFO if known else WARN,
	             f"{bench['name']}: {len(unreadable)} site config(s) unreadable: risky settings and MariaDB checks unknown",
	             None if known else f"add {AGENT_USER} to the bench user's group")]  # fmt: skip


def _redis(bench, url):
	try:
		with RedisClient(url, timeout=3) as r:
			pong = r.command("PING")
	except Exception as e:
		return item("benches", WARN, f"{bench}: queue Redis {_redact(url)} unreachable: {e}",
		            "start the bench's queue Redis, or check redis_queue in the config")  # fmt: skip
	if pong in ("PONG", b"PONG"):
		return item("benches", OK, f"{bench}: queue Redis {_redact(url)} answers")
	return item("benches", WARN, f"{bench}: queue Redis {_redact(url)} does not answer PING ({pong!r})",
	            "check redis_queue: the port may be another service")  # fmt: skip


def _nginx(bench, path):
	state = presence(path)
	if state == "denied":
		return item("benches", FAIL, f"{bench}: cannot read {path} (permission denied)", f"add {AGENT_USER} to the adm group")
	if state == "missing":
		return item("benches", INFO, f"{bench}: {path} not written yet")
	try:
		with open(path, "rb") as f:
			start = max(os.path.getsize(path) - NGINX_SAMPLE_BYTES, 0)
			f.seek(start)
			lines = f.read().decode("utf-8", "replace").splitlines()[1 if start else 0:]  # a cut first line
	except OSError as e:
		return item("benches", FAIL, f"{bench}: cannot read {path}: {e}", f"give {AGENT_USER} read access (group adm)")
	if not lines:
		return item("benches", INFO, f"{bench}: {path} is empty so far")
	parsed = [p for p in map(parse_nginx_line, lines[-200:]) if p]
	if not parsed:
		return item("benches", WARN, f"{bench}: no line of {os.path.basename(path)} is in a format Wolf reads",
		            "log with nginx's combined format, Press's main or Pilot's pilot_access (docs: agent/collected)")  # fmt: skip
	return item("benches", OK, f"{bench}: {os.path.basename(path)} parsed ({len(parsed)} of its last {len(lines[-200:])} lines)")


# --- Press and Pilot ----------------------------------------------------------------------------


def _platform(cfg):
	out = []
	press_cfg = press_settings(cfg)
	if cfg.get("platform") == "press" or press.detect(press_cfg["agent_dir"]):
		out += _press(cfg, press_cfg)
	for bench in cfg.get("benches") or []:
		if bench.get("platform") == "pilot":
			out += _pilot(bench)
	return out


def _press(cfg, press_cfg):
	out = []
	db = os.path.join(press_cfg["agent_dir"], press.JOBS_DB)
	try:
		conn = press.open_jobs_db(db)
	except press.JobsDBError as e:
		out.append(item("platform", WARN, f"Press: cannot read {db}: {e}",
		                f"add {AGENT_USER} to the frappe group; deployments fall back to bench changes on disk"))  # fmt: skip
	else:
		jobs = conn.execute("select count(*) from jobmodel").fetchone()[0]
		conn.close()
		out.append(item("platform", OK, f"Press: job history readable ({jobs} jobs): deployments, backups"))
	# -wal/-shm the Press agent cannot write stop every Press job (seen on dev/press)
	try:
		owner = os.stat(db).st_uid
		for suffix in ("-wal", "-shm"):
			if os.path.exists(db + suffix) and os.stat(db + suffix).st_uid != owner:
				out.append(item("platform", FAIL, f"Press: {db}{suffix} is not the Press agent's: its jobs fail to write",
				                f"stop the Press agent (supervisorctl stop 'agent:'), delete {db}-wal and -shm, start it"))  # fmt: skip
	except OSError:
		pass
	if press.is_proxy(press_cfg["agent_dir"]):
		logs = [e for e in cfg.get("extra_logs") or [] if e.get("site_from_host")]
		out.append(item("platform", OK if logs else FAIL, "Press proxy server: " + ("its access log is read" if logs else "its access log is not read"),
		                None if logs else "sudo wolf-agent --config <config> refresh"))  # fmt: skip
	elif press_cfg.get("proxy_ip") and cfg.get("platform") == "press":
		out.append(item("platform", INFO, f"Press: behind the proxy {press_cfg['proxy_ip']}: web clients are blocked there"))
	return out


def _pilot(bench):
	name = bench["name"]
	path = os.path.join(pilot.EXPORT_DIR, f"{name}.json")
	state = presence(path)
	if state == "missing":
		return [item("platform", WARN, f"Pilot {name}: no export ({path}): no tasks nor process states",
		             "re-run agent/install.sh as root (it installs wolf-pilot-export)")]  # fmt: skip
	if state == "denied":
		return [item("platform", FAIL, f"Pilot {name}: cannot read {path}",
		             f"systemctl restart wolf-pilot-export.service (it sets the {AGENT_USER} group)")]  # fmt: skip
	data = pilot.read_export(name, path=bench.get("path"))
	if data is None:
		return [item("platform", WARN, f"Pilot {name}: the export is older than 5 minutes or about another folder",
		             "systemctl status wolf-pilot-export.timer")]  # fmt: skip
	return [item("platform", OK, f"Pilot {name}: export fresh ({len(data.get('tasks') or [])} tasks, "
	             f"{len(data.get('units') or [])} units)")]  # fmt: skip


# --- host signals, response, daemon ---------------------------------------------------------------


def _auth(cfg):
	where = resolve_auth_log(cfg.get("auth_log"), JournalTailer.available())
	if where is None:
		return [item("host signals", WARN, "no auth log and no journal: no SSH, sudo or account events",
		             "install journalctl, or set auth_log to the file sshd logs to")]  # fmt: skip
	if where != "journal":
		state = presence(where)
		if state == "missing":
			return [item("host signals", FAIL, f"auth log {where} does not exist", "set auth_log to the file sshd logs to, or null")]
		ok = state == "ok"
		return [item("host signals", OK if ok else FAIL, f"auth log {where}" + (" readable" if ok else " unreadable"),
		             None if ok else f"add {AGENT_USER} to the adm group")]  # fmt: skip
	if not _journal_groups():
		return [item("host signals", FAIL, "journal: this user is in none of the groups that read the system journal",
		             f"add {AGENT_USER} to the systemd-journal group")]  # fmt: skip
	try:
		# no -q: journalctl's hint that it is "not seeing messages from other users" goes to stderr
		done = subprocess.run(["journalctl", "-n", "1", "--no-pager", "-t", "sshd", "-t", "sshd-session"],
		                      capture_output=True, text=True, timeout=10)  # fmt: skip
	except (OSError, subprocess.SubprocessError) as e:
		return [item("host signals", FAIL, f"journalctl: {e}")]
	text = (done.stdout + done.stderr).lower()
	if "not seeing messages" in text or "insufficient permissions" in text or "no journal files" in text:
		return [item("host signals", FAIL, "journal: this user cannot read the system journal",
		             f"add {AGENT_USER} to the systemd-journal group")]  # fmt: skip
	return [item("host signals", OK, "journal readable (sshd, sudo, account changes)")]


def _journal_groups():
	"""Root, or a member of a group that reads the system journal."""
	if os.geteuid() == 0:
		return True
	names = set()
	for gid in os.getgroups():
		try:
			names.add(grp.getgrgid(gid).gr_name)
		except KeyError:
			continue
	return bool(names & {"systemd-journal", "adm", "wheel"})


def _response(cfg):
	resp = section(cfg, "response")
	if not resp.get("enabled"):
		return [item("response", INFO, "response actions off: approved blocks come back Failed (response.enabled)")]
	command = list(resp.get("command") or [])
	helper = next((p for p in command if p.startswith("/")), None)
	out = []
	if helper and not os.path.exists(helper):
		script = "wolf-block-fail2ban.sh" if "fail2ban" in helper else "wolf-block.sh"
		return [item("response", FAIL, f"response actions on, but {helper} is not installed",
		             f"install -m 0755 -o root -g root agent/{script} {helper} (docs: agent/response-actions)")]  # fmt: skip
	if command[:1] == ["sudo"] and helper:
		try:
			done = subprocess.run(["sudo", "-n", "-l", helper], capture_output=True, text=True, timeout=10)
			allowed = done.returncode == 0
		except (OSError, subprocess.SubprocessError):
			allowed = False
		out.append(item("response", OK if allowed else FAIL, f"sudo {'allows' if allowed else 'refuses'} {helper}",
		                None if allowed else f"echo '{AGENT_USER} ALL=(root) NOPASSWD: {helper}' > /etc/sudoers.d/wolf-block"))  # fmt: skip
	firewall = "fail2ban-client" if helper and "fail2ban" in helper else "nft"
	if not shutil.which(firewall) and not os.path.exists(f"/usr/sbin/{firewall}"):
		out.append(item("response", FAIL, f"{firewall} is not installed: blocks cannot apply", f"install {firewall}"))
	elif not out or out[-1]["status"] == OK:
		out.append(item("response", OK, f"blocks go through {firewall}"))
	return out


def _daemon(cfg):
	out = []
	spool = cfg.get("spool_dir")
	if spool:
		ok = os.path.isdir(spool) and os.access(spool, os.W_OK)
		out.append(item("daemon", OK if ok else FAIL, f"spool {spool} " + ("writable" if ok else "not writable"),
		                None if ok else f"install -d -o {AGENT_USER} -g {AGENT_USER} -m 0750 {spool}"))  # fmt: skip
	if _systemd():
		try:
			shown = subprocess.run(["systemctl", "show", "-p", "LoadState", "-p", "ActiveState", "wolf-agent.service"],
			                       capture_output=True, text=True, timeout=10).stdout  # fmt: skip
			props = dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)
		except (OSError, subprocess.SubprocessError):
			props = {}
		state = props.get("ActiveState") or "unknown"
		if props.get("LoadState") == "not-found":
			out.append(item("daemon", INFO, "no wolf-agent.service on this host: the agent is run some other way"))
		else:
			out.append(item("daemon", OK if state == "active" else FAIL, f"wolf-agent.service {state}",
			                None if state == "active" else "systemctl enable --now wolf-agent; journalctl -u wolf-agent"))  # fmt: skip
	if spool:
		stale = float(section(cfg, "watchdog").get("stale_minutes") or DEFAULT_STALE_MINUTES)
		out += _last_push(os.path.join(spool, "watchdog-state.json"), stale)
	return out


def _systemd():
	return bool(shutil.which("systemctl")) and os.path.isdir("/run/systemd/system")


def _last_push(path, stale=DEFAULT_STALE_MINUTES):
	try:
		with open(path) as f:
			state = json.load(f)
	except (OSError, ValueError):
		return []
	last = state.get("last_push_ok")
	if not isinstance(last, (int, float)):
		return []
	minutes = (time.time() - last) / 60
	return [item("daemon", OK if minutes < stale else WARN, f"last successful push {minutes:.0f} min ago",
	             None if minutes < stale else "journalctl -u wolf-agent: the Wolf site or the network")]  # fmt: skip

