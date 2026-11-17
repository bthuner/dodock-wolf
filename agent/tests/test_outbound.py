import ipaddress
import json
import os
import tempfile
import unittest

from wolf_agent import outbound

HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
DAY = 86400


def v4(ip, port):
	return f"{int.from_bytes(ipaddress.IPv4Address(ip).packed, 'little'):08X}:{port:04X}"


def v6(ip, port):
	raw = ipaddress.IPv6Address(ip).packed
	words = "".join(f"{int.from_bytes(raw[i:i + 4], 'little'):08X}" for i in range(0, 16, 4))
	return f"{words}:{port:04X}"


def line(local, remote, state, uid, n=0):
	return f"{n:4d}: {local} {remote} {state} 00000000:00000000 00:00000000 00000000 {uid:5d}        0 {1000 + n} 1\n"


class TestOutbound(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.bench = os.path.join(self.tmp.name, "frappe-bench")
		os.makedirs(self.bench)
		self.uid = os.stat(self.bench).st_uid
		self.benches = [{"name": "frappe-bench", "path": self.bench}]
		self.state = os.path.join(self.tmp.name, outbound.STATE_FILE)
		self.proc = os.path.join(self.tmp.name, "net")
		os.makedirs(self.proc)

	def tearDown(self):
		self.tmp.cleanup()

	def proc_net(self, v4_lines=(), v6_lines=()):
		with open(os.path.join(self.proc, "tcp"), "w") as f:
			f.write(HEADER + "".join(v4_lines))
		with open(os.path.join(self.proc, "tcp6"), "w") as f:
			f.write(HEADER + "".join(v6_lines))

	def watcher(self, **kw):
		return outbound.OutboundWatcher("bench-01", self.state, proc_root=self.proc, **kw)

	def test_parse_roundtrip(self):
		(s,) = outbound.parse(HEADER + line(v4("10.0.0.5", 51234), v4("203.0.113.9", 443), "01", 1000))
		self.assertEqual(s, ("01", "10.0.0.5", 51234, "203.0.113.9", 443, 1000))
		(s6,) = outbound.parse(HEADER + line(v6("2001:db8::5", 40000), v6("2606:4700::6810:84e5", 443), "01", 1000), ipv6=True)
		self.assertEqual(s6[3:5], ("2606:4700::6810:84e5", 443))

	def test_only_the_bench_users_client_connections_to_public_peers(self):
		listen = line(v4("0.0.0.0", 8000), v4("0.0.0.0", 0), "0A", self.uid, 1)
		self.proc_net([
			line(v4("10.0.0.5", 51234), v4("45.33.32.9", 443), "01", self.uid, 2),  # kept
			line(v4("10.0.0.5", 8000), v4("45.33.32.10", 61000), "01", self.uid, 3),  # a visitor on gunicorn's port
			line(v4("10.0.0.5", 51235), v4("10.0.0.7", 3306), "01", self.uid, 4),  # MariaDB on the LAN
			line(v4("10.0.0.5", 51236), v4("45.33.32.11", 4444), "01", self.uid + 1, 5),  # another user
			line(v4("10.0.0.5", 51237), v4("45.33.32.12", 443), "06", self.uid, 6),  # TIME_WAIT
			listen,
		])  # fmt: skip
		got = outbound.outbound(outbound.read_sockets(self.proc), {self.uid})
		self.assertEqual(got, {self.uid: {"45.33.32.0/24:443": ("45.33.32.9", 443)}})
		with_lan = outbound.outbound(outbound.read_sockets(self.proc), {self.uid}, include_private=True)
		self.assertIn("10.0.0.0/24:3306", with_lan[self.uid])

	def test_learned_then_each_new_destination_once(self):
		w = self.watcher(learn_days=7)
		self.proc_net([line(v4("10.0.0.5", 51234), v4("45.33.32.9", 443), "01", self.uid)])
		self.assertEqual(w.collect(self.benches, epoch=0)[1], [])  # learning
		self.proc_net([line(v4("10.0.0.5", 51234), v4("151.101.1.20", 443), "01", self.uid)])
		self.assertEqual(w.collect(self.benches, epoch=3 * DAY)[1], [], "still learning: learned silently")
		self.proc_net([line(v4("10.0.0.5", 51234), v4("45.33.32.77", 443), "01", self.uid, 1),  # same /24 and port: known
		               line(v4("10.0.0.5", 51235), v4("185.199.110.66", 4444), "01", self.uid, 2)])  # fmt: skip
		metrics, events = w.collect(self.benches, epoch=8 * DAY)
		(ev,) = events
		self.assertEqual((ev["category"], ev["severity"], ev["bench"]), ("bench_new_outbound", "warning", "frappe-bench"))
		self.assertEqual((ev["payload"]["ip"], ev["payload"]["port"], ev["payload"]["usual_port"]), ("185.199.110.66", 4444, False))
		self.assertEqual(metrics[0]["value"], 2)
		self.assertEqual(w.collect(self.benches, epoch=8 * DAY + 60)[1], [], "reported once")

	def test_usual_ports_are_info_and_the_record_survives_a_restart(self):
		self.watcher(learn_days=0).collect(self.benches, epoch=0)
		self.proc_net([line(v4("10.0.0.5", 51234), v4("185.199.111.5", 587), "01", self.uid)])
		(ev,) = self.watcher(learn_days=0).collect(self.benches, epoch=60)[1]  # a new watcher, the same file
		self.assertEqual(ev["severity"], "info")
		self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o600)
		self.assertEqual(self.watcher(learn_days=0).collect(self.benches, epoch=120)[1], [])

	def test_bounded_and_forgotten(self):
		w = self.watcher(learn_days=0)
		w.collect(self.benches, epoch=0)
		self.proc_net([line(v4("10.0.0.5", 50000 + i), v4(f"185.{i}.1.1", 443), "01", self.uid, i) for i in range(30)])
		events = w.collect(self.benches, epoch=60)[1]
		self.assertEqual(len(events), outbound.MAX_PER_SCAN, "a burst is bounded")
		self.proc_net()
		w.collect(self.benches, epoch=60 + (outbound.FORGET_DAYS + 1) * DAY)
		with open(self.state) as f:
			self.assertEqual(json.load(f)["users"][str(self.uid)]["seen"], {}, "unseen for 30 days: forgotten")


if __name__ == "__main__":
	unittest.main()
