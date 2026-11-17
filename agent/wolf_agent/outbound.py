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
import sys
import time

from .tailer import FileTailer
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


# --- benches in containers (Docker, Press, Podman): no root needed --------------------------

CGROUP_RE = re.compile(r"(?:docker-|/docker/|cri-containerd-|crio-|libpod-)([0-9a-f]{64})")


def containers(proc="/proc"):
	"""{container id: its lowest pid}, from /proc/<pid>/cgroup (readable by anyone)."""
	out = {}
	try:
		pids = [int(p) for p in os.listdir(proc) if p.isdigit()]
	except OSError:
		return out
	for pid in sorted(pids):
		try:
			with open(os.path.join(proc, str(pid), "cgroup")) as f:
				m = CGROUP_RE.search(f.read())
		except OSError:
			continue
		if m and m.group(1) not in out:
			out[m.group(1)] = pid
	return out


def _suffixes(path):
	"""The path and its tails of two components or more: a bind mount from a separate /home
	partition shows `/frappe/benches/b1/sites`, not `/home/frappe/benches/b1/sites`."""
	parts = [p for p in os.path.normpath(path).split(os.sep) if p]
	return ["/" + "/".join(parts[i:]) for i in range(len(parts) - 1)]


def container_bench(pid, benches, proc="/proc"):
	"""The bench a container belongs to: the one whose folder (or a folder in it) it mounts, from
	/proc/<pid>/mountinfo (readable by anyone), longest match first."""
	try:
		with open(os.path.join(proc, str(pid), "mountinfo")) as f:
			roots = [line.split()[3] for line in f if len(line.split()) > 4]
	except OSError:
		return None
	best = None
	for bench in benches:
		for suffix in _suffixes(bench.get("path") or ""):
			if any(r == suffix or r.startswith(suffix + "/") for r in roots):
				if best is None or len(suffix) > best[0]:
					best = (len(suffix), bench.get("name"))
				break
	return best[1] if best else None


# --- outbound proxies: the real destinations, from the proxy's access log -------------------

DEFAULT_PROXY_LOGS = [{"path": "/var/log/squid/access.log", "format": "squid"}]


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
	             report_usual_ports=False, proc="/proc", proxy_logs=None):  # fmt: skip
		self.host = host
		self.state_path = state_path
		self.learn_seconds = float(learn_days) * 86400
		self.include_private = include_private
		self.usual_ports = USUAL_PORTS | {int(p) for p in (usual_ports or [])}
		self.report_usual_ports = report_usual_ports
		self.proc_root = proc_root
		self.proc = proc
		self.proxy_logs = DEFAULT_PROXY_LOGS if proxy_logs is None else list(proxy_logs)
		self.state = self._load()
		self.tailers = {}

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
		"""[(key, bench names, {destination: (ip, port, host)}, how)] for this scan."""
		out = []
		users = bench_users(benches)
		host_sockets, host_inodes = read_table(self.proc_root) if sockets is None else (sockets, set())
		by_uid = outbound(host_sockets, set(users), self.include_private)
		for uid, names in sorted(users.items()):
			out.append((str(uid), names, by_uid.get(uid, {}), "host"))
		local_of = {}  # a container's addresses: who a proxy's client is
		for _cid, pid in sorted(containers(self.proc).items(), key=lambda kv: kv[1]):
			name = container_bench(pid, benches, self.proc)
			if not name:
				continue
			table, inodes = read_table(os.path.join(self.proc, str(pid), "net"))
			if inodes and inodes <= host_inodes:
				continue  # host networking: the host's own table already has it
			for _state, laddr, _lp, _r, _rp, _u in table:
				try:
					if not ipaddress.ip_address(laddr).is_loopback and not ipaddress.ip_address(laddr).is_unspecified:
						local_of[laddr] = f"bench:{name}"
				except ValueError:
					continue
			conns = {}
			for found in outbound(table, None, self.include_private).values():
				conns.update(found)
			out.append((f"bench:{name}", [name], conns, "container"))
		proxied = self._proxied(local_of)
		host_names = sorted({n for _k, names, _c, how in out if how == "host" for n in names})
		for key, conns in sorted(proxied.items()):
			names = [key.split(":", 1)[1]] if key.startswith("bench:") else host_names
			if names:
				out.append((f"proxy:{key}", names, conns, "proxy"))
		return out

	def _proxied(self, local_of):
		"""{subject: {host:port: (remote ip, port, host)}} read since the last scan from the proxy logs."""
		out = {}
		for spec in self.proxy_logs:
			path, parse_line = spec.get("path"), PROXY_PARSERS.get(spec.get("format") or "squid")
			if not path or not parse_line or not os.path.isfile(path):
				continue
			tailer = self.tailers.get(path) or self.tailers.setdefault(path, FileTailer(path, self.state["tail"]))
			try:
				lines = tailer.read_lines()
			except OSError:
				continue
			for line in lines:
				got = parse_line(line)
				if not got:
					continue
				client, name, port, remote = got
				if remote and not public(remote, self.include_private):
					continue
				subject = local_of.get(client, "host")
				out.setdefault(subject, {}).setdefault(f"{name}:{port}", (remote, port, name))
		return out

	def collect(self, benches, now=None, epoch=None, sockets=None):
		ts = utc_iso(now)
		epoch = (now.timestamp() if now else time.time()) if epoch is None else epoch
		cutoff = epoch - FORGET_DAYS * 86400
		metrics, events, active = [], [], set()
		for key, names, conns, how in self.subjects(benches, sockets):
			active.add(key)
			record = self.state["users"].setdefault(key, {"since": epoch, "seen": {}})
			record["last"] = epoch
			seen = record["seen"]
			since = record.get("since")
			learning = epoch - float(epoch if since is None else since) < self.learn_seconds
			bench = names[0] if len(names) == 1 else None
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
				ip, port, name = conns[dest]
				is_usual = port in self.usual_ports
				payload = {"remote_ip": ip, "remote_port": port, "destination": dest, "benches": names, "usual_port": is_usual,
				           "seen_by": how, "attack_techniques": ATTACK}  # fmt: skip
				if name:
					payload["remote_host"] = name
				payload = {k: v for k, v in payload.items() if v is not None}
				payload["note"] = {"host": "sampled every interval; the process is the bench's user, not one pid",
				                   "container": "sampled every interval in the bench's container",
				                   "proxy": "from the proxy's access log: every request through it"}[how]  # fmt: skip
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
