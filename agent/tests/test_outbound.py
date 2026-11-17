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
		kw.setdefault("kernel_log", False)
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
		                              report_usual_ports=True, proc=self.fake_proc, proxy_logs=[], kernel_log=False)  # fmt: skip
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


	def self_mounts(self, mount_point="/"):
		"""The agent's own mountinfo: the bench's filesystem mounted at `mount_point`."""
		path = os.path.join(self.tmp.name, "self-mountinfo")
		with open(path, "w") as f:
			f.write(f"25 1 {self.dev} / {mount_point} rw,relatime - ext4 /dev/nvme0n1p2 rw\n")
		return path

	def container(self, pid, root, v4_lines=(), cid="c" * 64, address="172.18.0.5", dev=None):
		"""A container process in the fake /proc: its cgroup, a bind mount (`root` inside the
		filesystem `dev`), its own TCP table and address."""
		base = os.path.join(self.fake_proc, str(pid))
		os.makedirs(os.path.join(base, "net"))
		with open(os.path.join(base, "cgroup"), "w") as f:
			f.write(f"0::/system.slice/docker-{cid}.scope\n")
		with open(os.path.join(base, "mountinfo"), "w") as f:
			f.write(f"3017 3005 {dev or self.dev} {root} /home/frappe/frappe-bench/sites rw,relatime - ext4 /dev/x rw\n")
		with open(os.path.join(base, "net", "tcp"), "w") as f:
			f.write(HEADER + "".join(v4_lines))
		with open(os.path.join(base, "net", "tcp6"), "w") as f:
			f.write(HEADER)
		with open(os.path.join(base, "net", "fib_trie"), "w") as f:
			f.write(f"Local:\n  +-- 0.0.0.0/0 3 0 5\n     |-- {address}\n        /32 host LOCAL\n     |-- 127.0.0.1\n        /32 host LOCAL\n")

	@property
	def dev(self):
		st = os.stat(self.bench)
		return f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"

	def cwatcher(self, **kw):
		kw.setdefault("self_mountinfo", self.self_mounts())
		return self.watcher(**kw)

	def test_a_bench_in_a_container(self):
		# a Press bench: the container mounts the bench's sites/ from the host, and has its own network
		self.container(4242, self.bench + "/sites", [line(v4("172.18.0.5", 41000), v4("185.199.110.66", 4444), "01", 1000, 7)])
		self.container(4300, "/srv/unrelated/data", [line(v4("172.18.0.9", 41000), v4("185.199.110.67", 4444), "01", 1000, 8)],
		               cid="d" * 64)  # not a bench: left alone
		w = self.cwatcher(learn_days=0)  # no learning period: the first scan reports
		(ev,) = w.collect(self.benches, epoch=0, sockets=[])[1]
		self.assertEqual((ev["bench"], ev["payload"]["remote_ip"], ev["payload"]["seen_by"]), ("frappe-bench", "185.199.110.66", "container"))
		self.assertEqual(w.collect(self.benches, epoch=60, sockets=[])[1], [])

	def test_same_path_on_another_filesystem_is_not_the_bench(self):
		self.container(4242, self.bench + "/sites", dev="7:42")  # a crafted mount elsewhere
		self.assertIsNone(outbound.container_bench(4242, outbound.bench_filesystems(self.benches, self.self_mounts()), self.fake_proc))

	def test_a_separate_partition_matches_by_its_own_path(self):
		top = "/" + self.bench.strip("/").split("/")[0]  # the bench's filesystem mounted there, like /home
		filesystems = outbound.bench_filesystems(self.benches, self.self_mounts(top))
		self.container(4242, self.bench[len(top):] + "/sites")
		self.assertEqual(outbound.container_bench(4242, filesystems, self.fake_proc), "frappe-bench")

	def test_a_container_on_the_host_network_is_not_counted_twice(self):
		mine = line(v4("10.0.0.5", 41000), v4("185.199.110.66", 4444), "01", self.uid, 7)
		self.proc_net([mine])
		# read a moment later: a socket opened meanwhile, but one shared socket says it is the same network
		self.container(4242, self.bench + "/sites", [mine, line(v4("10.0.0.5", 41001), v4("185.199.110.70", 4444), "01", 0, 9)])
		w = self.cwatcher(learn_days=0)
		w.collect(self.benches, epoch=0)
		self.assertEqual(list(w.state["users"]), [str(self.uid)])

	def test_two_containers_of_one_bench_are_one_subject(self):
		self.container(4242, self.bench + "/sites", [line(v4("172.18.0.5", 41000), v4("185.199.110.66", 4444), "01", 1000, 7)])
		self.container(4243, self.bench + "/sites", [line(v4("172.18.0.6", 41000), v4("185.199.110.88", 5555), "01", 1000, 8)],
		               cid="e" * 64, address="172.18.0.6")  # fmt: skip
		metrics, events = self.cwatcher(learn_days=0).collect(self.benches, epoch=0, sockets=[])
		self.assertEqual(len(events), 2)
		counts = [m["value"] for m in metrics if m["metric_name"] == "bench_outbound_destinations"
		          and m["labels"] == {"seen_by": "container"}]  # fmt: skip
		self.assertEqual(counts, [2], "one series for the bench's containers, both in it")

	def test_container_ids_from_every_layout(self):
		h = "a" * 64
		for text in (f"0::/system.slice/docker-{h}.scope", f"12:pids:/docker/{h}", f"0::/kubepods/besteffort/pod1/{h}",
		             f"0::/default/{h}", f"0::/machine.slice/libpod-{h}.scope"):  # fmt: skip
			self.assertEqual(outbound.container_id(text + "\n"), h, text)
		self.assertIsNone(outbound.container_id("0::/user.slice/user-1000.slice/session-3.scope\n"))

	def test_destinations_behind_a_proxy(self):
		self.assertEqual(outbound.parse_squid("1700000000.1 120 172.18.0.5 TCP_TUNNEL/200 3800 CONNECT api.Stripe.com:443 - HIER_DIRECT/52.1.2.3 -"),
		                 ("172.18.0.5", "api.stripe.com", 443, "52.1.2.3"))  # fmt: skip
		self.assertEqual(outbound.parse_squid("1700000000.1 5 10.0.0.5 TCP_MISS/200 512 GET http://evil.example:8081/x - HIER_DIRECT/185.199.110.9 text/plain"),
		                 ("10.0.0.5", "evil.example", 8081, "185.199.110.9"))  # fmt: skip
		self.assertIsNone(outbound.parse_squid("garbage"))
		log_path = os.path.join(self.tmp.name, "access.log")
		self.container(4242, self.bench + "/sites")
		w = self.cwatcher(learn_days=0, proxy_logs=[log_path])  # a plain path is a Squid log
		w.collect(self.benches, epoch=0, sockets=[])  # the log does not exist yet
		with open(log_path, "w") as f:  # created later: read from its start
			f.write("1700000000.1 120 172.18.0.5 TCP_TUNNEL/200 3800 CONNECT c2.evil.example:8443 - HIER_DIRECT/185.199.110.9 -\n")
			f.write("1700000000.2 120 127.0.0.1 TCP_TUNNEL/200 3800 CONNECT pastebin.example:4443 - HIER_DIRECT/185.199.110.10 -\n")
			f.write("1700000000.3 120 192.168.1.50 TCP_TUNNEL/200 3800 CONNECT lan-laptop.example:4443 - HIER_DIRECT/185.199.110.11 -\n")
		events = w.collect(self.benches, epoch=60, sockets=[])[1]
		got = sorted((e["payload"]["remote_host"], e["payload"]["seen_by"], tuple(e["payload"]["benches"])) for e in events)
		# the container's request is its bench's; the host's own is its benches'; a LAN client of a shared proxy is not a bench's
		self.assertEqual(got, [("c2.evil.example", "proxy", ("frappe-bench",)), ("pastebin.example", "proxy", ("frappe-bench",))])
		self.assertEqual(w.collect(self.benches, epoch=120, sockets=[])[1], [], "the log is read from where it stopped")
		w.close()

	def test_a_bad_proxy_entry_does_not_stop_detection(self):
		self.assertEqual(outbound.proxy_specs(["/var/log/squid/access.log", {"path": "/x", "format": "nginx"}, 42]),
		                 [{"path": "/var/log/squid/access.log", "format": "squid"}])  # fmt: skip
		w = self.cwatcher(learn_days=0, proxy_logs=[42])
		self.proc_net([self.conn("185.199.110.66", 4444)])
		self.assertEqual(len(w.collect(self.benches, epoch=0)[1]), 1)

	# --- every new connection, from the kernel log (wolf-outbound-log) ---

	OUT = ("2026-11-17T23:59:01+0100 web-01 kernel: wolf-out: IN= OUT=eth0 SRC=10.0.0.5 DST={dst} LEN=60 TOS=0x00 "
	       "PREC=0x00 TTL=64 ID=4242 DF PROTO=TCP SPT=51234 DPT={port} WINDOW=64240 RES=0x00 SYN URGP=0 UID={uid} GID={uid}")
	FWD = ("Nov 17 23:59:02 web-01 kernel: [12345.678] wolf-fwd: IN=br-1a2b OUT=eth0 MAC=02:42:ac:12:00:05 SRC={src} "
	       "DST={dst} LEN=60 TTL=63 ID=1 DF PROTO=TCP SPT=40000 DPT={port} WINDOW=64240 RES=0x00 SYN URGP=0")

	def test_parse_kernel(self):
		self.assertEqual(outbound.parse_kernel(self.OUT.format(dst="185.199.110.66", port=4444, uid=1000)),
		                 ("out", "10.0.0.5", "185.199.110.66", 4444, 1000))  # fmt: skip
		self.assertEqual(outbound.parse_kernel(self.FWD.format(src="172.18.0.5", dst="2606:4700::1111", port=8443)),
		                 ("fwd", "172.18.0.5", "2606:4700::1111", 8443, None))  # fmt: skip
		self.assertIsNone(outbound.parse_kernel("kernel: [  1.0] usb 1-1: new device"))
		self.assertIsNone(outbound.parse_kernel("kernel: wolf-out: IN= OUT=eth0 SRC=10.0.0.5 DST=1.1.1.1 PROTO=ICMP TYPE=8"))

	class Source:
		def __init__(self):
			self.lines = []

		def read_lines(self):
			lines, self.lines = self.lines, []
			return lines

	def kwatcher(self, returncode=0):
		helper = os.path.join(self.tmp.name, "wolf-outbound-log")
		with open(helper, "w") as f:
			f.write("#!/bin/sh\n")
		self.calls, self.source = [], self.Source()

		def run(cmd, **kw):
			self.calls.append(cmd)
			return mock.Mock(returncode=returncode, stderr="sudo: a password is required" if returncode else "")

		return self.cwatcher(learn_days=0, kernel_log="auto", helper=helper, kernel_source=self.source, run=run)

	def test_every_new_connection_from_the_kernel_log(self):
		self.container(4242, self.bench + "/sites")
		w = self.kwatcher()
		w.collect(self.benches, epoch=0, sockets=[])
		self.assertEqual(self.calls, [["sudo", "-n", w.helper, str(self.uid)]], "applied with the bench users")
		self.source.lines = [
			self.OUT.format(dst="185.199.110.66", port=4444, uid=self.uid),  # closed long before the next sample
			self.OUT.format(dst="185.199.110.67", port=4444, uid=self.uid + 7),  # not a bench user
			self.FWD.format(src="172.18.0.5", dst="185.199.110.68", port=5555),  # the bench's container
			self.FWD.format(src="172.18.0.99", dst="185.199.110.69", port=5555),  # another container
		]
		events = w.collect(self.benches, epoch=60, sockets=[])[1]
		got = sorted((e["payload"]["remote_ip"], e["payload"]["seen_by"], e["bench"]) for e in events)
		self.assertEqual(got, [("185.199.110.66", "kernel", "frappe-bench"), ("185.199.110.68", "kernel", "frappe-bench")])
		w.collect(self.benches, epoch=120, sockets=[])
		self.assertEqual(len(self.calls), 1, "applied again only when the bench users change")

	def test_without_sudo_it_samples_proc_and_says_so_once(self):
		w = self.kwatcher(returncode=1)
		with self.assertLogs("wolf_agent.outbound", "WARNING") as logs:
			w.collect(self.benches, epoch=0, sockets=[])
		self.assertIn("sampling /proc only", logs.output[0])
		w.collect(self.benches, epoch=60, sockets=[])
		self.assertEqual(len(self.calls), 1, "not retried every minute")
		self.assertIsNone(outbound.OutboundWatcher("h", None, helper="/nonexistent/wolf-outbound-log").helper)


	def test_installed_after_learning_kernel_only_destinations_learn_first(self):
		w = self.kwatcher()
		w.learn_seconds = 7 * DAY
		w.state["users"][str(self.uid)] = {"since": 0, "seen": {}}  # learned long ago, from /proc
		w.collect(self.benches, epoch=30 * DAY, sockets=[])  # the helper is applied now
		self.source.lines = [self.OUT.format(dst="185.199.110.66", port=4444, uid=self.uid)]
		self.assertEqual(w.collect(self.benches, epoch=31 * DAY, sockets=[])[1], [], "its own learning week")
		self.source.lines = [self.OUT.format(dst="151.101.1.99", port=4444, uid=self.uid)]  # another network
		self.assertEqual(len(w.collect(self.benches, epoch=38 * DAY, sockets=[])[1]), 1, "then reported")

	def test_turned_off_removes_the_table_once(self):
		helper = os.path.join(self.tmp.name, "wolf-outbound-log")
		open(helper, "w").close()
		calls = []
		w = self.cwatcher(kernel_log=False, helper=helper, run=lambda cmd, **kw: calls.append(cmd) or mock.Mock(returncode=0))
		w.collect(self.benches, epoch=0, sockets=[])
		w.collect(self.benches, epoch=60, sockets=[])
		self.assertEqual(calls, [["sudo", "-n", helper, "--off"]])

	def test_a_failed_reapply_says_which_users_are_still_covered(self):
		w = self.kwatcher()
		w.collect(self.benches, epoch=0, sockets=[])
		other = os.path.join(self.tmp.name, "other-bench")
		os.makedirs(other)
		os.chown(other, 4343, 4343) if os.geteuid() == 0 else None
		w.run = lambda cmd, **kw: mock.Mock(returncode=1, stderr="nope")
		if os.stat(other).st_uid == self.uid:
			self.skipTest("cannot give the second bench another owner here")
		with self.assertLogs("wolf_agent.outbound", "WARNING") as logs:
			w.collect(self.benches + [{"name": "other", "path": other}], epoch=60, sockets=[])
		self.assertIn("still covers", logs.output[0])

	def test_the_kernel_journal_resumes_after_a_restart(self):
		from wolf_agent.tailer import JournalTailer

		with mock.patch.object(JournalTailer, "supports_cursor_file", return_value=True):
			cmd = JournalTailer(("kernel",), cursor_file="/var/lib/wolf-agent/spool/outbound-journal.cursor").cmd
		self.assertEqual(cmd[cmd.index("--cursor-file") + 1], "/var/lib/wolf-agent/spool/outbound-journal.cursor")
		with mock.patch.object(JournalTailer, "supports_cursor_file", return_value=False):
			self.assertNotIn("--cursor-file", JournalTailer(("kernel",), cursor_file="/x").cmd, "systemd before 242")

	def test_the_collector_closes_the_watcher(self):
		from wolf_agent.collector import InfraChecks

		infra = InfraChecks({"outbound": {"kernel_log": False}}, "h")
		infra.outbound_watcher = mock.Mock()
		infra.close()
		infra.outbound_watcher.close.assert_called_once()


class TestHelperScript(unittest.TestCase):
	"""agent/wolf-outbound-log.sh with a fake nft that records what it would apply."""

	SCRIPT = os.path.join(os.path.dirname(__file__), "..", "wolf-outbound-log.sh")

	def run_helper(self, *args, listed=True):
		import subprocess

		with tempfile.TemporaryDirectory() as tmp:
			record = os.path.join(tmp, "nft-calls")
			with open(os.path.join(tmp, "nft"), "w") as f:
				f.write(f"#!/bin/sh\necho \"$*\" >> {record}\n[ \"$1\" = list ] && exit {0 if listed else 1}\n"
				        f"[ \"$1\" = -f ] && cat >> {record}\nexit 0\n")  # only `nft -f -` reads a ruleset
			os.chmod(os.path.join(tmp, "nft"), 0o755)
			done = subprocess.run(["sh", self.SCRIPT, *args], capture_output=True, text=True, timeout=30,
			                      stdin=subprocess.DEVNULL, env={"PATH": f"{tmp}:/usr/bin:/bin"})  # fmt: skip
			calls = open(record).read() if os.path.exists(record) else ""
		return done.returncode, calls, done.stderr

	def test_uids_and_rules(self):
		rc, calls, _ = self.run_helper("1000", "1001")
		self.assertEqual(rc, 0)
		self.assertIn("elements = { 1000, 1001 }", calls)
		self.assertIn('limit wolf_rate { rate 50/second burst 200 packets }', calls)
		self.assertEqual(calls.count('limit name "wolf_rate"'), 10, "every rule shares one budget")
		self.assertEqual(calls.count("meta l4proto tcp"), 10, "TCP only")
		self.assertIn("flags skuid", calls)

	def test_refusals(self):
		for args in (["0"], ["00"], ["abc"], ["1000;", "x"], ["-1"]):
			rc, calls, _ = self.run_helper(*args)
			self.assertEqual((rc, calls), (2, ""), args)

	def test_containers_only_and_off(self):
		rc, calls, _ = self.run_helper()
		self.assertEqual(rc, 0)
		self.assertNotIn("skuid", calls, "no bench user: the forward rules only")
		self.assertEqual(self.run_helper("--off")[1], "list table inet wolf_outbound\ndelete table inet wolf_outbound\n")
		self.assertEqual(self.run_helper("--off", listed=False)[:2], (0, "list table inet wolf_outbound\n"))

if __name__ == "__main__":
	unittest.main()
