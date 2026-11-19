"""Outbound connections of bench processes to destinations never seen for them (#72 step 7).

A light hint of command-and-control or exfiltration for a bench without Suricata, not packet
inspection. Every `outbound.interval` (60 s) the agent reads `/proc/net/tcp` and `/proc/net/tcp6`
(no root needed, no external tool) and keeps the established connections that:

- belong to a bench's user (the owner of the bench folder): `/proc/net/tcp` names each socket's
  uid, while which process holds it would need root. Benches sharing one user share one record,
  and anything else that user runs (an SSH session, a `git push`) counts as the bench's. A bench
  owned by root is skipped: everything root does would count. A bench in Docker (another network
  namespace) is not seen, and an outbound proxy on a private address hides the real destinations;
- leave from a local port nothing listens on: the bench is the client, not answering a visitor;
- go to a public address: private, loopback and link-local peers (MariaDB, Redis, a LAN API)
  are left out unless `outbound.include_private`.

A destination is the remote network (/24 for IPv4, /48 for IPv6) and port. For `learn_days`
(7) after the agent first sees a bench's user, every destination is learned silently. After that,
each new destination on an unusual port is reported once as `bench_new_outbound` (warning); on a
usual port (web, mail, DNS, NTP, SSH and git, LDAP; `outbound.usual_ports` adds more) it is only
counted (`bench_new_outbound_usual`), since clouds rotate their addresses all day, unless
`outbound.report_usual_ports` sends those too, at info. At most MAX_PER_SCAN events per scan; the
rest stay new and come out at the next scans. A destination unseen for FORGET_DAYS is forgotten.
The record is kept in the spool directory (`outbound-state.json`, 0600).

The event names the destination in `remote_ip` / `remote_port`, never in `ip`: on the Wolf site
`ip` is the remote party of an attack (incident grouping, sequence rules, CrowdSec, block
proposals), while `remote_ip` is searchable and checked against the IP reputation lists.

A snapshot every interval misses a connection that opened and closed in between: this samples,
it does not record every connection.
"""

import ipaddress
import json
import logging
import os
import re
import subprocess
import sys
import time

from .tailer import FileTailer, JournalTailer
from .util import event, fingerprint, metric, utc_iso

log = logging.getLogger(__name__)

STATE_FILE = "outbound-state.json"
ESTABLISHED, LISTEN = "01", "0A"
FORGET_DAYS = 30
MAX_PER_SCAN = 20  # events per scan: a burst of new destinations is one alert, not hundreds
MAX_SEEN = 5000  # destinations kept per user
USUAL_PORTS = {80, 443, 25, 465, 587, 2525, 110, 143, 993, 995, 53, 123, 853, 22, 9418, 389, 636}
ATTACK = ["T1071", "T1041"]


# /proc/net prints each 32-bit word of an address in the host's byte order
def _ipv4(hexaddr):
	return str(ipaddress.IPv4Address(int(hexaddr, 16).to_bytes(4, sys.byteorder)))


def _ipv6(hexaddr):
	raw = b"".join(int(hexaddr[i : i + 8], 16).to_bytes(4, sys.byteorder) for i in range(0, 32, 8))
	ip = ipaddress.IPv6Address(raw)
	return str(ip.ipv4_mapped or ip)  # a dual-stack socket's IPv4 peer, written as IPv4


def parse(text, ipv6=False):
	"""(state, local ip, local port, remote ip, remote port, uid) of each socket of a /proc/net table."""
	out = []
	for line in (text or "").splitlines()[1:]:
		parts = line.split()
		if len(parts) < 8:
			continue
		try:
			(laddr, lport), (raddr, rport) = parts[1].rsplit(":", 1), parts[2].rsplit(":", 1)
			to_ip = _ipv6 if ipv6 else _ipv4
			out.append((parts[3], to_ip(laddr), int(lport, 16), to_ip(raddr), int(rport, 16), int(parts[7])))
		except (ValueError, ipaddress.AddressValueError):
			continue
	return out


def read_table(net_dir):
	"""(sockets, inodes) of a /proc/.../net directory: the inodes tell two network namespaces apart."""
	sockets, inodes = [], set()
	for name, ipv6 in (("tcp", False), ("tcp6", True)):
		try:
			with open(os.path.join(net_dir, name)) as f:
				text = f.read()
		except OSError:
			continue
		sockets += parse(text, ipv6)
		for line in text.splitlines()[1:]:
			parts = line.split()
			if len(parts) > 9 and parts[9] != "0":
				inodes.add(parts[9])
	return sockets, inodes


def read_sockets(proc_root="/proc/net"):
	return read_table(proc_root)[0]


# --- benches in containers (Docker, Podman): no root needed --------------------------------

CGROUP_RE = re.compile(r"(?:docker-|/docker/|cri-containerd-|crio-|libpod-)([0-9a-f]{64})")
# any other layout naming the container by its id (kubepods with the cgroupfs driver, nerdctl)
CGROUP_FALLBACK_RE = re.compile(r"/([0-9a-f]{64})(?:\.scope)?$", re.M)


def container_id(cgroup_text):
	m = CGROUP_RE.search(cgroup_text) or CGROUP_FALLBACK_RE.search(cgroup_text)
	return m.group(1) if m else None


def containers(proc="/proc", cache=None):
	"""{container id: its lowest pid}, from /proc/<pid>/cgroup (readable by anyone). `cache`
	({pid: (start, id)}) skips the cgroup of a process already read: a pid's /proc entry keeps its
	time until the pid is reused."""
	out = {}
	try:
		pids = [int(p) for p in os.listdir(proc) if p.isdigit()]
	except OSError:
		return out
	fresh = {}
	for pid in sorted(pids):
		try:
			start = os.stat(os.path.join(proc, str(pid))).st_ctime_ns
			cached = (cache or {}).get(pid)
			if cached and cached[0] == start:
				cid = cached[1]
			else:
				with open(os.path.join(proc, str(pid), "cgroup")) as f:
					cid = container_id(f.read())
		except OSError:
			continue
		fresh[pid] = (start, cid)
		if cid and cid not in out:
			out[cid] = pid
	if cache is not None:
		cache.clear()
		cache.update(fresh)
	return out


def mount_lines(path):
	"""(maj:min, root inside its filesystem, mount point) of each line of a mountinfo file."""
	try:
		with open(path) as f:
			return [(p[2], p[3], p[4]) for p in (line.split() for line in f) if len(p) > 4]
	except OSError:
		return []


def bench_filesystems(benches, self_mountinfo="/proc/self/mountinfo"):
	"""{bench name: (maj:min, its path inside that filesystem)}: what a container mounting it shows
	in its own mountinfo, whatever the bench path is on the host."""
	mounts = mount_lines(self_mountinfo)
	out = {}
	for bench in benches:
		path = os.path.realpath(bench.get("path") or "")
		try:
			st = os.stat(path)
		except OSError:
			continue
		dev = f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
		best = None  # the mount of that device holding the bench, deepest mount point first
		for majmin, root, point in mounts:
			if majmin == dev and (path == point or path.startswith(point.rstrip("/") + "/")):
				if best is None or len(point) > len(best[1]):
					best = (root, point)
		if best:
			rel = path[len(best[1].rstrip("/")):] or "/"
			out[bench.get("name")] = (dev, os.path.normpath(best[0].rstrip("/") + "/" + rel.lstrip("/")))
	return out


def container_bench(pid, filesystems, proc="/proc"):
	"""The bench a container belongs to: one that mounts the bench folder (or a folder in it) from
	the same filesystem, from /proc/<pid>/mountinfo (readable by anyone)."""
	for majmin, root, _point in mount_lines(os.path.join(proc, str(pid), "mountinfo")):
		for name, (dev, rel) in sorted(filesystems.items(), key=lambda kv: -len(kv[1][1])):
			if majmin == dev and (root == rel or root.startswith(rel.rstrip("/") + "/")):
				return name
	return None


def local_addresses(net_dir):
	"""The addresses of a network namespace, from fib_trie (IPv4 `/32 host LOCAL`) and if_inet6."""
	out = set()
	try:
		with open(os.path.join(net_dir, "fib_trie")) as f:
			last = None
			for line in f:
				text = line.strip()
				if text.startswith("|--"):
					last = text[3:].strip()
				elif "/32 host LOCAL" in text and last:
					out.add(last)
	except OSError:
		pass
	try:
		with open(os.path.join(net_dir, "if_inet6")) as f:
			for line in f:
				word = line.split()[0] if line.split() else ""
				if len(word) == 32:
					out.add(str(ipaddress.IPv6Address(int(word, 16))))
	except (OSError, ValueError):
		pass
	return {a for a in out if not ipaddress.ip_address(a).is_loopback}


# --- outbound proxies: the real destinations, from the proxy's access log -------------------

DEFAULT_PROXY_LOGS = [{"path": "/var/log/squid/access.log", "format": "squid"}]


def proxy_specs(value):
	"""[{"path", "format"}] from `outbound.proxy_logs`: a path alone means Squid; anything else is
	dropped with a warning, so one bad entry does not stop outbound detection."""
	out = []
	for item in DEFAULT_PROXY_LOGS if value is None else (value or []):
		spec = {"path": item, "format": "squid"} if isinstance(item, str) else item
		if isinstance(spec, dict) and spec.get("path") and (spec.get("format") or "squid") in PROXY_PARSERS:
			out.append({"path": spec["path"], "format": spec.get("format") or "squid"})
		else:
			log.warning("outbound.proxy_logs: %r is not {\"path\", \"format\": \"squid\"}, ignored", item)
	return out


def parse_squid(line):
	"""(client ip, host, port, remote ip or None) from a Squid native access.log line, or None.

	`1700000000.123 120 172.18.0.5 TCP_TUNNEL/200 3800 CONNECT api.stripe.com:443 - HIER_DIRECT/52.1.2.3 -`
	"""
	parts = line.split()
	if len(parts) < 9:
		return None
	client, method, url, peer = parts[2], parts[5], parts[6], parts[8]
	if method == "CONNECT":
		host, _, port = url.rpartition(":")
	else:
		m = re.match(r"^(https?)://([^/:]+)(?::(\d+))?", url)
		if not m:
			return None
		host, port = m.group(2), m.group(3) or ("443" if m.group(1) == "https" else "80")
	try:
		ipaddress.ip_address(client)
		port = int(port)
	except ValueError:
		return None
	remote = peer.split("/", 1)[1] if "/" in peer else None
	try:
		remote = str(ipaddress.ip_address(remote)) if remote and remote != "-" else None
	except ValueError:
		remote = None
	return client, host.strip("[]").lower(), port, remote


PROXY_PARSERS = {"squid": parse_squid}


# --- every new connection: the kernel log, when wolf-outbound-log is installed -------------

HELPER = "/usr/local/sbin/wolf-outbound-log"
KERN_LOG = "/var/log/kern.log"
_KV = re.compile(r"\b([A-Z]+)=(\S*)")


def parse_kernel(line):
	"""("out", src, dst, port, uid) for a `wolf-out: ` line, ("fwd", src, dst, port, None) for a
	`wolf-fwd: ` one, else None. The fields are netfilter's own: SRC=, DST=, DPT=, UID=."""
	for kind, marker in (("out", "wolf-out: "), ("fwd", "wolf-fwd: ")):
		at = line.find(marker)
		if at < 0:
			continue
		fields = dict(_KV.findall(line[at + len(marker):]))
		try:
			dst, port = str(ipaddress.ip_address(fields["DST"])), int(fields["DPT"])
			src = str(ipaddress.ip_address(fields["SRC"]))
			uid = int(fields["UID"]) if kind == "out" and fields.get("UID") else None
		except (KeyError, ValueError):
			return None
		return kind, src, dst, port, uid
	return None


def public(address, include_private=False):
	ip = ipaddress.ip_address(address)
	if getattr(ip, "ipv4_mapped", None):
		ip = ip.ipv4_mapped
	if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
		return False
	return include_private or ip.is_global


def destination(address, port):
	"""The remote network (/24, /48) and port: a CDN's next address is not a new destination."""
	ip = ipaddress.ip_address(address)
	if getattr(ip, "ipv4_mapped", None):
		ip = ip.ipv4_mapped
	net = ipaddress.ip_network(f"{ip}/{24 if ip.version == 4 else 48}", strict=False)
	return f"{net}:{port}"


def outbound(sockets, uids, include_private=False):
	"""{uid: {destination: (remote ip, remote port, host name)}} of the client connections of `uids`
	(None: every uid, a container's)."""
	listening = {lport for state, _l, lport, _r, _rp, _u in sockets if state == LISTEN}
	out = {}
	for state, _laddr, lport, raddr, rport, uid in sockets:
		if state != ESTABLISHED or (uids is not None and uid not in uids) or lport in listening:
			continue
		try:
			if not public(raddr, include_private):
				continue
			out.setdefault(uid, {}).setdefault(destination(raddr, rport), (raddr, rport, None))
		except ValueError:
			continue
	return out


def bench_users(benches):
	"""{uid: [bench names]}: the owner of each bench folder; root is skipped (everything it runs
	would count as the bench's)."""
	users = {}
	for bench in benches:
		try:
			uid = os.stat(bench.get("path") or "").st_uid
		except OSError:
			continue
		if uid == 0:
			log.warning("outbound: bench %s belongs to root, its connections are not watched", bench.get("name"))
			continue
		users.setdefault(uid, []).append(bench.get("name"))
	return users


class OutboundWatcher:
	"""New destinations per subject: a bench's user on the host (`<uid>`), a bench in a container
	(`bench:<name>`), or the host's benches behind a proxy (`proxy:host`)."""

	def __init__(self, host, state_path=None, learn_days=7, include_private=False, proc_root="/proc/net", usual_ports=None,
	             report_usual_ports=False, proc="/proc", proxy_logs=None, self_mountinfo="/proc/self/mountinfo",
	             kernel_log="auto", helper=HELPER, kernel_source=None, run=None):  # fmt: skip
		self.host = host
		self.state_path = state_path
		self.learn_seconds = float(learn_days) * 86400
		self.include_private = include_private
		self.usual_ports = USUAL_PORTS | {int(p) for p in (usual_ports or [])}
		self.report_usual_ports = report_usual_ports
		self.proc_root = proc_root
		self.proc = proc
		self.proxy_logs = proxy_specs(proxy_logs)
		self.self_mountinfo = self_mountinfo
		self.state = self._load()
		self.tailers = {}
		self.cgroups = {}  # pid -> (start, container id)
		self.absent = set()  # proxy logs missing at a scan: read from their start once they appear
		self.unreadable = set()  # proxy logs already warned about
		# every new connection, when the operator installed the helper (wolf-outbound-log.sh)
		installed = os.path.exists(helper)
		self.helper = helper if kernel_log and installed else None
		self.turn_off = helper if not kernel_log and installed else None  # remove the table once
		self.kernel_source = kernel_source
		self.run = run or subprocess.run
		self.applied = None  # the bench uids the helper was last run with
		self._epoch = time.time()
		self.helper_failed = set()

	def _load(self):
		if not self.state_path or not os.path.exists(self.state_path):
			return {"users": {}, "tail": {}}
		try:
			with open(self.state_path) as f:
				data = json.load(f)
			if isinstance(data, dict) and isinstance(data.get("users"), dict):
				data.setdefault("tail", {})
				return data
		except (OSError, ValueError):
			pass
		return {"users": {}, "tail": {}}

	def _save(self):
		if not self.state_path:
			return
		tmp = self.state_path + ".tmp"
		try:
			fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
			with os.fdopen(fd, "w") as f:
				json.dump(self.state, f)
			os.replace(tmp, self.state_path)
		except OSError as e:
			log.warning("could not save the outbound record: %s", e)

	def subjects(self, benches, sockets=None):
		"""[(key, bench names, {destination: (ip, port, host)}, how)] for this scan, one per key."""
		merged, order = {}, []

		def add(key, names, conns, how):
			if key not in merged:
				merged[key] = (names, {}, how)
				order.append(key)
			for dest, value in conns.items():  # several containers of one bench: one subject
				merged[key][1].setdefault(dest, value if len(value) == 4 else (*value, how))

		users = bench_users(benches)
		host_sockets, host_inodes = read_table(self.proc_root) if sockets is None else (sockets, set())
		by_uid = outbound(host_sockets, set(users), self.include_private)
		for uid, names in sorted(users.items()):
			add(str(uid), names, by_uid.get(uid, {}), "host")
		filesystems = bench_filesystems(benches, self.self_mountinfo)
		owner_of = {}  # a container's addresses: who a proxy's client is
		for _cid, pid in sorted(containers(self.proc, self.cgroups).items(), key=lambda kv: kv[1]):
			name = container_bench(pid, filesystems, self.proc)
			if not name:
				continue
			net_dir = os.path.join(self.proc, str(pid), "net")
			table, inodes = read_table(net_dir)
			if inodes & host_inodes:
				continue  # a socket lives in one network: this container uses the host's, already read
			for address in local_addresses(net_dir):
				owner_of[address] = f"bench:{name}"
			conns = {}
			for found in outbound(table, None, self.include_private).values():
				conns.update(found)
			add(f"bench:{name}", [name], conns, "container")
		for key, conns in self._kernel(users, owner_of).items():
			if key in merged:  # a bench user, or a container already read: the kernel adds what /proc missed
				add(key, merged[key][0], conns, merged[key][2])
		host_names = sorted({n for key in order if merged[key][2] == "host" for n in merged[key][0]})
		host_addresses = local_addresses(self.proc_root) | {"127.0.0.1", "::1"}
		for key, conns in sorted(self._proxied(owner_of, host_addresses).items()):
			names = [key.split(":", 1)[1]] if key.startswith("bench:") else host_names
			if names:
				add(f"proxy:{key}", names, conns, "proxy")
		return [(key, *merged[key]) for key in order]

	def _kernel(self, users, owner_of):
		"""{subject: {destination: (ip, port, None, "kernel")}}: every new connection the helper
		logged since the last scan, of a bench user (by its uid) or a bench's container (by its
		address). The helper is (re)applied when the bench users change."""
		if self.turn_off:  # `kernel_log: false` with the helper installed: stop the host's logging
			try:
				self.run(["sudo", "-n", self.turn_off, "--off"], capture_output=True, text=True, timeout=15)
			except (OSError, subprocess.SubprocessError):
				pass
			self.turn_off = None
		if not self.helper:
			return {}
		uids = sorted(users)
		if uids != self.applied and tuple(uids) not in self.helper_failed:
			try:
				done = self.run(["sudo", "-n", self.helper, *map(str, uids)], capture_output=True, text=True, timeout=15)
				ok = done.returncode == 0
				why = (done.stderr or "").strip()[:200]
			except (OSError, subprocess.SubprocessError) as e:
				ok, why = False, str(e)
			if ok:
				self.applied = uids
				self.state.setdefault("kernel_since", self._epoch)  # its own learning period starts now
			else:
				self.helper_failed.add(tuple(uids))
				if self.applied is None:
					log.warning("outbound: %s did not run (%s); sampling /proc only", self.helper, why or "sudo refused")
				else:
					log.warning("outbound: %s did not run for the bench users %s (%s); the kernel log still covers %s",
					            self.helper, uids, why or "sudo refused", self.applied)  # fmt: skip
		if self.applied is None:
			return {}
		if self.kernel_source is None:
			cursor = os.path.join(os.path.dirname(self.state_path), "outbound-journal.cursor") if self.state_path else None
			self.kernel_source = (JournalTailer(("kernel",), cursor_file=cursor) if JournalTailer.available()
			                      else FileTailer(KERN_LOG, self.state["tail"]))  # fmt: skip
		try:
			lines = self.kernel_source.read_lines()
		except OSError:
			return {}
		out = {}
		for line in lines:
			got = parse_kernel(line)
			if not got:
				continue
			kind, src, dst, port, uid = got
			key = str(uid) if kind == "out" and uid in users else owner_of.get(src) if kind == "fwd" else None
			try:
				if key and public(dst, self.include_private):
					out.setdefault(key, {}).setdefault(destination(dst, port), (dst, port, None, "kernel"))
			except ValueError:
				continue
		return out

	def _proxied(self, owner_of, host_addresses):
		"""{subject: {host:port: (remote ip, port, host)}} read since the last scan from the proxy
		logs. A client is a bench's container, or the host itself (all its benches); any other
		client of a shared proxy (a LAN machine) is not a bench's and is left out."""
		out = {}
		for spec in self.proxy_logs:
			path, parse_line = spec["path"], PROXY_PARSERS[spec["format"]]
			if not os.path.isfile(path):
				folder = os.path.dirname(path)
				if os.path.isdir(folder) and not os.access(folder, os.R_OK | os.X_OK) and path not in self.unreadable:
					self.unreadable.add(path)
					log.warning("outbound: cannot read %s; add the agent's user to the proxy's group (proxy for Squid)", path)
				self.absent.add(path)
				continue
			if path not in self.tailers:  # a log that appeared after the agent started is read from its start
				self.tailers[path] = FileTailer(path, self.state["tail"], from_start=path in self.absent)
			try:
				lines = self.tailers[path].read_lines()
			except OSError:
				continue
			for line in lines:
				got = parse_line(line)
				if not got:
					continue
				client, name, port, remote = got
				if remote and not public(remote, self.include_private):
					continue
				subject = owner_of.get(client) or ("host" if client in host_addresses else None)
				if subject:
					out.setdefault(subject, {}).setdefault(f"{name}:{port}", (remote, port, name))
		return out

	def collect(self, benches, now=None, epoch=None, sockets=None):
		ts = utc_iso(now)
		epoch = (now.timestamp() if now else time.time()) if epoch is None else epoch
		self._epoch = epoch
		cutoff = epoch - FORGET_DAYS * 86400
		metrics, events, active = [], [], set()
		subjects = self.subjects(benches, sockets)
		since = self.state.get("kernel_since")
		# what only the kernel log sees (connections shorter than a sample) gets its own learning
		# period from when the helper was installed: not a burst of alerts on a host learned long ago
		kernel_learning = since is not None and epoch - float(since) < self.learn_seconds
		for key, names, conns, how in subjects:
			active.add(key)
			record = self.state["users"].setdefault(key, {"since": epoch, "seen": {}})
			record["last"] = epoch
			seen = record["seen"]
			since = record.get("since")
			learning = epoch - float(epoch if since is None else since) < self.learn_seconds
			bench = names[0] if len(names) == 1 else None
			if kernel_learning:
				for dest, value in conns.items():
					if value[3] == "kernel" and dest not in seen:
						seen[dest] = epoch
			new = sorted(d for d in conns if d not in seen)
			unusual = [d for d in new if conns[d][1] not in self.usual_ports]
			usual = [d for d in new if conns[d][1] in self.usual_ports]
			for dest in conns:
				if dest not in new or learning:
					seen[dest] = epoch
			report = [] if learning else (unusual + (usual if self.report_usual_ports else []))[:MAX_PER_SCAN]
			if not learning and not self.report_usual_ports:
				for dest in usual:  # counted, not reported: learned at once
					seen[dest] = epoch
			for dest in report:
				seen[dest] = epoch  # the rest stays new and comes out at the next scans
				ip, port, name, via = conns[dest]
				is_usual = port in self.usual_ports
				payload = {"remote_ip": ip, "remote_port": port, "destination": dest, "benches": names, "usual_port": is_usual,
				           "seen_by": via, "attack_techniques": ATTACK}  # fmt: skip
				if name:
					payload["remote_host"] = name
				payload = {k: v for k, v in payload.items() if v is not None}
				payload["note"] = {"host": "sampled every interval; the process is the bench's user, not one pid",
				                   "container": "sampled every interval in the bench's container",
				                   "proxy": "from the proxy's access log: every request through it",
				                   "kernel": "every new connection, from the kernel log (wolf-outbound-log)"}[via]  # fmt: skip
				events.append(event(
					"security", "bench_new_outbound", "info" if is_usual else "warning", ts, self.host,
					f"{', '.join(names)}: new outbound connection to {name or ip}:{port}"[:255],
					fingerprint(self.host, "bench_new_outbound", key, dest), payload, source="outbound", bench=bench,
				))  # fmt: skip
			metrics.append(metric("bench_outbound_destinations", len(conns), ts, self.host, bench, labels={"seen_by": how}))
			metrics.append(metric("bench_new_outbound_usual", 0 if learning else len(usual), ts, self.host, bench,
			                      labels={"seen_by": how}))  # fmt: skip
			kept = sorted(((d, t) for d, t in seen.items() if t >= cutoff), key=lambda kv: kv[1], reverse=True)
			record["seen"] = dict(kept[:MAX_SEEN])
		for key in [k for k, r in self.state["users"].items() if k not in active and float(r.get("last") or 0) < cutoff]:
			del self.state["users"][key]  # a bench user, container or proxy client gone for a month
		self._save()
		return metrics, events

	def read(self):
		return read_sockets(self.proc_root)

	def close(self):
		"""Release the proxy logs and the kernel log reader (a journalctl process)."""
		for tailer in list(self.tailers.values()) + [self.kernel_source]:
			if hasattr(tailer, "close"):
				tailer.close()
