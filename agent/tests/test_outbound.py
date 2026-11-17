import ipaddress
import os
import sys
import tempfile
import unittest
from unittest import mock

from wolf_agent import outbound

HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
DAY = 86400


def v4(ip, port):
	return f"{int.from_bytes(ipaddress.IPv4Address(ip).packed, sys.byteorder):08X}:{port:04X}"


def v6(ip, port):
	raw = ipaddress.IPv6Address(ip).packed
	words = "".join(f"{int.from_bytes(raw[i:i + 4], sys.byteorder):08X}" for i in range(0, 16, 4))
	return f"{words}:{port:04X}"


def line(local, remote, state, uid, n=0):
	return f"{n:4d}: {local} {remote} {state} 00000000:00000000 00:00000000 00000000 {uid:5d}        0 {1000 + n} 1\n"


class TestOutbound(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.bench = os.path.join(self.tmp.name, "frappe-bench")
		os.makedirs(self.bench)
		if os.stat(self.bench).st_uid == 0:  # running as root (a container): a root-owned bench is skipped
			os.chown(self.bench, 4242, 4242)
		self.uid = os.stat(self.bench).st_uid
		self.benches = [{"name": "frappe-bench", "path": self.bench}]
		self.state = os.path.join(self.tmp.name, outbound.STATE_FILE)
		self.proc = os.path.join(self.tmp.name, "net")
		os.makedirs(self.proc)
		self.fake_proc = os.path.join(self.tmp.name, "proc")  # pids, for containers
		os.makedirs(self.fake_proc)
		self.proc_net()

	def tearDown(self):
		self.tmp.cleanup()

	def proc_net(self, v4_lines=(), v6_lines=()):
		with open(os.path.join(self.proc, "tcp"), "w") as f:
			f.write(HEADER + "".join(v4_lines))
		with open(os.path.join(self.proc, "tcp6"), "w") as f:
			f.write(HEADER + "".join(v6_lines))

	def watcher(self, **kw):
		kw.setdefault("proc", self.fake_proc)
		kw.setdefault("proxy_logs", [])
		return outbound.OutboundWatcher("bench-01", self.state, proc_root=self.proc, **kw)

	def conn(self, ip, port, n=0, uid=None):
		return line(v4("10.0.0.5", 50000 + n), v4(ip, port), "01", self.uid if uid is None else uid, n)

	def test_parse_roundtrip(self):
		(s,) = outbound.parse(HEADER + line(v4("10.0.0.5", 51234), v4("203.0.113.9", 443), "01", 1000))
		self.assertEqual(s, ("01", "10.0.0.5", 51234, "203.0.113.9", 443, 1000))
		(s6,) = outbound.parse(HEADER + line(v6("2001:db8::5", 40000), v6("2606:4700::6810:84e5", 443), "01", 1000), ipv6=True)
		self.assertEqual(s6[3:5], ("2606:4700::6810:84e5", 443))
		(mapped,) = outbound.parse(HEADER + line(v6("::ffff:10.0.0.5", 40000), v6("::ffff:185.199.110.66", 4444), "01", 1000),
		                           ipv6=True)  # fmt: skip
		self.assertEqual(mapped[3], "185.199.110.66", "a dual-stack socket's IPv4 peer is written as IPv4")

	def test_only_the_bench_users_client_connections_to_public_peers(self):
		self.proc_net([
			self.conn("45.33.32.9", 443, 2),  # kept
			line(v4("10.0.0.5", 8000), v4("45.33.32.10", 61000), "01", self.uid, 3),  # a visitor on gunicorn's port
			self.conn("10.0.0.7", 3306, 4),  # MariaDB on the LAN
			self.conn("45.33.32.11", 4444, 5, uid=self.uid + 1),  # another user
			line(v4("10.0.0.5", 51237), v4("45.33.32.12", 443), "06", self.uid, 6),  # TIME_WAIT
			line(v4("0.0.0.0", 8000), v4("0.0.0.0", 0), "0A", self.uid, 1),
		])  # fmt: skip
		got = outbound.outbound(outbound.read_sockets(self.proc), {self.uid})
		self.assertEqual(got, {self.uid: {"45.33.32.0/24:443": ("45.33.32.9", 443, None)}})
		with_lan = outbound.outbound(outbound.read_sockets(self.proc), {self.uid}, include_private=True)
		self.assertIn("10.0.0.0/24:3306", with_lan[self.uid])

	def test_learned_then_each_new_unusual_destination_once(self):
		w = self.watcher(learn_days=7)
		self.proc_net([self.conn("45.33.32.9", 4444)])
		self.assertEqual(w.collect(self.benches, epoch=0)[1], [])  # learning
		self.proc_net([self.conn("151.101.1.20", 8443)])
		self.assertEqual(w.collect(self.benches, epoch=3 * DAY)[1], [], "still learning: learned silently")
		self.proc_net([self.conn("45.33.32.77", 4444, 1),  # same /24 and port: known
		               self.conn("185.199.110.66", 4444, 2)])  # fmt: skip
		metrics, events = w.collect(self.benches, epoch=8 * DAY)
		(ev,) = events
		self.assertEqual((ev["category"], ev["severity"], ev["bench"]), ("bench_new_outbound", "warning", "frappe-bench"))
		p = ev["payload"]
		self.assertEqual((p["remote_ip"], p["remote_port"], p["usual_port"]), ("185.199.110.66", 4444, False))
		self.assertNotIn("ip", p, "the destination is not the remote party of an attack")
		self.assertEqual({m["metric_name"]: m["value"] for m in metrics}["bench_outbound_destinations"], 2)
		self.assertEqual(w.collect(self.benches, epoch=8 * DAY + 60)[1], [], "reported once")

	def test_usual_ports_are_counted_not_reported(self):
		w = self.watcher(learn_days=0)
		w.collect(self.benches, epoch=0)
		self.proc_net([self.conn("185.199.111.5", 587, 1), self.conn("140.82.121.4", 22, 2), self.conn("52.217.1.1", 443, 3)])
		metrics, events = w.collect(self.benches, epoch=60)
		self.assertEqual(events, [])
		self.assertEqual({m["metric_name"]: m["value"] for m in metrics}["bench_new_outbound_usual"], 3)
		self.assertEqual({m["metric_name"]: m["value"] for m in w.collect(self.benches, epoch=120)[0]}["bench_new_outbound_usual"], 0)
		# reported at info when asked, and a port of the operator's own is usual
		w2 = outbound.OutboundWatcher("bench-01", None, learn_days=0, proc_root=self.proc, usual_ports=[5432],
		                              report_usual_ports=True, proc=self.fake_proc, proxy_logs=[])  # fmt: skip
		w2.collect(self.benches, epoch=0, sockets=[])
		self.proc_net([self.conn("185.199.111.5", 587, 1), self.conn("35.180.1.1", 5432, 2)])
		self.assertEqual(sorted(e["severity"] for e in w2.collect(self.benches, epoch=60)[1]), ["info", "info"])

	def test_the_record_survives_a_restart(self):
		self.watcher(learn_days=0).collect(self.benches, epoch=0)
		self.proc_net([self.conn("185.199.110.66", 4444)])
		(ev,) = self.watcher(learn_days=0).collect(self.benches, epoch=60)[1]  # a new watcher, the same file
		self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o600)
		self.assertEqual(self.watcher(learn_days=0).collect(self.benches, epoch=120)[1], [])
		with open(self.state, "w") as f:
			f.write("{not json")
		self.assertEqual(self.watcher(learn_days=7).collect(self.benches, epoch=180)[1], [], "a corrupt record learns again")

	def test_a_burst_is_bounded_and_the_rest_comes_out_later(self):
		w = self.watcher(learn_days=0)
		w.collect(self.benches, epoch=0)
		self.proc_net([self.conn(f"185.{i}.1.1", 4444, i) for i in range(30)])
		first = w.collect(self.benches, epoch=60)[1]
		second = w.collect(self.benches, epoch=120)[1]
		self.assertEqual((len(first), len(second)), (outbound.MAX_PER_SCAN, 10))
		self.assertEqual(len({e["payload"]["remote_ip"] for e in first + second}), 30)
		self.assertEqual(w.collect(self.benches, epoch=180)[1], [])

	def test_forgotten_while_learning_and_users_gone(self):
		w = self.watcher(learn_days=365)
		self.proc_net([self.conn("185.199.110.66", 4444)])
		w.collect(self.benches, epoch=0)
		self.proc_net()
		w.collect(self.benches, epoch=(outbound.FORGET_DAYS + 1) * DAY)
		self.assertEqual(w.state["users"][str(self.uid)]["seen"], {}, "pruned during the learning period too")
		w.collect([], epoch=(2 * outbound.FORGET_DAYS + 2) * DAY)
		self.assertEqual(w.state["users"], {}, "a bench user gone for a month is dropped")

	def test_a_bench_owned_by_root_is_skipped(self):
		with mock.patch("os.stat", return_value=mock.Mock(st_uid=0)):
			self.assertEqual(outbound.bench_users(self.benches), {})

	def test_benches_sharing_a_user(self):
		other = os.path.join(self.tmp.name, "other-bench")
		os.makedirs(other)
		if os.stat(other).st_uid != self.uid:
			os.chown(other, self.uid, self.uid)
		w = self.watcher(learn_days=0)
		benches = self.benches + [{"name": "other-bench", "path": other}]
		w.collect(benches, epoch=0)
		self.proc_net([self.conn("185.199.110.66", 4444)])
		(ev,) = w.collect(benches, epoch=60)[1]
		self.assertEqual((ev["bench"], ev["payload"]["benches"]), (None, ["frappe-bench", "other-bench"]))


	def container(self, pid, mounted, v4_lines=(), cid="c" * 64):
		"""A container process in the fake /proc: its cgroup, a bind mount, and its own TCP table."""
		base = os.path.join(self.fake_proc, str(pid))
		os.makedirs(os.path.join(base, "net"))
		with open(os.path.join(base, "cgroup"), "w") as f:
			f.write(f"0::/system.slice/docker-{cid}.scope\n")
		with open(os.path.join(base, "mountinfo"), "w") as f:
			f.write(f"3017 3005 259:2 {mounted} /home/frappe/frappe-bench/sites rw,relatime - ext4 /dev/nvme0n1p2 rw\n")
		with open(os.path.join(base, "net", "tcp"), "w") as f:
			f.write(HEADER + "".join(v4_lines))
		with open(os.path.join(base, "net", "tcp6"), "w") as f:
			f.write(HEADER)

	def test_a_bench_in_a_container(self):
		# a Press bench: the container mounts the bench's sites/ from the host, and has its own network
		self.container(4242, self.bench + "/sites", [line(v4("172.18.0.5", 41000), v4("185.199.110.66", 4444), "01", 1000, 7)])
		self.container(4300, "/srv/unrelated/data", [line(v4("172.18.0.9", 41000), v4("185.199.110.67", 4444), "01", 1000, 8)],
		               cid="d" * 64)  # not a bench: left alone
		w = self.watcher(learn_days=0)  # no learning period: the first scan reports
		(ev,) = w.collect(self.benches, epoch=0, sockets=[])[1]
		self.assertEqual((ev["bench"], ev["payload"]["remote_ip"], ev["payload"]["seen_by"]), ("frappe-bench", "185.199.110.66", "container"))
		self.assertEqual(w.collect(self.benches, epoch=60, sockets=[])[1], [])

	def test_a_container_on_the_host_network_is_not_counted_twice(self):
		conn = line(v4("10.0.0.5", 41000), v4("185.199.110.66", 4444), "01", self.uid, 7)
		self.proc_net([conn])
		self.container(4242, self.bench + "/sites", [conn])  # the same sockets, the same inodes
		w = self.watcher(learn_days=0)
		w.collect(self.benches, epoch=0)
		events = w.collect(self.benches, epoch=60)[1]
		self.assertEqual([e["payload"]["seen_by"] for e in events], [], "already learned through the host's table")
		self.assertEqual([k for k in w.state["users"]], [str(self.uid)])

	def test_a_separate_home_partition_still_matches(self):
		parts = self.bench.strip("/").split("/")
		on_partition = "/" + "/".join(parts[1:]) + "/sites"  # the path inside its own filesystem
		self.container(4242, on_partition)
		self.assertEqual(outbound.container_bench(4242, self.benches, self.fake_proc), "frappe-bench")
		self.assertIsNone(outbound.container_bench(4242, [{"name": "x", "path": "/elsewhere/other"}], self.fake_proc))

	def test_destinations_behind_a_proxy(self):
		self.assertEqual(outbound.parse_squid("1700000000.1 120 172.18.0.5 TCP_TUNNEL/200 3800 CONNECT api.Stripe.com:443 - HIER_DIRECT/52.1.2.3 -"),
		                 ("172.18.0.5", "api.stripe.com", 443, "52.1.2.3"))  # fmt: skip
		self.assertEqual(outbound.parse_squid("1700000000.1 5 10.0.0.5 TCP_MISS/200 512 GET http://evil.example:8081/x - HIER_DIRECT/185.199.110.9 text/plain"),
		                 ("10.0.0.5", "evil.example", 8081, "185.199.110.9"))  # fmt: skip
		self.assertIsNone(outbound.parse_squid("garbage"))
		log_path = os.path.join(self.tmp.name, "access.log")
		with open(log_path, "w") as f:
			f.write("")
		self.container(4242, self.bench + "/sites", [line(v4("172.18.0.5", 41000), v4("10.0.0.2", 3128), "01", 1000, 7)])
		w = self.watcher(learn_days=0, proxy_logs=[{"path": log_path, "format": "squid"}])
		w.collect(self.benches, epoch=0, sockets=[])
		with open(log_path, "a") as f:
			f.write("1700000000.1 120 172.18.0.5 TCP_TUNNEL/200 3800 CONNECT c2.evil.example:8443 - HIER_DIRECT/185.199.110.9 -\n")
			f.write("1700000000.2 120 10.0.0.5 TCP_TUNNEL/200 3800 CONNECT pastebin.example:4443 - HIER_DIRECT/185.199.110.10 -\n")
		events = w.collect(self.benches, epoch=60, sockets=[])[1]
		got = sorted((e["bench"], e["payload"]["remote_host"], e["payload"]["seen_by"]) for e in events)
		# the first proxy line of a subject starts its learning (0 days here): both are new
		self.assertEqual(got, [("frappe-bench", "c2.evil.example", "proxy"), ("frappe-bench", "pastebin.example", "proxy")])
		self.assertEqual(w.collect(self.benches, epoch=120, sockets=[])[1], [], "the log is read from where it stopped")


if __name__ == "__main__":
	unittest.main()
