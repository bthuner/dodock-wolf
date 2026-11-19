"""Where Suricata writes its EVE log, found from Suricata itself (#72 step 1).

In order:

1. `suricata.eve_log` in the agent's config, when set;
2. a running Suricata: its command line (readable by anyone in /proc) gives `-c <suricata.yaml>`
   and `-l <log dir>`, and the config gives `default-log-dir` and the enabled `eve-log` output
   (`filename`, `filetype: regular`). When Suricata runs in a container, its paths are mapped to
   the host through the container's mountinfo (the log folder must be a bind mount: a log kept in
   the image's own layers cannot be read without root);
3. when no running Suricata gives a readable log, `suricata.yaml` where packages and source installs
   put it;
4. `/var/log/suricata/eve.json`, as before.

`discover()` returns `(path, how)`, or `(None, why)`. The collector runs it at start and every
RECHECK seconds, so a Suricata started after the agent is picked up. One EVE log is read: the
first running Suricata that gives one. Not read: `include:` files, flow-style outputs, `threaded`
outputs (one file per thread). Pilot hosts are read the same
way: Pilot does not know about Suricata.
"""

import os
import re

CONFIGS = ("/etc/suricata/suricata.yaml", "/usr/local/etc/suricata/suricata.yaml")
DEFAULT_LOG_DIR = "/var/log/suricata"
DEFAULT_EVE = "/var/log/suricata/eve.json"
RECHECK = 300
_CGROUP = re.compile(r"(?:docker-|/docker/|cri-containerd-|crio-|libpod-)([0-9a-f]{64})|/([0-9a-f]{64})(?:\.scope)?$", re.M)


def _value(line):
	text = line.split("#", 1)[0].split(":", 1)[1].strip()
	return text.strip("'\"")


def parse_config(text):
	"""(default-log-dir or None, [{"enabled", "filetype", "filename"}] of the eve-log outputs) from a
	suricata.yaml, read line by line (no YAML library in the agent)."""
	log_dir, outputs, block, child = None, [], None, None
	for raw in (text or "").splitlines():
		line = raw.rstrip()
		stripped = line.lstrip()
		if not stripped or stripped.startswith("#"):
			continue
		indent = len(line) - len(stripped)
		if re.match(r"^-\s*eve-log\s*:\s*#", stripped):  # `- eve-log: # comment`
			stripped = stripped.split("#", 1)[0].rstrip()
		if indent == 0 and stripped.startswith("default-log-dir:"):
			log_dir = _value(stripped) or None
		m = re.match(r"^-\s*eve-log\s*:\s*$", stripped)
		if m:
			# Suricata skips an output without `enabled: yes`
			block, child = {"indent": indent, "enabled": False, "filetype": "regular", "filename": "eve.json",
			                "threaded": False}, None  # fmt: skip
			outputs.append(block)
			continue
		if block is None:
			continue
		if indent <= block["indent"]:
			block = None  # the next output, or the end of `outputs`
			continue
		child = indent if child is None else child
		if indent != child or ":" not in stripped:
			continue  # deeper keys (types, xff...) are not ours
		key = stripped.split(":", 1)[0].strip()
		if key == "enabled":
			block["enabled"] = _value(stripped).lower() in ("yes", "true", "on", "1")
		elif key == "threaded":
			block["threaded"] = _value(stripped).lower() in ("yes", "true", "on", "1")
		elif key in ("filetype", "filename"):
			block[key] = _value(stripped) or block[key]
	return log_dir, [{k: o[k] for k in ("enabled", "filetype", "filename", "threaded")} for o in outputs]


def eve_path(config_text, log_dir_flag=None):
	"""The EVE log a config writes to, or None (no enabled eve-log output to a regular file)."""
	log_dir, outputs = parse_config(config_text)
	for output in outputs:
		# a threaded output writes eve.<n>.json, one per thread: not one file to tail
		if (output["enabled"] and output["filetype"] in ("regular", "file") and "%" not in output["filename"]
		        and not output["threaded"]):  # fmt: skip
			name = output["filename"]
			return name if os.path.isabs(name) else os.path.join(log_dir_flag or log_dir or DEFAULT_LOG_DIR, name)
	return None


def suricata_processes(proc="/proc"):
	"""[(pid, argv)] of the running Suricata processes, from /proc/<pid>/cmdline."""
	out = []
	try:
		pids = sorted(int(p) for p in os.listdir(proc) if p.isdigit())
	except OSError:
		return out
	for pid in pids:
		try:
			with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
				argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
		except OSError:
			continue
		if argv and os.path.basename(argv[0]) in ("suricata", "Suricata-Main"):
			out.append((pid, argv))
	return out


def flags(argv):
	"""(-c config, -l log dir) from a Suricata command line, either may be None.
	`--set default-log-dir=…` counts as -l when -l is not given."""
	config = log_dir = set_dir = None
	for i, arg in enumerate(argv):
		value = argv[i + 1] if i + 1 < len(argv) else None
		if arg == "--set" and value and value.startswith("default-log-dir="):
			set_dir = value.split("=", 1)[1]
		elif arg.startswith("--set=default-log-dir="):
			set_dir = arg.split("=", 2)[2]
		elif arg == "-c":
			config = value
		elif arg.startswith("-c") and len(arg) > 2:
			config = arg[2:]
		elif arg == "-l":
			log_dir = value
		elif arg.startswith("-l") and len(arg) > 2:
			log_dir = arg[2:]
	return config, log_dir or set_dir


def _unescape(field):
	"""mountinfo escapes spaces, tabs, newlines and backslashes as octal (`\\040`)."""
	return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def _mounts(path):
	try:
		with open(path, errors="replace") as f:
			return [(p[2], _unescape(p[3]), _unescape(p[4])) for p in (line.split() for line in f) if len(p) > 4]
	except OSError:
		return []


def host_path(path, pid, proc="/proc", self_mountinfo="/proc/self/mountinfo"):
	"""The host path of a path seen inside a container (through its bind mounts), or None."""
	best = None  # the container's mount holding `path`, deepest first
	for dev, root, point in _mounts(os.path.join(proc, str(pid), "mountinfo")):
		if path == point or path.startswith(point.rstrip("/") + "/"):
			if best is None or len(point) > len(best[2]):
				best = (dev, root, point)
	if not best:
		return None
	dev, root, point = best
	inside = os.path.normpath(root.rstrip("/") + "/" + path[len(point.rstrip("/")):].lstrip("/"))
	for my_dev, my_root, my_point in sorted(_mounts(self_mountinfo), key=lambda m: -len(m[1])):
		if my_dev == dev and (inside == my_root or inside.startswith(my_root.rstrip("/") + "/")):
			return os.path.normpath(my_point.rstrip("/") + "/" + inside[len(my_root.rstrip("/")):].lstrip("/"))
	return None


def _root(mountinfo):
	return next(((dev, root) for dev, root, point in _mounts(mountinfo) if point == "/"), None)


def in_container(pid, proc="/proc", self_mountinfo="/proc/self/mountinfo"):
	"""Whether the process sees another filesystem root than the agent: any runtime (Docker,
	Podman, LXC, nspawn), and right too when the agent itself runs in a container. Falls back on
	the cgroup name when its mountinfo cannot be read."""
	theirs, ours = _root(os.path.join(proc, str(pid), "mountinfo")), _root(self_mountinfo)
	if theirs and ours:
		return theirs != ours
	try:
		with open(os.path.join(proc, str(pid), "cgroup")) as f:
			return bool(_CGROUP.search(f.read()))
	except OSError:
		return False


def _seen(path, pid, contained, proc, self_mountinfo):
	"""A path of the Suricata process, as the agent sees it (mapped when it runs in a container)."""
	return host_path(path, pid, proc, self_mountinfo) if contained else path


def reachable(path):
	"""Whether the agent can open `path`, or the folder it will appear in (Suricata just started)."""
	if os.path.exists(path):
		return os.access(path, os.R_OK)
	folder = os.path.dirname(path)
	while folder and not os.path.exists(folder):
		folder = os.path.dirname(folder)
	return os.access(folder or "/", os.R_OK | os.X_OK)


def _read(path):
	try:
		with open(path, errors="replace") as f:
			return f.read()
	except OSError:
		return None


def discover(configured=None, proc="/proc", self_mountinfo="/proc/self/mountinfo", configs=CONFIGS, default=DEFAULT_EVE):
	"""(EVE log path, how it was found) or (None, why not)."""
	if configured:
		return configured, "config"
	why = None  # the first process's problem, when no process gives a readable log
	for pid, argv in suricata_processes(proc):
		config, log_dir = flags(argv)
		contained = in_container(pid, proc, self_mountinfo)
		text = None
		for candidate in [config] if config else CONFIGS:  # a source install reads /usr/local/etc
			text = _read(_seen(candidate, pid, contained, proc, self_mountinfo) or "")
			if text is not None:
				break
		path = eve_path(text, log_dir) if text is not None else os.path.join(log_dir or DEFAULT_LOG_DIR, "eve.json")
		if not path:
			why = why or f"Suricata pid {pid} has no eve-log output to a single regular file"
			continue
		mapped = _seen(path, pid, contained, proc, self_mountinfo)
		if mapped and reachable(mapped):
			return mapped, f"Suricata pid {pid}" + (" (container)" if contained else "")
		if mapped:
			why = why or (f"Suricata pid {pid} writes {mapped}, which the agent cannot read: bind-mount its log "
			              "folder somewhere the agent can read, or set suricata.eve_log")  # fmt: skip
		else:
			why = why or f"Suricata pid {pid} writes {path} inside its container, not to a folder mounted from the host"
	if why:
		return None, why
	for config in configs:
		text = _read(config)
		if text is not None:
			path = eve_path(text)
			if path:
				return path, config
	if os.path.exists(default):
		return default, "default"
	return None, "no Suricata found"
