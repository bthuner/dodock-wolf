"""File integrity on the bench (#72 step 7, planned in #47): what changed in the code, the site
configs and the web and process server configs, and whether a deployment explains it.

Watched, per bench:

- `code`: every file of every app under `apps/<app>/`, except what a bench builds or runs there
  (`.git`, `node_modules`, `public/dist` and other `dist`/`build` output, `*.egg-info`, caches,
  compiled `.pyc` and `.mo` files). A change while the app's git `HEAD` stayed the same was made
  outside a deployment (a web shell, a patched file): critical. A change with a new `HEAD` is a
  deployment: info, with the commits, or warning when it added Python under a `www/` folder (a
  page anyone can reach). An app without a git checkout (installed from an archive, or an image
  that drops `.git`) cannot tell one from the other: warning, and the title says so. While git
  holds a lock (a pull or checkout in progress), the app is judged at the next scan.
- `site_config`: `sites/common_site_config.json` and each `sites/<site>/site_config.json`. Only
  the names of the keys that were added, changed or removed are sent, never their values; a file
  rewritten with the same keys and values raises nothing.
- `server_config`: the bench's `config/` (nginx and supervisor files it generates, not `pids/`),
  and on the host `/etc/nginx` and `/etc/supervisor` (`integrity.server_paths`). A change there
  can redirect traffic or start a process.

Every `integrity.interval` (15 min) the agent compares size and modification time and hashes only
what changed; every `integrity.full_scan_interval` (24 h) it hashes everything again, so a file
whose size and time were put back is still caught. Files over MAX_HASH_BYTES are compared by size
and time only, and a pass stops after MAX_FILES files (what is left keeps its baseline until the
next pass), so a crafted tree cannot stall the agent.

The first scan of a path is its baseline and raises nothing. The baseline is kept in the spool
directory (`integrity-state.json`, mode 0600), so a restart does not hide what changed meanwhile.
A path discovery misses for a while keeps its baseline (for KEEP_UNSEEN); a path that is gone is
reported once, as removed. A file or folder the agent cannot read keeps its baseline instead of
reading as deleted, and is counted (`integrity_unreadable`). Site config values are kept as HMACs
under a key of this install (`integrity.key`, 0600), never in clear nor as plain hashes.

One event per app, config file or server path that changed, with up to MAX_LISTED paths of each
kind (added, modified, deleted): `bench_code_changed` for an app's code, `bench_config_changed`
for a site or server config, so a rule can watch one without the other. Metric `integrity_files`
counts what is watched, per bench (and for the host's own paths).
"""

import hashlib
import hmac
import json
import logging
import os
import time

from .util import event, fingerprint, metric, utc_iso

log = logging.getLogger(__name__)

STATE_FILE = "integrity-state.json"
KEY_FILE = "integrity.key"
MAX_LISTED = 20
MAX_FILES = 200_000  # per pass, over every path watched
MAX_HASH_BYTES = 32 * 1024 * 1024  # larger files: size and time only
KEEP_UNSEEN = 7 * 86400  # a baseline discovery has not seen for this long is dropped
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".venv",
             "dist", "build", "pids"}  # fmt: skip
SKIP_DIR_SUFFIXES = (".egg-info",)
SKIP_SUFFIXES = (".pyc", ".pyo", ".mo", ".log", ".pid", ".swp", ".tmp")
SKIP_NAMES = {"scheduler_process"}
GIT_LOCKS = ("index.lock", "HEAD.lock")
DEFAULT_SERVER_PATHS = ["/etc/nginx", "/etc/supervisor"]
SEVERITY = {"code": "critical", "deploy": "info", "deploy_web": "warning", "no_git": "warning", "removed": "warning",
            "site_config": "warning", "server_config": "warning"}  # fmt: skip
CATEGORY = {"code": "bench_code_changed", "site_config": "bench_config_changed", "server_config": "bench_config_changed"}
# what a change there can be (MITRE ATT&CK): a web shell or patched code, a tampered config
ATTACK = {"code": ["T1505.003", "T1565.001"], "deploy": [], "deploy_web": ["T1505.003"], "no_git": ["T1565.001"],
          "removed": ["T1565.001"], "site_config": ["T1565.001"], "server_config": ["T1565.001"]}  # fmt: skip


def file_digest(path, st):
	"""sha256 of the content, or `size:<n>` for a file too large to read every pass."""
	if st.st_size > MAX_HASH_BYTES:
		return f"size:{st.st_size}"
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def walk(root, errors):
	"""Regular files under `root` (a file or a directory), skipping what a bench builds or runs.
	Directories that could not be listed go to `errors`."""
	if os.path.isfile(root):
		yield root
		return
	for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: errors.append(e.filename)):
		dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(SKIP_DIR_SUFFIXES))
		for name in sorted(filenames):
			if name.endswith(SKIP_SUFFIXES) or name in SKIP_NAMES:
				continue
			path = os.path.join(dirpath, name)
			if os.path.isfile(path) and not os.path.islink(path):  # no FIFO, device or link out of the tree
				yield path


def git_dirs(app_dir):
	"""(git dir, common dir) of an app's checkout: they differ for a worktree; (None, None) without git."""
	git = os.path.join(app_dir, ".git")
	try:
		if os.path.isfile(git):  # a worktree or submodule: "gitdir: <path>"
			with open(git) as f:
				line = f.read().strip()
			if not line.startswith("gitdir:"):
				return None, None
			git = os.path.normpath(os.path.join(app_dir, line.split(":", 1)[1].strip()))
		if not os.path.isdir(git):
			return None, None
		common = git
		if os.path.isfile(os.path.join(git, "commondir")):
			with open(os.path.join(git, "commondir")) as f:
				common = os.path.normpath(os.path.join(git, f.read().strip()))
		return git, common
	except OSError:
		return None, None


def git_head(app_dir):
	"""The commit an app's checkout is at, or None (no git, unreadable)."""
	git, common = git_dirs(app_dir)
	if not git:
		return None
	try:
		with open(os.path.join(git, "HEAD")) as f:
			head = f.read().strip()
		if not head.startswith("ref:"):
			return head or None
		ref = head.split(":", 1)[1].strip()
		for base in (git, common):
			ref_file = os.path.join(base, ref)
			if os.path.isfile(ref_file):
				with open(ref_file) as f:
					return f.read().strip() or None
		with open(os.path.join(common, "packed-refs")) as f:
			for line in f:
				parts = line.split()
				if len(parts) == 2 and parts[1] == ref:
					return parts[0]
	except (OSError, IndexError):
		return None
	return None


def git_busy(app_dir):
	"""Whether git is changing the checkout right now (a pull or a checkout holds its locks)."""
	git, _common = git_dirs(app_dir)
	return bool(git) and any(os.path.exists(os.path.join(git, lock)) for lock in GIT_LOCKS)


def json_keys(path, key):
	"""{key: HMAC of its value} of a JSON object file, or None when it is not one."""
	try:
		with open(path) as f:
			data = json.load(f)
	except (OSError, ValueError):
		return None
	if not isinstance(data, dict):
		return None
	return {k: hmac.new(key, json.dumps(v, sort_keys=True, default=str).encode(), hashlib.sha256).hexdigest()
	        for k, v in data.items()}  # fmt: skip


def key_changes(before, after):
	"""Names only: added, changed and removed keys of a config file."""
	before, after = before or {}, after or {}
	return {
		"keys_added": sorted(set(after) - set(before)),
		"keys_changed": sorted(k for k in set(after) & set(before) if after[k] != before[k]),
		"keys_removed": sorted(set(before) - set(after)),
	}


def targets(benches, server_paths):
	"""(group, kind, bench, site, root, app) for everything watched; a group is one event's scope."""
	out = []
	for bench in benches:
		path = bench.get("path") or ""
		name = bench.get("name")
		apps_dir = os.path.join(path, "apps")
		try:
			apps = sorted(bench.get("apps") or (os.listdir(apps_dir) if os.path.isdir(apps_dir) else []))
		except OSError:
			apps = []
		for app in apps:
			root = os.path.join(apps_dir, app)
			if os.path.isdir(root) and not os.path.islink(root):
				out.append((f"code:{root}", "code", name, None, root, app))
		sites_dir = os.path.join(path, "sites")
		common = os.path.join(sites_dir, "common_site_config.json")
		out.append((f"config:{common}", "site_config", name, None, common, None))
		for site in bench.get("sites") or []:
			config = os.path.join(sites_dir, site, "site_config.json")
			out.append((f"config:{config}", "site_config", name, site, config, None))
		config_dir = os.path.join(path, "config")
		out.append((f"server:{config_dir}", "server_config", name, None, config_dir, None))
	for root in server_paths:
		out.append((f"server:{root}", "server_config", None, None, root, None))
	return out


def _write_private(path, data):
	"""Write `data` (bytes) to `path` atomically, readable by the agent's user only."""
	tmp = path + ".tmp"
	fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	try:
		os.write(fd, data)
		os.fsync(fd)
	finally:
		os.close(fd)
	os.replace(tmp, path)


class IntegrityWatcher:
	def __init__(self, host, state_path=None, server_paths=None, full_scan_interval=86400):
		self.host = host
		self.state_path = state_path
		self.server_paths = DEFAULT_SERVER_PATHS if server_paths is None else list(server_paths)
		self.full_scan_interval = full_scan_interval
		self.key = self._key()
		self.state = self._load()

	def _key(self):
		if not self.state_path:
			return os.urandom(32)  # a dry run keeps nothing
		path = os.path.join(os.path.dirname(self.state_path), KEY_FILE)
		try:
			with open(path, "rb") as f:
				key = f.read()
			if len(key) >= 32:
				return key
		except OSError:
			pass
		key = os.urandom(32)
		try:
			_write_private(path, key)
		except OSError as e:
			log.warning("could not save the integrity key: %s", e)
		return key

	def _load(self):
		empty = {"groups": {}, "last_full": None}
		if not self.state_path or not os.path.exists(self.state_path):
			return empty
		try:
			with open(self.state_path) as f:
				data = json.load(f)
			return data if isinstance(data, dict) and isinstance(data.get("groups"), dict) else empty
		except (OSError, ValueError):
			log.warning("integrity baseline unreadable, starting a new one")
			return empty

	def _save(self):
		if not self.state_path:
			return
		try:
			_write_private(self.state_path, json.dumps(self.state).encode())
		except OSError as e:
			log.warning("could not save the integrity baseline: %s", e)

	def scan(self, root, previous, full, budget):
		"""({path: [size, mtime_ns, digest]}, unreadable): hashes only what changed since `previous`,
		or all of it. A file or folder that cannot be read keeps its previous entry."""
		files, unreadable, errors = {}, 0, []
		for path in walk(root, errors):
			if budget["files"] <= 0:
				break
			budget["files"] -= 1
			old = previous.get(path)
			try:
				st = os.stat(path)
				if not full and old and old[0] == st.st_size and old[1] == st.st_mtime_ns:
					files[path] = old
				else:
					files[path] = [st.st_size, st.st_mtime_ns, file_digest(path, st)]
			except OSError:
				unreadable += 1
				if old:
					files[path] = old  # unreadable is not deleted
		for path, old in previous.items():  # under a folder that could not be listed: not deleted either
			if path not in files and any(path.startswith(d.rstrip(os.sep) + os.sep) for d in errors if d):
				files[path] = old
				unreadable += 1
		return files, unreadable

	def collect(self, benches, now=None, epoch=None):
		ts = utc_iso(now)
		epoch = (now.timestamp() if now else time.time()) if epoch is None else epoch
		last_full = self.state.get("last_full")
		full = last_full is None or epoch < float(last_full) or epoch - float(last_full) >= self.full_scan_interval
		metrics, events, counts, unreadable = [], [], {}, {}
		old_groups, groups = self.state.get("groups") or {}, {}
		budget = {"files": MAX_FILES}
		listed = targets(benches, self.server_paths)
		for group, kind, bench, site, root, app in listed:
			old = old_groups.get(group)
			if not os.path.exists(root):
				if old is not None:  # it was there: report it once, then forget it
					events.append(self._removed(kind, bench, site, root, app, old, ts))
				continue
			if budget["files"] <= 0 or (kind == "code" and git_busy(root)):
				if old is not None:
					groups[group] = old  # judged at a later pass, against the same baseline
				continue
			files, bad = self.scan(root, (old or {}).get("files") or {}, full, budget)
			new = {"files": files, "seen": epoch, "meta": [kind, bench, site, root, app]}
			if kind == "code":
				new["head"] = git_head(root)
			if kind == "site_config":
				new["keys"] = json_keys(root, self.key)
			groups[group] = new
			counts[bench] = counts.get(bench, 0) + len(files)
			unreadable[bench] = unreadable.get(bench, 0) + bad
			if old is not None:  # the first scan of a path is its baseline
				ev = self._change(kind, bench, site, root, app, old, new, ts)
				if ev:
					events.append(ev)
		listed_groups = {t[0] for t in listed}
		for group, old in old_groups.items():
			if group in listed_groups or group in groups:
				continue
			meta = old.get("meta")
			if meta and not os.path.exists(meta[3]) and os.path.isdir(os.path.dirname(meta[3])):
				# its folder is there, it is not (an app removed from apps/, a site dropped): report it once
				events.append(self._removed(*meta, old, ts))
			elif epoch - float(old.get("seen") or epoch) < KEEP_UNSEEN:
				groups[group] = old  # not discovered this time (a hiccup, a mount): keep the baseline a while
		self.state["groups"] = groups
		if full:
			self.state["last_full"] = epoch
		self._save()
		for bench in sorted(counts, key=lambda b: b or ""):
			metrics.append(metric("integrity_files", counts[bench], ts, self.host, bench))
			metrics.append(metric("integrity_unreadable", unreadable.get(bench, 0), ts, self.host, bench))
		return metrics, events

	def _event(self, kind, severity_key, bench, site, root, title, payload, ts):
		payload["attack_techniques"] = ATTACK[severity_key]
		return event("security", CATEGORY[kind], SEVERITY[severity_key], ts, self.host, title[:255],
		             fingerprint(self.host, CATEGORY[kind], root, ts), payload, source="integrity",
		             bench=bench, site=site)  # fmt: skip

	def _removed(self, kind, bench, site, root, app, old, ts):
		files = sorted(old.get("files") or {})
		rel = (lambda p: os.path.relpath(p, root)) if kind != "site_config" else (lambda p: p)
		payload = {"kind": kind, "path": root, "app": app, "removed": True, "added": [], "modified": [],
		           "deleted": [rel(p) for p in files[:MAX_LISTED]], "counts": {"added": 0, "modified": 0, "deleted": len(files)}}  # fmt: skip
		what = app or (os.path.basename(root) if kind == "site_config" else root)
		return self._event(kind, "removed", bench, site, root, f"{what} removed", payload, ts)

	def _change(self, kind, bench, site, root, app, old, new, ts):
		before, after = old.get("files") or {}, new["files"]
		added = sorted(set(after) - set(before))
		deleted = sorted(set(before) - set(after))
		modified = sorted(p for p in set(after) & set(before) if after[p][2] != before[p][2])
		if not (added or deleted or modified):
			return None
		rel = (lambda p: os.path.relpath(p, root)) if os.path.isdir(root) else (lambda p: p)
		payload = {
			"kind": kind, "path": root, "app": app,
			"added": [rel(p) for p in added[:MAX_LISTED]], "modified": [rel(p) for p in modified[:MAX_LISTED]],
			"deleted": [rel(p) for p in deleted[:MAX_LISTED]],
			"counts": {"added": len(added), "modified": len(modified), "deleted": len(deleted)},
		}  # fmt: skip
		total = len(added) + len(modified) + len(deleted)
		if kind == "site_config":
			changes = key_changes(old.get("keys"), new.get("keys"))
			if old.get("keys") is not None and new.get("keys") is not None and not any(changes.values()):
				return None  # rewritten with the same keys and values
			payload.update(changes)
			names = changes["keys_added"] + changes["keys_changed"] + changes["keys_removed"]
			title = f"{os.path.basename(root)} changed" + (f": {', '.join(names[:5])}" if names else "")
			return self._event(kind, kind, bench, site, root, title, payload, ts)
		if kind == "server_config":
			return self._event(kind, kind, bench, site, root, f"Server config changed under {root}: {total} files", payload, ts)
		no_git = new.get("head") is None and old.get("head") is None
		deploy = old.get("head") != new.get("head") and new.get("head") is not None
		web_code = [rel(p) for p in added if f"{os.sep}www{os.sep}" in os.sep + rel(p) and p.endswith(".py")]
		payload.update(deploy=None if no_git else deploy, git_head_before=old.get("head"), git_head_after=new.get("head"))
		if deploy:
			payload["added_web_code"] = web_code[:MAX_LISTED]
			short = f"{(old.get('head') or '?')[:8]} → {(new.get('head') or '?')[:8]}"
			title = f"{app} updated ({short}): {total} files" + (f", new web code: {', '.join(web_code[:3])}" if web_code else "")
			severity_key = "deploy_web" if web_code else "deploy"
		elif no_git:
			title, severity_key = f"{app}: {total} files changed (no git checkout to tell a deployment)", "no_git"
		else:
			title, severity_key = f"{app}: {total} files changed outside a deployment", "code"
		return self._event(kind, severity_key, bench, site, root, title, payload, ts)
