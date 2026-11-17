"""File integrity on the bench (#72 step 7, planned in #47): what changed in the code, the site
configs and the web and process server configs, and whether a deployment explains it.

Watched, per bench:

- `code`: every file of every app under `apps/<app>/`, except `.git`, `node_modules`, caches and
  compiled files. A change while the app's git `HEAD` stayed the same was made outside a
  deployment (a web shell, a patched file): critical. A change with a new `HEAD` is a deployment:
  info, with the commits. An app without a git checkout (installed from an archive, or an image
  that drops `.git`) cannot tell one from the other: warning, and the title says so.
- `site_config`: `sites/common_site_config.json` and each `sites/<site>/site_config.json`. Only
  the names of the keys that were added, changed or removed are sent, never their values.
- `server_config`: the bench's `config/` (nginx and supervisor files it generates), and on the
  host `/etc/nginx` and `/etc/supervisor` (`integrity.server_paths`). A change there can
  redirect traffic or start a process.

Every `integrity.interval` (15 min) the agent compares size and modification time and hashes only
what changed; every `integrity.full_scan_interval` (24 h) it hashes everything again, so a file
whose size and time were put back is still caught. The first scan of a path is the baseline and
raises nothing. The baseline is kept in the spool directory (`integrity-state.json`), so a
restart does not hide what changed meanwhile.

One event per app, config file or server path that changed, with up to MAX_LISTED paths of each
kind (added, modified, deleted): `bench_code_changed` for an app's code, `bench_config_changed`
for a site or server config, so a rule can watch one without the other. Metric `integrity_files` counts what is
watched, per bench (and for the host's own paths).
"""

import hashlib
import json
import logging
import os

from .util import event, fingerprint, metric, utc_iso

log = logging.getLogger(__name__)

STATE_FILE = "integrity-state.json"
MAX_LISTED = 20
MAX_FILES = 200_000  # per scan: a runaway tree is not walked to the end
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".venv"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".log", ".swp", ".tmp")
DEFAULT_SERVER_PATHS = ["/etc/nginx", "/etc/supervisor"]
SEVERITY = {"code": "critical", "deploy": "info", "no_git": "warning", "site_config": "warning", "server_config": "warning"}
CATEGORY = {"code": "bench_code_changed", "site_config": "bench_config_changed", "server_config": "bench_config_changed"}
# what a change there can be (MITRE ATT&CK): a web shell or patched code, a tampered config
ATTACK = {"code": ["T1505.003", "T1565.001"], "deploy": [], "no_git": ["T1565.001"], "site_config": ["T1565.001"],
          "server_config": ["T1565.001"]}  # fmt: skip


def sha256(path):
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def walk(root):
	"""Regular files under `root` (a file or a directory), skipping caches and VCS data."""
	if os.path.isfile(root):
		yield root
		return
	for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
		dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
		for name in sorted(filenames):
			if not name.endswith(SKIP_SUFFIXES):
				path = os.path.join(dirpath, name)
				if os.path.isfile(path) and not os.path.islink(path):
					yield path


def git_head(app_dir):
	"""The commit an app's checkout is at, or None (no git, unreadable)."""
	git = os.path.join(app_dir, ".git")
	try:
		if os.path.isfile(git):  # a worktree or submodule: "gitdir: <path>"
			with open(git) as f:
				line = f.read().strip()
			git = os.path.join(app_dir, line.split(":", 1)[1].strip()) if line.startswith("gitdir:") else git
		with open(os.path.join(git, "HEAD")) as f:
			head = f.read().strip()
		if not head.startswith("ref:"):
			return head or None
		ref = head.split(":", 1)[1].strip()
		ref_file = os.path.join(git, ref)
		if os.path.isfile(ref_file):
			with open(ref_file) as f:
				return f.read().strip() or None
		with open(os.path.join(git, "packed-refs")) as f:
			for line in f:
				parts = line.split()
				if len(parts) == 2 and parts[1] == ref:
					return parts[0]
	except (OSError, IndexError):
		return None
	return None


def json_keys(path):
	"""{key: sha256 of its value} of a JSON object file, or None when it is not one."""
	try:
		with open(path) as f:
			data = json.load(f)
	except (OSError, ValueError):
		return None
	if not isinstance(data, dict):
		return None
	return {k: hashlib.sha256(json.dumps(v, sort_keys=True, default=str).encode()).hexdigest() for k, v in data.items()}


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
		for app in sorted(bench.get("apps") or (os.listdir(apps_dir) if os.path.isdir(apps_dir) else [])):
			root = os.path.join(apps_dir, app)
			if os.path.isdir(root):
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


class IntegrityWatcher:
	def __init__(self, host, state_path=None, server_paths=None, full_scan_interval=86400):
		self.host = host
		self.state_path = state_path
		self.server_paths = DEFAULT_SERVER_PATHS if server_paths is None else list(server_paths)
		self.full_scan_interval = full_scan_interval
		self.state = self._load()

	def _load(self):
		empty = {"groups": {}, "last_full": 0}
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
		tmp = self.state_path + ".tmp"
		try:
			with open(tmp, "w") as f:
				json.dump(self.state, f)
			os.replace(tmp, self.state_path)
		except OSError:
			log.exception("could not save the integrity baseline")

	def scan(self, root, previous, full):
		"""{path: [size, mtime_ns, sha256]}: hashes only what changed since `previous`, or all of it."""
		files, count = {}, 0
		for path in walk(root):
			count += 1
			if count > MAX_FILES:
				log.warning("integrity: more than %d files under %s, the rest is not watched", MAX_FILES, root)
				break
			try:
				st = os.stat(path)
				old = previous.get(path)
				if not full and old and old[0] == st.st_size and old[1] == st.st_mtime_ns:
					files[path] = old
				else:
					files[path] = [st.st_size, st.st_mtime_ns, sha256(path)]
			except OSError:
				continue  # gone or unreadable meanwhile
		return files

	def collect(self, benches, now=None, epoch=None):
		ts = utc_iso(now)
		epoch = (now.timestamp() if now else 0) if epoch is None else epoch
		full = epoch - float(self.state.get("last_full") or 0) >= self.full_scan_interval
		metrics, events, counts, groups = [], [], {}, {}
		for group, kind, bench, site, root, app in targets(benches, self.server_paths):
			if not os.path.exists(root):
				continue
			old = self.state["groups"].get(group)
			files = self.scan(root, (old or {}).get("files") or {}, full)
			now_group = {"files": files}
			if kind == "code":
				now_group["head"] = git_head(root)
			if kind == "site_config":
				now_group["keys"] = json_keys(root)
			groups[group] = now_group
			counts[bench] = counts.get(bench, 0) + len(files)
			if old is not None:  # the first scan of a path is its baseline
				ev = self._change(kind, bench, site, root, app, old, now_group, ts)
				if ev:
					events.append(ev)
		self.state["groups"] = groups
		if full:
			self.state["last_full"] = epoch
		self._save()
		for bench, n in sorted(counts.items(), key=lambda kv: kv[0] or ""):
			metrics.append(metric("integrity_files", n, ts, self.host, bench))
		return metrics, events

	def _change(self, kind, bench, site, root, app, old, new, ts):
		before, after = old.get("files") or {}, new["files"]
		added = sorted(set(after) - set(before))
		deleted = sorted(set(before) - set(after))
		modified = sorted(p for p in set(after) & set(before) if after[p][2] != before[p][2])
		if not (added or deleted or modified):
			return None
		no_git = kind == "code" and new.get("head") is None and old.get("head") is None
		deploy = kind == "code" and old.get("head") != new.get("head") and new.get("head") is not None
		severity_key = "deploy" if deploy else "no_git" if no_git else kind
		rel = (lambda p: os.path.relpath(p, root)) if os.path.isdir(root) else (lambda p: p)
		payload = {
			"kind": kind, "path": root, "app": app,
			"added": [rel(p) for p in added[:MAX_LISTED]], "modified": [rel(p) for p in modified[:MAX_LISTED]],
			"deleted": [rel(p) for p in deleted[:MAX_LISTED]],
			"counts": {"added": len(added), "modified": len(modified), "deleted": len(deleted)},
			"attack_techniques": ATTACK[severity_key],
		}  # fmt: skip
		total = len(added) + len(modified) + len(deleted)
		if kind == "code":
			payload.update(deploy=None if no_git else deploy, git_head_before=old.get("head"), git_head_after=new.get("head"))
			if deploy:
				title = f"{app} updated ({(old.get('head') or '?')[:8]} → {(new.get('head') or '?')[:8]}): {total} files"
			elif no_git:
				title = f"{app}: {total} files changed (no git checkout to tell a deployment)"
			else:
				title = f"{app}: {total} files changed outside a deployment"
		elif kind == "site_config":
			payload.update(key_changes(old.get("keys"), new.get("keys")))
			names = payload["keys_added"] + payload["keys_changed"] + payload["keys_removed"]
			title = f"{os.path.basename(root)} changed" + (f": {', '.join(names[:5])}" if names else "")
		else:
			title = f"Server config changed under {root}: {total} files"
		return event("security", CATEGORY[kind], SEVERITY[severity_key], ts, self.host, title[:255],
		             fingerprint(self.host, CATEGORY[kind], root, ts), payload, source="integrity",
		             bench=bench, site=site)  # fmt: skip
