"""wolf-agent doctor: each check on real files, a fake collector for what the daemon would tail."""

import json
import os
import contextlib
import io
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wolf_agent import doctor, press  # noqa: E402

COMBINED = '203.0.113.9 - - [29/Oct/2026:02:00:13 +0000] "GET /app HTTP/1.1" 200 12 "-" "Mozilla/5.0"\n'


def write(path, text=""):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as f:
		f.write(text)


class FakeCollector:
	def __init__(self, paths, benches):
		self.sources = [SimpleNamespace(tailer=SimpleNamespace(path=p)) for p in paths]
		self.benches = benches

	def close(self):
		pass


class DoctorCase(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		root = self.tmp.name
		self.bench = os.path.join(root, "frappe-bench")
		self.logs = os.path.join(self.bench, "logs")
		write(os.path.join(self.logs, "web.log"), "x\n")
		write(os.path.join(self.bench, "sites", "a.example.com", "site_config.json"), "{}")
		self.nginx = os.path.join(root, "access.log")
		write(self.nginx, COMBINED * 5)
		self.spool = os.path.join(root, "spool")
		os.makedirs(self.spool)
		self.config = os.path.join(root, "config.json")
		write(self.config, "{}")
		os.chmod(self.config, 0o600)
		self.benches = [{"name": "main", "path": self.bench, "sites": ["a.example.com"], "platform": "generic",
		                 "nginx_access_log": self.nginx, "redis_queue": "redis://:s3cret@127.0.0.1:1"}]  # fmt: skip
		self.cfg = {"url": "https://wolf.example", "agent_id": "WAG-1", "agent_secret": "s", "hostname": "h",
		            "spool_dir": self.spool, "benches": self.benches, "auth_log": False,
		            "press": {"agent_dir": os.path.join(root, "no-press")}}  # fmt: skip
		self.paths = [os.path.join(self.logs, "web.log"), os.path.join(self.logs, "worker.log"), self.nginx]

	def run_doctor(self, cfg=None, paths=None, benches=None, euid=None):
		cfg = cfg or self.cfg
		collector = FakeCollector(self.paths if paths is None else paths, cfg["benches"] if benches is None else benches)
		# the machine running the tests has its own systemd, users and units: none of them is checked
		with mock.patch.object(doctor, "_agent_uid", return_value=None), mock.patch.object(doctor, "_systemd", return_value=False):
			checks = doctor.run(cfg, self.config, live=False, collector_factory=lambda c: collector,
			                    euid=os.geteuid() if euid is None else euid)  # fmt: skip
		return checks

	def find(self, checks, text):
		return [c for c in checks if text in c["title"]]


class TestDoctor(DoctorCase):
	def test_a_healthy_bench(self):
		checks = self.run_doctor()
		self.assertEqual(self.find(checks, "log file(s) readable")[0]["status"], doctor.OK)
		missing = self.find(checks, "not written yet")[0]
		self.assertEqual(missing["status"], doctor.INFO)
		self.assertIn("frappe-bench/worker.log", missing["title"])
		self.assertEqual(self.find(checks, "parsed (5 of its last 5 lines)")[0]["status"], doctor.OK)
		redis = self.find(checks, "queue Redis")[0]
		self.assertEqual(redis["status"], doctor.WARN)  # nothing listens on port 1
		self.assertTrue(redis["fix"])
		self.assertNotIn("s3cret", json.dumps(checks))  # a password in the URL stays out of the report
		self.assertEqual(self.find(checks, "registered as WAG-1")[0]["status"], doctor.OK)
		self.assertEqual(doctor.exit_code(checks), 0)
		self.assertIn("fix:", doctor.render(checks))

	@unittest.skipIf(os.geteuid() == 0, "root reads mode 000 files")
	def test_what_the_daemon_cannot_read(self):
		os.chmod(os.path.join(self.logs, "web.log"), 0)
		self.addCleanup(os.chmod, os.path.join(self.logs, "web.log"), 0o644)
		os.chmod(os.path.join(self.bench, "sites", "a.example.com", "site_config.json"), 0)
		self.addCleanup(os.chmod, os.path.join(self.bench, "sites", "a.example.com", "site_config.json"), 0o644)
		checks = self.run_doctor()
		self.assertEqual(self.find(checks, f"cannot read {self.logs}/web.log")[0]["status"], doctor.FAIL)
		self.assertEqual(self.find(checks, "site config(s) unreadable")[0]["status"], doctor.WARN)  # generic bench
		self.assertEqual(doctor.exit_code(checks), 1)
		press_bench = [{**self.benches[0], "platform": "press"}]
		checks = self.run_doctor({**self.cfg, "benches": press_bench})
		self.assertEqual(self.find(checks, "site config(s) unreadable")[0]["status"], doctor.INFO)  # 0600 by design

	@unittest.skipIf(os.geteuid() == 0, "root enters mode 000 folders")
	def test_a_folder_it_cannot_enter_is_not_a_missing_one(self):
		# a 0750 home the agent's user is not in the group of: Ubuntu's default since 21.04
		os.chmod(self.bench, 0)
		self.addCleanup(os.chmod, self.bench, 0o755)
		checks = self.run_doctor()
		bench = self.find(checks, "cannot enter")[0]
		self.assertEqual(bench["status"], doctor.FAIL)
		self.assertIn("group", bench["fix"])
		self.assertFalse(self.find(checks, "is gone"))
		self.assertEqual(len(self.find(checks, "permission denied, on it or a folder above")), 2)  # web.log, worker.log
		self.assertFalse(self.find(checks, "not written yet"))

	def test_a_collector_that_cannot_start(self):
		def broken(cfg):
			raise ValueError("bench entry without a path")

		with mock.patch.object(doctor, "_agent_uid", return_value=None), mock.patch.object(doctor, "_systemd", return_value=False):
			checks = doctor.run(self.cfg, self.config, live=False, collector_factory=broken)
		self.assertEqual(self.find(checks, "collector cannot start: ValueError")[0]["status"], doctor.FAIL)

	def test_journal_and_auth_log(self):
		with mock.patch.object(doctor, "_journal_groups", return_value=False), \
		     mock.patch.object(doctor, "resolve_auth_log", return_value="journal"):  # fmt: skip
			self.assertEqual(self.find(self.run_doctor(), "none of the groups")[0]["status"], doctor.FAIL)
		hint = SimpleNamespace(stdout="", stderr="Hint: You are currently not seeing messages from other users and the system.")
		with mock.patch.object(doctor, "_journal_groups", return_value=True), \
		     mock.patch.object(doctor, "resolve_auth_log", return_value="journal"), \
		     mock.patch.object(doctor.subprocess, "run", return_value=hint):  # fmt: skip
			self.assertEqual(self.find(self.run_doctor(), "cannot read the system journal")[0]["status"], doctor.FAIL)
		cfg = {**self.cfg, "auth_log": os.path.join(self.tmp.name, "nope.log")}
		self.assertEqual(self.find(self.run_doctor(cfg), "does not exist")[0]["status"], doctor.FAIL)

	def test_sudo_for_the_block_helper(self):
		helper = os.path.join(self.tmp.name, "wolf-block-fail2ban")
		write(helper)
		cfg = {**self.cfg, "response": {"enabled": True, "command": ["sudo", "-n", helper, "{ip}", "{seconds}"]}}
		with mock.patch.object(doctor.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
			check = self.find(self.run_doctor(cfg), "sudo refuses")[0]
		self.assertEqual(check["status"], doctor.FAIL)
		self.assertIn(f"NOPASSWD: {helper}", check["fix"])
		with mock.patch.object(doctor.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
		     mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/fail2ban-client"):  # fmt: skip
			checks = self.run_doctor(cfg)
		self.assertEqual(self.find(checks, "sudo allows")[0]["status"], doctor.OK)
		self.assertEqual(self.find(checks, "blocks go through fail2ban-client")[0]["status"], doctor.OK)
		os.unlink(helper)
		check = self.find(self.run_doctor(cfg), "is not installed")[0]
		self.assertIn("wolf-block-fail2ban.sh", check["fix"])  # the helper the command names

	@unittest.skipIf(os.geteuid() == 0, "root reads a mode 000 file")
	def test_an_unreadable_config(self):
		# registered as root, before the chown install.sh asks for
		from wolf_agent import cli

		os.chmod(self.config, 0)
		self.addCleanup(os.chmod, self.config, 0o600)
		args = SimpleNamespace(config=self.config, offline=True, json=False, verbose=False)
		with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as done:
			cli.cmd_doctor(args)
		self.assertEqual(done.exception.code, 1)
		self.assertIn("permission denied", out.getvalue())
		self.assertIn(f"chown wolf-agent: {self.config}", out.getvalue())

	def test_an_nginx_log_in_an_unknown_format(self):
		write(self.nginx, "this is not an access log\n" * 3)
		check = self.find(self.run_doctor(), "format Wolf reads")[0]
		self.assertEqual(check["status"], doctor.WARN)

	def test_registration_root_and_config_mode(self):
		cfg = {k: v for k, v in self.cfg.items() if k != "agent_secret"}
		checks = self.run_doctor(cfg)
		self.assertEqual(self.find(checks, "not registered")[0]["status"], doctor.FAIL)
		os.chmod(self.config, 0o644)
		with mock.patch.object(doctor, "_agent_uid", return_value=4242), mock.patch.object(doctor, "_systemd", return_value=False):
			checks = doctor.run(self.cfg, self.config, live=False, euid=0,
			                    collector_factory=lambda c: FakeCollector([], self.benches))  # fmt: skip
		self.assertIn("sudo -u wolf-agent", self.find(checks, "running as root")[0]["fix"])
		self.assertEqual(self.find(checks, "it holds the agent secret")[0]["status"], doctor.WARN)

	def test_no_bench_and_a_press_proxy(self):
		self.assertEqual(self.find(self.run_doctor(benches=[]), "no bench in the config")[0]["status"], doctor.WARN)
		agent_dir = os.path.join(self.tmp.name, "agent")
		write(os.path.join(agent_dir, "nginx", "proxy.conf"))
		cfg = {**self.cfg, "benches": [], "press": {"agent_dir": agent_dir}}
		self.assertEqual(self.find(self.run_doctor(cfg, benches=[]), "a Press proxy server")[0]["status"], doctor.INFO)

	def test_response_and_daemon(self):
		cfg = {**self.cfg, "response": {"enabled": True, "command": ["sudo", "-n", "/nonexistent/wolf-block", "{ip}", "{seconds}"]}}
		check = self.find(self.run_doctor(cfg), "is not installed")[0]
		self.assertEqual(check["status"], doctor.FAIL)
		self.assertEqual(self.find(self.run_doctor(), "response actions off")[0]["status"], doctor.INFO)
		write(os.path.join(self.spool, "watchdog-state.json"), json.dumps({"last_push_ok": time.time() - 3600}))
		self.assertEqual(self.find(self.run_doctor(), "last successful push 60 min ago")[0]["status"], doctor.WARN)
		cfg = {**self.cfg, "spool_dir": os.path.join(self.tmp.name, "gone")}
		self.assertEqual(self.find(self.run_doctor(cfg), "not writable")[0]["status"], doctor.FAIL)

	def test_a_check_that_breaks_is_a_finding(self):
		with mock.patch.object(doctor, "_auth", side_effect=RuntimeError("boom")):
			checks = self.run_doctor()
		broken = [c for c in checks if c["area"] == "host signals"]
		self.assertEqual((broken[0]["status"], broken[0]["title"]), (doctor.FAIL, "check failed: RuntimeError: boom"))
		self.assertTrue(self.find(checks, "spool"))  # the checks after it still ran


class TestDoctorPlatforms(DoctorCase):
	def test_pilot_export(self):
		export = os.path.join(self.tmp.name, "export")
		bench = {**self.benches[0], "name": "wolf", "platform": "pilot"}
		cfg = {**self.cfg, "benches": [bench]}
		with mock.patch.object(doctor.pilot, "EXPORT_DIR", export):
			self.assertEqual(self.find(self.run_doctor(cfg), "no export")[0]["status"], doctor.WARN)
			write(os.path.join(export, "wolf.json"), json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
			      "path": self.bench, "tasks": [{}], "units": [{}, {}]}))  # fmt: skip
			with mock.patch.object(doctor.pilot, "read_export", return_value={"tasks": [{}], "units": [{}, {}]}):
				self.assertEqual(self.find(self.run_doctor(cfg), "export fresh (1 tasks, 2 units)")[0]["status"], doctor.OK)
			with mock.patch.object(doctor.pilot, "read_export", return_value=None):
				self.assertEqual(self.find(self.run_doctor(cfg), "older than 5 minutes")[0]["status"], doctor.WARN)

	def test_press_job_database_and_its_wal_files(self):
		agent_dir = os.path.join(self.tmp.name, "agent")
		write(os.path.join(agent_dir, "config.json"), "{}")
		db = os.path.join(agent_dir, press.JOBS_DB)
		conn = sqlite3.connect(db)
		conn.execute("create table jobmodel (id integer primary key, name text)")
		conn.commit()
		conn.close()
		cfg = {**self.cfg, "platform": "press", "press": {"agent_dir": agent_dir, "proxy_ip": "10.0.0.3"}}
		checks = self.run_doctor(cfg)
		self.assertEqual(self.find(checks, "job history readable (0 jobs)")[0]["status"], doctor.OK)
		self.assertEqual(self.find(checks, "behind the proxy 10.0.0.3")[0]["status"], doctor.INFO)
		# -wal/-shm the Press agent cannot write: every Press job fails (seen on dev/press)
		write(db + "-wal")
		real_stat = os.stat

		def stat(path, *a, **k):
			st = real_stat(path, *a, **k)
			if path == db + "-wal":
				return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid + 1) + tuple(st)[5:])
			return st

		with mock.patch.object(doctor.os, "stat", stat):
			checks = self.run_doctor(cfg)
		check = self.find(checks, "-wal is not the Press agent's")[0]
		self.assertEqual(check["status"], doctor.FAIL)
		self.assertIn("supervisorctl stop", check["fix"])

	def test_a_press_proxy_has_no_benches_folder_to_warn_about(self):
		agent_dir = os.path.join(self.tmp.name, "agent")
		with mock.patch.object(press.log, "warning") as warning:
			self.assertEqual(press.discover_press_benches(agent_dir, benches_dir=os.path.join(self.tmp.name, "none")), [])
		warning.assert_not_called()



class TestSetupWatcher(unittest.TestCase):
	"""The daemon's hourly doctor run: in a thread, its result sent once with the next push."""

	def setUp(self):
		self.now = [0.0]
		self.started = []
		self.runs = []
		self.collector = FakeCollector(["/var/log/x.log"], [{"name": "b"}])

		def runner(cfg, path, live, collector_factory):
			self.runs.append((live, collector_factory(cfg).sources[0].tailer.path))
			return [doctor.item("logs", doctor.FAIL, "cannot read /var/log/x.log"), doctor.item("daemon", doctor.OK, "spool")]

		self.watcher = doctor.SetupWatcher({"setup_checks": {"interval": 3600}}, "/etc/wolf-agent/config.json", self.collector,
		                                   clock=lambda: self.now[0], runner=runner, start=self.started.append)  # fmt: skip

	def test_hourly_in_a_thread_and_once(self):
		self.assertIsNone(self.watcher.poll())  # not in the first minute
		self.now[0] = 61
		self.assertIsNone(self.watcher.poll())  # started, not finished
		self.assertEqual(len(self.started), 1)
		self.assertIsNone(self.watcher.poll())  # still running: not started twice
		self.assertEqual(len(self.started), 1)
		self.started[0]()  # the thread runs
		self.assertEqual(self.runs, [(False, "/var/log/x.log")])  # its own sources, the Wolf site not called
		result = self.watcher.poll()
		self.assertEqual([c["status"] for c in result["checks"]], ["fail", "ok"])
		self.assertIsNone(self.watcher.poll())  # handed over once
		metrics = {m["metric_name"]: m["value"] for m in doctor.setup_metrics(result, "h")}
		self.assertEqual(metrics, {"agent_setup_failed": 1, "agent_setup_warnings": 0})
		self.now[0] = 61 + 3599
		self.watcher.poll()
		self.assertEqual(len(self.started), 1)
		self.now[0] = 61 + 3600
		self.watcher.poll()
		self.assertEqual(len(self.started), 2)  # the next hour

	def test_a_run_that_breaks_and_turning_it_off(self):
		def broken(*a, **k):
			raise RuntimeError("boom")

		now = [0.0]
		w = doctor.SetupWatcher({}, "/c", self.collector, clock=lambda: now[0], runner=broken, start=lambda t: t())
		now[0] = 61
		self.assertIsNone(w.poll())  # started (and run inline)
		self.assertEqual(w.poll()["checks"][0]["title"], "setup checks failed: RuntimeError: boom")
		off = doctor.SetupWatcher({"setup_checks": {"enabled": False}}, "/c", self.collector, clock=lambda: 9999,
		                          runner=broken, start=lambda t: t())  # fmt: skip
		self.assertIsNone(off.poll())
		self.assertIsNone(off.poll())


class TestShipperSendsSetupOnce(unittest.TestCase):
	def test_once_even_when_spooled(self):
		from wolf_agent.shipper import Shipper

		with tempfile.TemporaryDirectory() as tmp:
			shipper = Shipper({"url": "http://127.0.0.1:1", "agent_id": "WAG-1", "agent_secret": "s", "hostname": "h",
			                   "spool_dir": tmp}, clock=lambda: 0)  # fmt: skip
			shipper.setup = {"checked_at": "2026-11-18T20:00:00Z", "checks": []}
			posted = []
			with mock.patch.object(shipper, "_post", side_effect=lambda body: posted.append(body)):
				self.assertTrue(shipper.send([], []))
				self.assertTrue(shipper.send([], []))
			self.assertIn("setup", posted[0])
			self.assertNotIn("setup", posted[1])


if __name__ == "__main__":
	unittest.main()
