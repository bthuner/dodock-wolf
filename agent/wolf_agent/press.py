"""Frappe Press (Frappe Cloud) server support: bench discovery and deploy correlation.

Everything here reads what the Press server agent (github.com/frappe/agent)
leaves on disk; no Press credentials are needed. See docs/press.md for the
source files and lines each assumption comes from.

Layout, as set up by the Press agent:

- `/home/frappe/agent/config.json` holds `benches_directory` (default
  `/home/frappe/benches`) and `nginx_directory`.
- Each bench is `<benches_directory>/<bench-name>/` with `config.json` (bench
  config: `docker_image`, `web_port`, `rq_port`, ...), `sites/`, `logs/` and
  `config/`; the apps live inside the bench's Docker image, not on the host.
- The agent's job history is the SQLite database `jobs.sqlite3` in the agent
  directory (peewee tables `jobmodel` and `stepmodel`).

File modes, as checked on a server set up by Press's roles (dev/press): the Press agent writes
its config.json, each bench's config.json and every site_config.json mode 0600, so the Wolf
agent (its own user, in the `frappe` group) reads them only at registration, which runs as root.
At run time it relies on what the group can read: jobs.sqlite3, the bench logs, the bench's
docker-compose.yml (its image) and nginx.conf (its web port, sites and custom domains).
"""

import contextlib
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .util import event, fingerprint, utc_iso

log = logging.getLogger(__name__)

DEFAULT_AGENT_DIR = "/home/frappe/agent"
DEFAULT_BENCHES_DIR = "/home/frappe/benches"
DEFAULT_NGINX_ACCESS_LOG = "/var/log/nginx/access.log"
JOBS_DB = "jobs.sqlite3"

# Press agent job name → (category, positional parameter names of the job function).
# Parameter names come from the @job-decorated methods in frappe/agent
# (agent/server.py, agent/bench.py, agent/site.py). `name` is the site (or the
# bench for New Bench), `target` / `bench` the bench the site ends up on.
DEPLOY_JOBS = {
	"New Bench": ("new_bench", ("bench",)),
	"Update Site Pull": ("update", ("site", "source", "bench")),
	"Update Site Migrate": ("migrate", ("site", "source", "bench")),
	"Recover Failed Site Migrate": ("recover", ("site", "source", "bench")),
	"Recover Failed Site Pull": ("recover", ("site", "source", "bench")),
	"Recover Failed Site Update": ("recover", ("site", "bench")),
	"Move Site to Bench": ("update", ("site", "source", "bench")),
	"Update Bench In Place": ("update", ("sites",)),
	"Patch App": ("patch", ()),
	"Migrate Site": ("migrate", ()),
	"Install App on Site": ("app_install", ()),
	"Uninstall App on Site": ("app_uninstall", ()),
	"Bench Restart": ("restart", ()),
	"Rebuild Bench Assets": ("rebuild", ()),
}
TERMINAL = ("Success", "Failure")
# Press takes every backup through its agent (Site.backup_job), offsite ones deleted from the server
# after the upload or streamed without a local copy: the job history, not the backups folder, says
# when a site was last backed up
BACKUP_JOB = "Backup Site"
_BACKUP_PATH_RE = re.compile(r"/benches/(?P<bench>[^/\"]+)/sites/(?P<site>[^/\"]+)/private/backups/")
# a streamed backup's result has S3 keys for paths, and the site only in its url
_BACKUP_URL_RE = re.compile(r"\"url\":\s*\"https?://(?P<site>[^/\"]+)/backups/")
MAX_BACKUP_JOBS = 200000  # rows read back for the newest backup of each site, at most


def _backup_site(text):
	"""(bench or None, site) named by a Backup Site job's result, or None."""
	m = _BACKUP_PATH_RE.search(text or "")
	if m:
		return m.group("bench"), m.group("site")
	m = _BACKUP_URL_RE.search(text or "")
	return (None, m.group("site")) if m else None
# A job whose bench cannot be read yet (Bench/Site methods carry no bench name in
# their arguments) waits this long for its steps to name it, then ships host-scoped.
SCOPE_WAIT = timedelta(minutes=2)
MAX_JOBS_PER_POLL = 500
# Jobs stuck Pending/Running longer than this are given up on.
STALE_AFTER = timedelta(hours=24)

_SITE_FLAG_RE = re.compile(r"--site\s+([A-Za-z0-9._-]+)")


def read_agent_config(agent_dir=DEFAULT_AGENT_DIR):
	"""The Press agent's config.json, or None when this is not a Press server."""
	try:
		with open(os.path.join(agent_dir, "config.json")) as f:
			cfg = json.load(f)
	except (OSError, ValueError):
		return None
	if not isinstance(cfg, dict) or not cfg.get("benches_directory"):
		return None
	return cfg


def detect(agent_dir=DEFAULT_AGENT_DIR):
	"""A Press server: the agent's config is readable (root), or it and the job database are there
	(the Wolf agent's user cannot read the 0600 config.json, but can see that it exists)."""
	if read_agent_config(agent_dir) is not None:
		return True
	return os.path.isfile(os.path.join(agent_dir, "config.json")) and os.path.isfile(os.path.join(agent_dir, JOBS_DB))


def is_proxy(agent_dir=DEFAULT_AGENT_DIR):
	"""A Press proxy server: Press's proxy role creates the agent's nginx/proxy.conf (0664, readable)."""
	return os.path.isfile(os.path.join(agent_dir, "nginx", "proxy.conf"))


def proxy_hosts(agent_dir=DEFAULT_AGENT_DIR):
	"""On a Press proxy: domain → site, from each `nginx/hosts/<host>/map.json` (Add Host to Proxy)."""
	root = os.path.join(agent_dir, "nginx", "hosts")
	try:
		names = os.listdir(root)
	except OSError:
		return {}
	aliases = {}
	for name in names:
		if name.startswith("*"):
			continue  # a wildcard: its sites are under it by name
		for host, target in _load_json(os.path.join(root, name, "map.json")).items():
			if isinstance(target, str) and target and target != host and "." in target:
				aliases[host] = target
	return aliases


def benches_directory(agent_dir=DEFAULT_AGENT_DIR, default=None):
	"""From the agent's config, else `default` (what registration read as root), else Press's own."""
	cfg = read_agent_config(agent_dir) or {}
	return cfg.get("benches_directory") or default or DEFAULT_BENCHES_DIR


def _load_json(path):
	try:
		with open(path) as f:
			data = json.load(f)
		return data if isinstance(data, dict) else {}
	except (OSError, ValueError):
		return {}


def _read_text(path, limit=1024 * 1024):
	try:
		with open(path, errors="replace") as f:
			return f.read(limit)
	except OSError:
		return ""


def is_press_bench(path):
	"""Press bench: `sites/` (no apps/ on the host) and `config.json` with a `docker_image`, or, when
	that config is not readable (mode 0600), `config.json` next to the agent's docker-compose.yml."""
	if not os.path.isdir(os.path.join(path, "sites")):
		return False
	if _load_json(os.path.join(path, "config.json")).get("docker_image"):
		return True
	return os.path.isfile(os.path.join(path, "config.json")) and bool(_compose_image(path))


_IMAGE_RE = re.compile(r"^\s+image:\s*['\"]?([^\s'\"]+)", re.M)
_WEB_UPSTREAM_RE = re.compile(r"upstream\s+\S+-web-server\s*\{\s*server\s+127\.0\.0\.1:(\d+)")
_DOMAIN_MAP_RE = re.compile(r"map\s+\$host\s+\$site_name_\w+\s*\{([^}]*)\}")


def _compose_image(path):
	"""The bench image, from the docker-compose.yml the agent renders at bench init (mode 0644)."""
	images = _IMAGE_RE.findall(_read_text(os.path.join(path, "docker-compose.yml")))
	return next((i for i in images if not i.startswith("redis:")), None)


def _nginx_web_port(path):
	"""The bench's web port, from the nginx.conf the agent renders for it (mode 0644)."""
	m = _WEB_UPSTREAM_RE.search(_read_text(os.path.join(path, "nginx.conf")))
	return int(m.group(1)) if m else None


def _nginx_domains(path):
	"""Custom domain → site, from the bench nginx.conf `map $host $site_name_<bench>` block."""
	m = _DOMAIN_MAP_RE.search(_read_text(os.path.join(path, "nginx.conf")))
	aliases = {}
	for line in (m.group(1) if m else "").splitlines():
		parts = line.strip().rstrip(";").split()
		if len(parts) == 2 and parts[0] != "default" and parts[0] != parts[1]:
			aliases[parts[0]] = parts[1]
	return aliases


def _rq_port(bench_config, path):
	"""`rq_port` from the bench config; unreadable, from the web port: Press gives a bench one
	offset for all its ports (web 18000 + offset, rq 11000 + offset, press Bench doctype)."""
	rq_port = bench_config.get("rq_port")
	if str(rq_port or "").isdigit():
		return int(rq_port)
	if bench_config:
		return None  # a readable config without rq_port: an older bench whose Redis is not published
	web_port = _nginx_web_port(path)
	if web_port and 18000 <= web_port < 19000:
		return 11000 + web_port - 18000
	return None


def _sites(path):
	sites_dir = os.path.join(path, "sites")
	try:
		names = sorted(os.listdir(sites_dir))
	except OSError:
		return []
	return [n for n in names if os.path.isfile(os.path.join(sites_dir, n, "site_config.json"))]


def _site_domains(path, sites):
	"""Custom domains → site, from each site_config.json `domains` (what the bench nginx maps)."""
	aliases = {}
	for site in sites:
		domains = _load_json(os.path.join(path, "sites", site, "site_config.json")).get("domains") or []
		if isinstance(domains, str):
			domains = [domains]
		for domain in domains:
			if isinstance(domain, dict):
				domain = domain.get("domain") or domain.get("name")
			if isinstance(domain, str) and domain and domain != site:
				aliases[domain] = site
	return aliases


def describe_press_bench(path, nginx_access_log=DEFAULT_NGINX_ACCESS_LOG):
	# resolved: after Run Benches on Shared FS the same bench is also /home/frappe/shared/<bench> (a
	# link); one path keeps its logs' read positions, which are keyed by path, across the switch
	path = os.path.realpath(path)
	bench_config = _load_json(os.path.join(path, "config.json"))
	sites = _sites(path)
	rq_port = _rq_port(bench_config, path)
	nginx = nginx_access_log if nginx_access_log and os.path.exists(nginx_access_log) else None
	return {
		"name": os.path.basename(path),
		"path": path,
		"sites": sites,
		"logs_dir": os.path.join(path, "logs"),
		"nginx_access_log": nginx,
		# rq_port is published on the host (docker run -p 0.0.0.0:<rq_port>:11000);
		# common_site_config's redis_queue is the in-container address.
		"redis_queue": f"redis://127.0.0.1:{rq_port}" if rq_port else None,
		# site configs are 0600: the bench nginx.conf maps the same domains
		"site_domains": {**_nginx_domains(path), **_site_domains(path, sites)},
		"platform": "press",
		"docker_image": bench_config.get("docker_image") or _compose_image(path),
		# read from the bench's config.json (root, at registration), or around it (the daemon)
		"config_read": bool(bench_config),
		"bench_toml": False,
	}


def keep_registered(found, known):
	"""Benches the daemon found around their 0600 config keep what root read in it at registration:
	`rq_port` (an older bench has none, and its Redis is not published) and the image (the
	compose file keeps the one the bench was created with)."""
	read = {b["name"]: b for b in known or () if b.get("config_read")}
	for bench in found:
		old = read.get(bench["name"])
		if old and not bench.get("config_read") and old.get("path") == bench.get("path"):
			bench.update(redis_queue=old.get("redis_queue"), docker_image=old.get("docker_image"), config_read=True)
	return found


def discover_press_benches(agent_dir=DEFAULT_AGENT_DIR, nginx_access_log=DEFAULT_NGINX_ACCESS_LOG, benches_dir=None):
	root = benches_directory(agent_dir, default=benches_dir)
	try:
		names = sorted(os.listdir(root))
	except FileNotFoundError:
		# a proxy or database server has no benches folder: nothing to say at every rediscovery
		log.debug("no Press benches directory %s", root)
		return []
	except OSError as e:
		log.warning("cannot list Press benches directory %s: %s", root, e)
		return []
	benches = []
	for name in names:
		path = os.path.join(root, name)
		if os.path.isdir(path) and is_press_bench(path):
			benches.append(describe_press_bench(path, nginx_access_log=nginx_access_log))
	return benches


def _parse_dt(value):
	"""Peewee stores naive `datetime.now()` (server local time) as text."""
	if not value:
		return None
	if isinstance(value, datetime):
		return value
	text = str(value).strip().replace("T", " ")
	for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			continue
	return None


def _json(text):
	try:
		return json.loads(text) if text else None
	except (TypeError, ValueError):
		return None


def _backup_scope(row, steps, bench_in):
	"""(bench, site) of a Backup Site job: its result lists the files, under
	`<benches>/<bench>/sites/<site>/private/backups/`; a failed one, from its steps."""
	for text in [row.get("data") or ""] + [s.get("data") or "" for s in steps]:
		found = _backup_site(text)
		if found and found[0]:
			return found
	site = next((m.group(1) for s in steps for m in [_SITE_FLAG_RE.search(s.get("data") or "")] if m), None)
	bench = next((b for b in map(bench_in, [s.get("data") or "" for s in reversed(steps)]) if b), None)
	return bench, site


def last_backups(agent_dir=DEFAULT_AGENT_DIR, sites=None, limit=MAX_BACKUP_JOBS):
	"""{site: end} of each site's newest successful Backup Site job (naive server local time), or
	None when jobs.sqlite3 cannot be read. Reads back from the newest job until every one of `sites`
	is found (a site whose backups stopped long ago still gets its age), `limit` rows at most."""
	try:
		conn = open_jobs_db(os.path.join(agent_dir, JOBS_DB))
	except JobsDBError:
		return None
	wanted = set(sites) if sites is not None else None
	newest = {}
	try:
		cur = conn.execute(
			"select data, end from jobmodel where name = ? and status = 'Success' order by id desc limit ?", [BACKUP_JOB, limit]
		)
		for data, end in cur:
			found, end = _backup_site(data), _parse_dt(end)
			if found and end and found[1] not in newest:
				newest[found[1]] = end
				if wanted is not None and wanted <= set(newest):
					break
	except sqlite3.Error:
		return None
	finally:
		conn.close()
	return newest


class JobsDBError(Exception):
	pass


def open_jobs_db(path):
	"""Open the Press agent's jobs.sqlite3 strictly read-only, creating no file.

	The database runs in WAL mode. A reader opening it creates its -wal and -shm files when they are
	missing (after the Press agent's last connection closed, a restart), and the agent's folder is
	writable by the frappe group: they would be ours, mode 0644, and the Press agent could no longer
	write its own database (seen on dev/press after `sudo -u wolf-agent wolf-agent check`; the daemon's
	unit has ProtectHome=read-only). So `mode=ro` only while both files are there; without them no
	writer is open and the file holds every write: `immutable=1`, which creates nothing.
	"""
	if not os.path.exists(path):
		raise JobsDBError(f"{path} does not exist")
	errors = []
	with_wal = os.path.exists(path + "-wal") and os.path.exists(path + "-shm")
	for params in ("mode=ro", "mode=ro&immutable=1") if with_wal else ("mode=ro&immutable=1",):
		try:
			conn = sqlite3.connect(f"file:{path}?{params}", uri=True, timeout=5)
			conn.execute("select 1 from jobmodel limit 1").fetchall()
		except sqlite3.Error as e:
			errors.append(f"{params}: {e}")
			continue
		if "immutable" not in params and _created_wal(path):
			# the Press agent's last connection closed between the check and the connect: the files
			# are ours, which the Press agent could not write; take them back and read the file alone
			conn.close()
			for suffix in ("-wal", "-shm"):
				with contextlib.suppress(OSError):
					os.unlink(path + suffix)
			errors.append("mode=ro: created the -wal/-shm files, removed")
			continue
		return conn
	raise JobsDBError("; ".join(errors))


def _created_wal(path):
	"""True when the -shm file is ours but the database is not (we, not the Press agent, made it)."""
	try:
		return os.stat(path + "-shm").st_uid == os.geteuid() != os.stat(path).st_uid
	except OSError:
		return False


class PressJobWatcher:
	"""Turns Press agent jobs (deploys, updates, migrations) into Wolf events.

	One `deployment` event per job when it starts (timestamp = job start), and
	one `error` event if it ends in Failure. Emitted job ids are persisted in
	`state_path` so restarts never emit twice; on first run only jobs that are
	still pending/running are picked up (no history backfill).
	"""

	def __init__(self, host, agent_dir=DEFAULT_AGENT_DIR, state_path=None, known_benches=None, benches_dir=None):
		self.host = host
		self.agent_dir = agent_dir
		self.db_path = os.path.join(agent_dir, JOBS_DB)
		self.state_path = state_path
		self.known_benches = known_benches or (lambda: set())
		# resolved: on shared FS the Press agent works in /home/frappe/shared, a link to the benches
		# folder registration saw (Press's link_benches_to_nfs role)
		self.benches_dir = os.path.realpath(benches_dir or DEFAULT_BENCHES_DIR)
		self.state = self._load_state()
		self._warned = False

	def _load_state(self):
		state = {"floor": None, "started": [], "finished": [], "backup_since": None}
		if self.state_path:
			try:
				with open(self.state_path) as f:
					state.update(json.load(f))
			except (OSError, ValueError):
				pass
		return state

	def _save_state(self):
		if not self.state_path:
			return
		tmp = self.state_path + ".tmp"
		try:
			os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
			with open(tmp, "w") as f:
				json.dump(self.state, f)
			os.replace(tmp, self.state_path)
		except OSError as e:
			log.warning("cannot save Press job state %s: %s", self.state_path, e)

	def _rows(self, conn, floor):
		names = list(DEPLOY_JOBS)
		marks = ",".join("?" * len(names))
		cur = conn.execute(
			f"select id, name, status, agent_job_id, data, enqueue, start, end from jobmodel "
			f"where id > ? and name in ({marks}) order by id limit {MAX_JOBS_PER_POLL}",
			[floor, *names],
		)
		cols = [c[0] for c in cur.description]
		return [dict(zip(cols, row)) for row in cur.fetchall()]  # noqa: B905 (Python 3.9: no strict=)

	def _steps(self, conn, job_id):
		try:
			cur = conn.execute("select name, status, data from stepmodel where job_id = ? order by id", [job_id])
		except sqlite3.Error:
			return []
		return [{"name": n, "status": s, "data": d} for n, s, d in cur.fetchall()]

	def _scope(self, row, steps):
		"""(bench, sites) for a job, from its arguments, then from its steps' commands."""
		_, params = DEPLOY_JOBS[row["name"]]
		bench, sites = None, []
		data = _json(row.get("data"))
		if isinstance(data, dict) and "function" in data:
			args = data.get("args") or []
			kwargs = data.get("kwargs") or {}
			values = dict(zip(params, args))  # noqa: B905 (fewer args than params is expected)
			# keyword names in frappe/agent: name/target/bench/sites
			for key, role in (("name", params[0] if params else None), ("target", "bench"), ("bench", "bench"), ("sites", "sites")):
				if role and key in kwargs and role not in values:
					values[role] = kwargs[key]
			bench = values.get("bench") if isinstance(values.get("bench"), str) else None
			if isinstance(values.get("site"), str):
				sites.append(values["site"])
			if isinstance(values.get("sites"), list):
				sites += [s for s in values["sites"] if isinstance(s, str)]

		# A finished job's data is its result, its arguments gone (agent/job.py): the bench is then
		# the one its last step worked in, which for a site move is the target (checked on dev/press:
		# Update Site Migrate enables maintenance on the source, migrates on the target).
		texts = [s.get("data") or "" for s in reversed(steps)] + [row.get("data") or ""]
		if not bench:
			bench = next((b for b in map(self._bench_in, texts) if b), None)
		if not sites:
			for text in texts:
				for site in _SITE_FLAG_RE.findall(text):
					if site not in sites:
						sites.append(site)
		return bench, sites

	def _bench_in(self, text):
		"""The bench a step ran in: its `directory` under the benches folder (a bench Wolf has not
		rediscovered yet, e.g. New Bench's), else a known bench named in it."""
		data = _json(text)
		directory = data.get("directory") if isinstance(data, dict) else None
		if isinstance(directory, str) and os.path.realpath(os.path.dirname(os.path.normpath(directory))) == self.benches_dir:
			return os.path.basename(os.path.normpath(directory))
		return next((b for b in sorted(self.known_benches(), key=len, reverse=True) if b in text), None)

	def _deployment_event(self, row, bench, sites, start):
		category, _ = DEPLOY_JOBS[row["name"]]
		site = sites[0] if len(sites) == 1 else None
		target = site or bench or self.host
		return event(
			"deployment",
			"press",
			"info",
			utc_iso(start),
			self.host,
			f"Press: {row['name']} on {target}"[:140],
			fingerprint("press_job", self.host, row["id"]),
			{
				"note": row["name"],
				"source": "press",
				"press_job": row["name"],
				"press_category": category,
				"agent_job_id": row.get("agent_job_id"),
				"local_job_id": row["id"],
				"sites": sites,
			},
			source="press-agent",
			bench=bench,
			site=site,
		)

	def _backup_failed_event(self, row, bench, site, end, steps):
		data = _json(row.get("data"))
		tb = data.get("traceback") if isinstance(data, dict) else None
		failed = [s["name"] for s in steps if s.get("status") == "Failure"]
		return event(
			"error",
			"backup_failed",
			"critical",
			utc_iso(end),
			self.host,
			f"Press backup failed on {site or bench or self.host}"[:140],
			fingerprint("press_backup_failed", self.host, row["id"]),
			{
				"press_job": row["name"],
				"agent_job_id": row.get("agent_job_id"),
				"local_job_id": row["id"],
				"failed_steps": failed,
				"traceback": (tb or "")[-4000:] or None,
			},
			source="press-agent",
			bench=bench,
			site=site,
		)

	def _failure_event(self, row, bench, sites, end, steps):
		site = sites[0] if len(sites) == 1 else None
		failed = [s["name"] for s in steps if s.get("status") == "Failure"]
		data = _json(row.get("data"))
		tb = data.get("traceback") if isinstance(data, dict) else None
		output = data.get("output") if isinstance(data, dict) else None
		return event(
			"error",
			"press_job_failed",
			"warning",
			utc_iso(end),
			self.host,
			f"Press job failed: {row['name']}" + (f" ({failed[-1]})" if failed else ""),
			fingerprint("press_job_failed", self.host, row["id"]),
			{
				"press_job": row["name"],
				"agent_job_id": row.get("agent_job_id"),
				"local_job_id": row["id"],
				"failed_steps": failed,
				"sites": sites,
				"traceback": (tb or "")[-4000:] or None,
				"output": (str(output) if output else "")[-2000:] or None,
			},
			source="press-agent",
			bench=bench,
			site=site,
		)

	def poll(self, now=None):
		"""Events since the last poll, or None when jobs.sqlite3 cannot be read."""
		now = now or datetime.now(timezone.utc)
		try:
			conn = open_jobs_db(self.db_path)
		except JobsDBError as e:
			if not self._warned:
				log.warning("cannot read Press agent jobs (%s); falling back to bench/site changes on disk", e)
				self._warned = True
			return None
		try:
			return self._poll(conn, now)
		except sqlite3.Error as e:
			log.warning("reading %s: %s", self.db_path, e)
			return []
		finally:
			conn.close()

	def _poll(self, conn, now):
		floor = self.state.get("floor")
		started, finished = set(self.state["started"]), set(self.state["finished"])
		if floor is None:
			floor = self._baseline(conn, started, finished)
		rows = self._rows(conn, floor)

		events, pending = [], []
		local_now = now.astimezone().replace(tzinfo=None)
		for row in rows:
			jid = row["id"]
			if jid in finished:
				continue
			terminal = row["status"] in TERMINAL
			start = _parse_dt(row.get("start")) or (_parse_dt(row.get("enqueue")) if terminal else None)
			if not terminal:
				seen_at = start or _parse_dt(row.get("enqueue"))
				if seen_at and local_now - seen_at > STALE_AFTER:
					# left Pending/Running by a crashed worker: stop waiting for it
					finished.add(jid)
					continue
			steps = self._steps(conn, jid)
			bench, sites = self._scope(row, steps)
			if jid not in started and start:
				if bench or terminal or local_now - start >= SCOPE_WAIT:
					events.append(self._deployment_event(row, bench, sites, start))
					started.add(jid)
			if terminal and jid in started:
				if row["status"] == "Failure":
					end = _parse_dt(row.get("end")) or start
					events.append(self._failure_event(row, bench, sites, end, steps))
				finished.add(jid)
			else:
				pending.append(jid)

		if pending:
			floor = min(pending) - 1
		elif rows:
			floor = rows[-1]["id"]
		self.state["floor"] = floor
		self.state["started"] = sorted(j for j in started if j > floor)
		self.state["finished"] = sorted(j for j in finished if j > floor)
		events += self._backup_failures(conn)
		self._save_state()
		return events

	def _backup_failures(self, conn):
		"""`backup_failed` for each Backup Site job that failed since the last poll.

		Apart from the deployment jobs and their floor: Press queues a backup of every site at once,
		which must not hold deployments back, and the first poll (an install, an upgrade) starts at
		the newest backup that ended, so no old failure is replayed. Ordered by `end`, which a job
		gets when it ends (same peewee text format, so it compares as text)."""
		since = self.state.get("backup_since")
		if since is None:
			row = conn.execute("select max(end) from jobmodel where name = ?", [BACKUP_JOB]).fetchone()
			self.state["backup_since"] = (row[0] if row else None) or ""
			return []
		rows = conn.execute(
			"select id, name, status, agent_job_id, data, start, end from jobmodel where name = ? and status = 'Failure' "
			f"and end > ? order by end limit {MAX_JOBS_PER_POLL}",
			[BACKUP_JOB, since],
		)
		cols = [c[0] for c in rows.description]
		events = []
		for row in (dict(zip(cols, r)) for r in rows.fetchall()):  # noqa: B905 (Python 3.9: no strict=)
			steps = self._steps(conn, row["id"])
			bench, site = _backup_scope(row, steps, self._bench_in)
			end = _parse_dt(row["end"]) or _parse_dt(row["start"])
			events.append(self._backup_failed_event(row, bench, site, end, steps))
			self.state["backup_since"] = max(self.state["backup_since"], str(row["end"]))
		return events

	def _baseline(self, conn, started, finished):
		"""First run: skip history. Returns the floor; old finished jobs above it are marked done."""
		row = conn.execute("select max(id) from jobmodel").fetchone()
		max_id = row[0] if row and row[0] is not None else 0
		names = list(DEPLOY_JOBS)
		marks = ",".join("?" * len(names))
		open_ids = [
			r[0]
			for r in conn.execute(
				f"select id from jobmodel where name in ({marks}) and status not in ('Success', 'Failure')",
				names,
			).fetchall()
		]
		if not open_ids:
			return max_id
		floor = min(open_ids) - 1
		for (jid,) in conn.execute(
			f"select id from jobmodel where id > ? and name in ({marks}) and status in ('Success', 'Failure')",
			[floor, *names],
		).fetchall():
			finished.add(jid)
		return floor


class PressBenchWatcher:
	"""Fallback when jobs.sqlite3 is unreadable: deployments from the filesystem.

	A Press deploy creates a new bench directory and moves sites into it
	(Server.move_site in frappe/agent), so a new bench or a site that changed
	bench is reported as a `deployment`. Snapshot persisted in `state_path`.
	"""

	def __init__(self, host, state_path=None):
		self.host = host
		self.state_path = state_path
		self.snapshot = None
		if state_path:
			try:
				with open(state_path) as f:
					self.snapshot = json.load(f)
			except (OSError, ValueError):
				self.snapshot = None

	def poll(self, benches, now=None):
		ts = utc_iso(now)
		current = {"benches": sorted(b["name"] for b in benches), "sites": {}}
		for b in benches:
			for site in b.get("sites") or []:
				current["sites"][site] = b["name"]
		events = []
		if self.snapshot is not None:
			old_benches = set(self.snapshot.get("benches") or [])
			old_sites = self.snapshot.get("sites") or {}
			for name in current["benches"]:
				if name not in old_benches:
					events.append(self._event(ts, f"Press: new bench {name}", name, None, {"press_job": "New Bench"}))
			for site, bench in sorted(current["sites"].items()):
				before = old_sites.get(site)
				if before and before != bench:
					events.append(
						self._event(ts, f"Press: {site} moved to {bench}", bench, site, {"from_bench": before})
					)
		if current != self.snapshot:
			self.snapshot = current
			self._save()
		return events

	def _event(self, ts, title, bench, site, payload):
		payload = dict(payload, source="press", detected_by="filesystem")
		return event(
			"deployment",
			"press",
			"info",
			ts,
			self.host,
			title[:140],
			fingerprint("press_fs", self.host, bench, site, ts),
			payload,
			source="press-agent",
			bench=bench,
			site=site,
		)

	def _save(self):
		if not self.state_path:
			return
		tmp = self.state_path + ".tmp"
		try:
			os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
			with open(tmp, "w") as f:
				json.dump(self.snapshot, f)
			os.replace(tmp, self.state_path)
		except OSError as e:
			log.warning("cannot save Press bench snapshot %s: %s", self.state_path, e)
