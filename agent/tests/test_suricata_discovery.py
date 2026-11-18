import os
import tempfile
import unittest
from unittest import mock

from wolf_agent import collector
from wolf_agent import suricata_discovery as d
from wolf_agent.parsers.suricata import SuricataParser

CONFIG = """%YAML 1.1
---
vars:
  address-groups:
    HOME_NET: "[192.168.0.0/16]"
default-log-dir: /var/log/suricata/   # where the logs go
outputs:
  - fast:
      enabled: yes
      filename: fast.log
  - eve-log:
      enabled: no
      filetype: regular
      filename: old-eve.json
  - eve-log:
      enabled: yes
      filetype: syslog #regular|syslog|unix_dgram
      identity: "suricata"
  - eve-log:
      enabled: yes
      filetype: regular
      filename: alerts/eve.json
      types:
        - alert:
            filename: nested-is-not-ours.json
  - stats:
      enabled: yes
"""


def write(path, text):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as f:
		f.write(text)


class TestConfig(unittest.TestCase):
	def test_parse(self):
		log_dir, outputs = d.parse_config(CONFIG)
		self.assertEqual(log_dir, "/var/log/suricata/")
		self.assertEqual([(o["enabled"], o["filetype"], o["filename"]) for o in outputs],
		                 [(False, "regular", "old-eve.json"), (True, "syslog", "eve.json"),
		                  (True, "regular", "alerts/eve.json")])  # fmt: skip
		# the first enabled output to a regular file, under -l when given
		self.assertEqual(d.eve_path(CONFIG), "/var/log/suricata/alerts/eve.json")
		self.assertEqual(d.eve_path(CONFIG, "/data/ids"), "/data/ids/alerts/eve.json")
		on = "outputs:\n  - eve-log:\n      enabled: yes\n"
		self.assertEqual(d.eve_path(on + "      filename: /srv/eve.json\n"), "/srv/eve.json")
		self.assertIsNone(d.eve_path("outputs:\n  - eve-log:\n      enabled: no\n"))
		self.assertIsNone(d.eve_path("outputs:\n  - eve-log:\n      filename: /srv/eve.json\n"), "Suricata skips it without enabled")
		self.assertIsNone(d.eve_path(on + "      filename: eve-%Y.json\n"), "a dated name cannot be tailed")
		self.assertIsNone(d.eve_path(on + "      threaded: yes\n"), "one file per thread")
		self.assertEqual(d.eve_path("outputs:\n  - eve-log: # json\n      enabled: yes\n"), "/var/log/suricata/eve.json")

	def test_flags(self):
		self.assertEqual(d.flags(["/usr/bin/suricata", "-c", "/etc/s.yaml", "-l", "/logs", "-i", "eth0"]), ("/etc/s.yaml", "/logs"))
		self.assertEqual(d.flags(["suricata", "-c/etc/s.yaml", "-l/logs"]), ("/etc/s.yaml", "/logs"))
		self.assertEqual(d.flags(["suricata", "--af-packet"]), (None, None))
		self.assertEqual(d.flags(["suricata", "--set", "default-log-dir=/ids"]), (None, "/ids"))
		self.assertEqual(d.flags(["suricata", "-l", "/a", "--set", "default-log-dir=/b"]), (None, "/a"))


class TestDiscover(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = self.tmp.name
		self.proc = os.path.join(self.root, "proc")
		os.makedirs(self.proc)
		self.self_mounts = os.path.join(self.root, "self-mountinfo")
		write(self.self_mounts, "25 1 259:2 / / rw - ext4 /dev/x rw\n")

	def tearDown(self):
		self.tmp.cleanup()

	def process(self, pid, argv, cgroup="0::/system.slice/suricata.service", mounts=""):
		base = os.path.join(self.proc, str(pid))
		write(os.path.join(base, "cmdline"), "\0".join(argv) + "\0")
		write(os.path.join(base, "cgroup"), cgroup + "\n")
		write(os.path.join(base, "mountinfo"), mounts)

	def discover(self, **kw):
		kw.setdefault("configs", [])
		kw.setdefault("default", os.path.join(self.root, "nowhere", "eve.json"))
		return d.discover(proc=self.proc, self_mountinfo=self.self_mounts, **kw)

	def test_order(self):
		self.assertEqual(self.discover(configured="/x/eve.json"), ("/x/eve.json", "config"))
		self.assertEqual(self.discover(), (None, "no Suricata found"))
		config = os.path.join(self.root, "etc", "suricata.yaml")
		write(config, "default-log-dir: /opt/ids/\noutputs:\n  - eve-log:\n      enabled: yes\n")
		self.assertEqual(self.discover(configs=[config]), ("/opt/ids/eve.json", config))

	def test_a_running_suricata_on_the_host(self):
		config = os.path.join(self.root, "etc", "suricata.yaml")
		write(config, CONFIG)
		logs = os.path.join(self.root, "ids")
		os.makedirs(logs)
		self.process(4242, ["/usr/local/bin/suricata", "-c", config, "-l", logs, "--af-packet"])
		self.process(4300, ["/usr/bin/python3", "suricata-update"])  # not Suricata itself
		self.assertEqual(self.discover(), (os.path.join(logs, "alerts/eve.json"), "Suricata pid 4242"))

	def test_a_suricata_in_a_container(self):
		host_logs = os.path.join(self.root, "srv", "suricata-logs")
		os.makedirs(host_logs)
		cid = "a" * 64
		mounts = f"3017 3005 259:2 {host_logs} /var/log/suricata rw,relatime - ext4 /dev/x rw\n"
		self.process(4242, ["/usr/bin/suricata", "-i", "eth0"], cgroup=f"0::/system.slice/docker-{cid}.scope", mounts=mounts)
		# its config is in the image, not mounted: the default name in its log folder
		self.assertEqual(self.discover(), (os.path.join(host_logs, "eve.json"), "Suricata pid 4242 (container)"))

	def test_a_container_writing_where_the_agent_cannot_read(self):
		cid = "b" * 64
		mounts = "3017 3005 259:2 /var/lib/docker/volumes/x/_data /var/log/suricata rw - ext4 /dev/x rw\n"
		self.process(4242, ["/usr/bin/suricata", "-i", "eth0"], cgroup=f"0::/docker/{cid}", mounts=mounts)
		with mock.patch.object(d, "reachable", return_value=False):
			eve, why = self.discover()
		self.assertIsNone(eve)
		self.assertIn("bind-mount its log folder", why)

	def test_any_runtime_is_a_container_when_its_root_differs(self):
		host_logs = os.path.join(self.root, "srv", "ids logs")
		os.makedirs(host_logs)
		escaped = host_logs.replace(" ", "\\040")
		mounts = ("100 90 0:61 / / rw - overlay overlay rw\n"
		          f"101 100 259:2 {escaped} /var/log/suricata rw - ext4 /dev/x rw\n")  # fmt: skip
		self.process(4242, ["/usr/bin/suricata"], cgroup="0::/lxc.payload.ids", mounts=mounts)  # LXC: no 64-hex id
		self.assertEqual(self.discover(), (os.path.join(host_logs, "eve.json"), "Suricata pid 4242 (container)"))

	def test_the_next_instance_is_tried(self):
		mounts = "100 90 0:61 / / rw - overlay overlay rw\n"  # writes inside its image only
		self.process(4242, ["/usr/bin/suricata"], cgroup="0::/lxc.payload.a", mounts=mounts)
		logs = os.path.join(self.root, "ids")
		os.makedirs(logs)
		self.process(4300, ["/usr/bin/suricata", "-c", "/nowhere.yaml", "-l", logs])
		self.assertEqual(self.discover(), (os.path.join(logs, "eve.json"), "Suricata pid 4300"))
		os.remove(os.path.join(self.proc, "4300", "cmdline"))
		eve, why = self.discover()
		self.assertIsNone(eve)
		self.assertIn("inside its container", why)

	def test_undecodable_bytes(self):
		config = os.path.join(self.root, "etc", "suricata.yaml")
		os.makedirs(os.path.dirname(config))
		with open(config, "wb") as f:
			f.write(b"# caf\xe9\ndefault-log-dir: /opt/ids/\noutputs:\n  - eve-log:\n      enabled: yes\n")
		self.assertEqual(self.discover(configs=[config]), ("/opt/ids/eve.json", config))

	def test_host_path_through_a_separate_partition(self):
		write(self.self_mounts, "25 1 259:2 / / rw - ext4 /dev/x rw\n30 25 259:5 / /srv rw - ext4 /dev/y rw\n")
		mounts = "3017 3005 259:5 /ids/logs /var/log/suricata rw - ext4 /dev/y rw\n"
		self.process(4242, ["/usr/bin/suricata"], cgroup=f"0::/docker/{'c' * 64}", mounts=mounts)
		self.assertEqual(d.host_path("/var/log/suricata/eve.json", 4242, self.proc, self.self_mounts), "/srv/ids/logs/eve.json")
		self.assertIsNone(d.host_path("/etc/suricata/suricata.yaml", 4242, self.proc, self.self_mounts), "not mounted from the host")


class TestCollector(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.now = [0.0]
		self.cfg = {"hostname": "h", "benches": [], "auth_log": False, "collect_host_metrics": False, "wazuh": False,
		            "mariadb": False, "processes": False, "exposure": False, "backups": False, "tls": False, "rq": {},
		            "versions": False, "site_settings": False, "pilot": {"enabled": False}, "platform": "generic"}  # fmt: skip

	def collector(self, cfg, found):
		with mock.patch.object(d, "discover", side_effect=lambda *a, **k: found[0]):
			c = collector.Collector(cfg, state_path=os.path.join(self.tmp.name, "state.json"), clock=lambda: self.now[0])
		self.addCleanup(c.close)
		return c

	def eves(self, c):
		return [p.log_file for s in c.sources for p in s.parsers if isinstance(p, SuricataParser)]

	def test_follows_a_suricata_started_or_moved_later(self):
		found = [(None, "no Suricata found")]
		c = self.collector(self.cfg, found)
		self.assertEqual(self.eves(c), [])
		with mock.patch.object(d, "discover", side_effect=lambda *a, **k: found[0]):
			found[0] = ("/srv/ids/eve.json", "Suricata pid 1")
			c._recheck_suricata()
			self.assertEqual(self.eves(c), [], "not before RECHECK")
			self.now[0] += d.RECHECK
			c._recheck_suricata()
			self.assertEqual(self.eves(c), ["/srv/ids/eve.json"])
			found[0] = ("/data/eve.json", "Suricata pid 2")
			self.now[0] += d.RECHECK
			c._recheck_suricata()
			self.assertEqual(self.eves(c), ["/data/eve.json"], "replaced, not added")

	def test_a_configured_path_or_disabled_is_left_alone(self):
		c = self.collector({**self.cfg, "suricata": {"eve_log": "/x/eve.json"}}, [("/x/eve.json", "config")])
		with mock.patch.object(d, "discover") as discover:
			self.now[0] += d.RECHECK
			c._recheck_suricata()
			discover.assert_not_called()
		self.assertEqual(self.eves(c), ["/x/eve.json"])
		off = self.collector({**self.cfg, "suricata": False}, [("/y/eve.json", "Suricata pid 1")])
		self.assertEqual(self.eves(off), [])

	def test_a_discovery_error_does_not_stop_the_agent(self):
		with mock.patch.object(d, "discover", side_effect=RuntimeError("odd /proc")), self.assertLogs(level="WARNING"):
			c = collector.Collector(self.cfg, state_path=os.path.join(self.tmp.name, "s.json"), clock=lambda: self.now[0])
		self.addCleanup(c.close)
		self.assertEqual(self.eves(c), [])


if __name__ == "__main__":
	unittest.main()
