"""Outbound connections of bench processes to destinations never seen for them (#72 step 7).

A light hint of command-and-control or exfiltration for a bench without Suricata, not packet
inspection. Every `outbound.interval` (60 s) the agent reads `/proc/net/tcp` and `/proc/net/tcp6`
(no root needed, no external tool) and keeps the established connections that:

- belong to a bench's user (the owner of the bench folder): `/proc/net/tcp` names each socket's
  uid, while which process holds it would need root. Benches sharing one user share one record;
- leave from a local port nothing listens on: the bench is the client, not answering a visitor;
- go to a public address: private, loopback and link-local peers (MariaDB, Redis, a LAN API)
  are left out unless `outbound.include_private`.

A destination is the remote network (/24 for IPv4, /48 for IPv6) and port. For `learn_days`
(7) after the agent first sees a bench's user, every destination is learned silently; after that,
each new one is reported once as `bench_new_outbound`: info on the usual ports (web, mail, DNS,
NTP), warning on any other. A destination unseen for FORGET_DAYS is forgotten. The record is kept
in the spool directory (`outbound-state.json`, 0600).

A snapshot every interval misses a connection that opened and closed in between: this samples,
it does not record every connection.
"""

import ipaddress
import json
import logging
import os
import time

from .util import event, fingerprint, metric, utc_iso

log = logging.getLogger(__name__)

STATE_FILE = "outbound-state.json"
ESTABLISHED, LISTEN = "01", "0A"
FORGET_DAYS = 30
MAX_PER_SCAN = 20  # events per scan: a burst of new destinations is one alert, not hundreds
MAX_SEEN = 5000  # destinations kept per user
USUAL_PORTS = {80, 443, 25, 465, 587, 993, 995, 53, 123, 853}
ATTACK = ["T1071", "T1041"]


def _ipv4(hexaddr):
	return str(ipaddress.IPv4Address(int(hexaddr, 16).to_bytes(4, "little")))


def _ipv6(hexaddr):
	raw = b"".join(int(hexaddr[i : i + 8], 16).to_bytes(4, "little") for i in range(0, 32, 8))
	return str(ipaddress.IPv6Address(raw))


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


def read_sockets(proc_root="/proc/net"):
	sockets = []
	for name, ipv6 in (("tcp", False), ("tcp6", True)):
		try:
			with open(os.path.join(proc_root, name)) as f:
				sockets += parse(f.read(), ipv6)
		except OSError:
			continue
	return sockets


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
	"""{uid: {destination: (remote ip, remote port)}} of the bench users' client connections."""
	listening = {lport for state, _l, lport, _r, _rp, _u in sockets if state == LISTEN}
	out = {}
	for state, _laddr, lport, raddr, rport, uid in sockets:
		if state != ESTABLISHED or uid not in uids or lport in listening:
			continue
		try:
			if not public(raddr, include_private):
				continue
			out.setdefault(uid, {}).setdefault(destination(raddr, rport), (raddr, rport))
		except ValueError:
			continue
	return out


def bench_users(benches):
	"""{uid: [bench names]}: the owner of each bench folder."""
	users = {}
	for bench in benches:
		try:
			uid = os.stat(bench.get("path") or "").st_uid
		except OSError:
			continue
		users.setdefault(uid, []).append(bench.get("name"))
	return users


class OutboundWatcher:
	def __init__(self, host, state_path=None, learn_days=7, include_private=False, proc_root="/proc/net"):
		self.host = host
		self.state_path = state_path
		self.learn_seconds = float(learn_days) * 86400
		self.include_private = include_private
		self.proc_root = proc_root
		self.state = self._load()

	def _load(self):
		if not self.state_path or not os.path.exists(self.state_path):
			return {"users": {}}
		try:
			with open(self.state_path) as f:
				data = json.load(f)
			return data if isinstance(data, dict) and isinstance(data.get("users"), dict) else {"users": {}}
		except (OSError, ValueError):
			return {"users": {}}

	def _save(self):
		if not self.state_path:
			return
		tmp = self.state_path + ".tmp"
		try:
			fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
			with os.fdopen(fd, "w") as f:
				json.dump(self.state, f)
			os.replace(tmp, self.state_path)
		except OSError:
			log.exception("could not save the outbound record")

	def collect(self, benches, now=None, epoch=None, sockets=None):
		ts = utc_iso(now)
		epoch = (now.timestamp() if now else time.time()) if epoch is None else epoch
		users = bench_users(benches)
		current = outbound(self.read() if sockets is None else sockets, set(users), self.include_private)
		metrics, events = [], []
		for uid, names in sorted(users.items()):
			record = self.state["users"].setdefault(str(uid), {"since": epoch, "seen": {}})
			seen = record["seen"]
			since = record.get("since")
			learning = epoch - float(epoch if since is None else since) < self.learn_seconds
			bench = names[0] if len(names) == 1 else None
			conns = current.get(uid, {})
			metrics.append(metric("bench_outbound_destinations", len(conns), ts, self.host, bench))
			new = sorted(d for d in conns if d not in seen)
			for dest in conns:
				seen[dest] = epoch
			if learning:
				continue
			for dest in new[:MAX_PER_SCAN]:
				ip, port = conns[dest]
				usual = port in USUAL_PORTS
				events.append(event(
					"security", "bench_new_outbound", "info" if usual else "warning", ts, self.host,
					f"{', '.join(names)}: new outbound connection to {ip}:{port}"[:255],
					fingerprint(self.host, "bench_new_outbound", uid, dest),
					{"ip": ip, "port": port, "destination": dest, "benches": names, "usual_port": usual,
					 "attack_techniques": ATTACK, "note": "sampled every interval; the process is the bench's user, not one pid"},
					source="outbound", bench=bench,
				))  # fmt: skip
			if len(new) > MAX_PER_SCAN:
				log.warning("outbound: %d new destinations for %s, %d reported", len(new), names, MAX_PER_SCAN)
			cutoff = epoch - FORGET_DAYS * 86400
			kept = sorted(((d, t) for d, t in seen.items() if t >= cutoff), key=lambda kv: kv[1], reverse=True)
			record["seen"] = dict(kept[:MAX_SEEN])
		self._save()
		return metrics, events

	def read(self):
		return read_sockets(self.proc_root)
