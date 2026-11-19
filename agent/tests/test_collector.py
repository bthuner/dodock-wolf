import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wolf_agent import cli  # noqa: E402
from wolf_agent.collector import Collector  # noqa: E402

from test_discovery_config import make_bench  # noqa: E402
from test_shipper import FakeWolf  # noqa: E402

def write(path, text, mode="w"):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, mode) as f:
		f.write(text)


TRACEBACK = (
	"Traceback (most recent call last):\n"
	'  File "apps/frappe/frappe/app.py", line 1, in application\n'
	"    boom()\n"
	"ZeroDivisionError: division by zero\n"
	"next\n"
)


class TestCollectorEndToEnd(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.bench = make_bench(self.tmp.name, sites=("a.example.com",), redis=None)
		self.nginx = os.path.join(self.tmp.name, "nginx", "access.log")
		self.auth = os.path.join(self.tmp.name, "auth.log")
		for path in (self.nginx, self.auth):
			write(path, "")
		for name in ("frappe.web.log", "scheduler.log", "worker.error.log"):
			write(os.path.join(self.bench, "logs", name), "")
		self.cfg = {
			"hostname": "bench-01",
			"benches": [
				{
					"name": "main",
					"path": self.bench,
					"sites": ["a.example.com"],
					"logs_dir": os.path.join(self.bench, "logs"),
					"nginx_access_log": self.nginx,
					"redis_queue": None,
				}
			],
			"extra_logs": [],
			# the exposure check reads this machine's real listening sockets (a service on 0.0.0.0:8000
			# looks like an exposed gunicorn): not what is tested here, see test_exposure.py
			"exposure": {"enabled": False},
			"auth_log": self.auth,
			"tls": False,
			"mariadb": False,
			"processes": False,
		}

	def tearDown(self):
		self.tmp.cleanup()

	def test_cycle(self):
		state = os.path.join(self.tmp.name, "spool", "tail-state.json")
		collector = Collector(self.cfg, state_path=state)
		self.assertEqual(collector.collect()[1], [])  # first cycle only records EOF offsets

		logs = os.path.join(self.bench, "logs")
		write(self.nginx, '1.2.3.4 - - [29/Oct/2026:03:00:13 +0100] "GET /app HTTP/1.1" 502 0 "-" "x"\n', "a")
		write(os.path.join(logs, "frappe.web.log"), TRACEBACK, "a")
		write(os.path.join(logs, "scheduler.log"), "2026-10-29 02:00:13,1 INFO scheduler Scheduled Job Failed: erpnext.x.nightly for a.example.com\n", "a")
		write(os.path.join(logs, "worker.error.log"), "Work-horse terminated unexpectedly; waitpid returned 9\n", "a")
		write(self.auth, "Oct 29 02:00:01 bench-01 sshd[1]: Invalid user oracle from 198.51.100.7 port 1\n", "a")
		write(os.path.join(self.bench, "sites", "a.example.com", "logs", "frappe.web.log"), "", "a")

		ms, events = collector.collect()
		collector.close()
		types = sorted((e["type"], e["category"]) for e in events)
		self.assertEqual(
			types,
			[
				("cron_failure", "scheduled_job"),
				("error", "http_502"),
				("error", "traceback"),
				("security", "ssh_failed_login"),
				("worker_failure", "worker_crash"),
			],
		)
		http_502 = next(m for m in ms if m["metric_name"] == "http_502")
		self.assertEqual((http_502["value"], http_502["site"], http_502["bench"]), (1, "a.example.com", "main"))
		self.assertTrue(all(e["host"] == "bench-01" for e in events))
		self.assertTrue(os.path.exists(state))

	def test_shared_nginx_log_across_benches(self):
		other = make_bench(os.path.join(self.tmp.name, "b2"), name="other-bench", sites=("b.example.com",), redis=None)
		self.cfg["benches"].append(
			{"name": "other", "path": other, "sites": ["b.example.com"], "nginx_access_log": self.nginx}
		)
		collector = Collector(self.cfg, from_start=True)
		nginx_sources = [s for s in collector.sources if s.tailer.path == self.nginx]
		self.assertEqual(len(nginx_sources), 1)
		write(self.nginx, 'b.example.com 1.2.3.4 - - [29/Oct/2026:03:00:13 +0100] "GET / HTTP/1.1" 500 0 "-" "x"\n', "a")
		_, events = collector.collect()
		collector.close()
		e = next(e for e in events if e["source"] == "nginx")
		self.assertEqual((e["site"], e["bench"]), ("b.example.com", "other"))


class TestCli(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.server = FakeWolf()
		self.bench = make_bench(self.tmp.name, sites=("a.example.com",), redis=None)
		self.config = os.path.join(self.tmp.name, "etc", "config.json")

	def tearDown(self):
		self.server.shutdown()
		self.server.server_close()
		self.tmp.cleanup()

	def run_cli(self, *argv):
		out = io.StringIO()
		with redirect_stdout(out):
			code = cli.main(["--config", self.config, *argv])
		return code, out.getvalue()

	def test_register_then_check_and_mark_deployment(self):
		code, out = self.run_cli("register", "--url", self.server.url, "--token", "tok", "--bench", self.bench, "--hostname", "bench-01")
		self.assertEqual(code, 0)
		self.assertIn("WAG-0007", out)
		with open(self.config) as f:
			cfg = json.load(f)
		self.assertEqual(cfg["agent_id"], "WAG-0007")
		self.assertEqual(cfg["push_interval"], 20)
		self.assertEqual(cfg["benches"][0]["sites"], ["a.example.com"])
		self.assertEqual(oct(os.stat(self.config).st_mode & 0o777), "0o600")

		# check: no network, prints a payload
		cfg["auth_log"] = False
		with open(self.config, "w") as f:
			json.dump(cfg, f)
		before = len(self.server.requests)
		code, out = self.run_cli("check")
		self.assertEqual(code, 0)
		self.assertEqual(json.loads(out)["hostname"], "bench-01")
		self.assertEqual(len(self.server.requests), before)

		code, _ = self.run_cli("mark-deployment", "--bench", "frappe-bench", "--note", "update")
		self.assertEqual(code, 0)
		self.assertTrue(self.server.requests[-1]["path"].endswith("ingest.deployment"))
		self.assertNotIn("silence_minutes", self.server.requests[-1]["body"])

		code, out = self.run_cli("mark-deployment", "--bench", "frappe-bench", "--silence", "1h")
		self.assertEqual(code, 0)
		self.assertEqual(self.server.requests[-1]["body"]["silence_minutes"], 60)

		before = len(self.server.requests)
		with self.assertRaises(SystemExit) as ctx:
			self.run_cli("mark-deployment", "--bench", "frappe-bench", "--silence", "soon")
		self.assertIn("invalid duration", str(ctx.exception.code))
		self.assertEqual(len(self.server.requests), before)

	def test_register_failure_exits(self):
		self.server.status = 403
		with self.assertRaises(SystemExit) as ctx:
			self.run_cli("register", "--url", self.server.url, "--token", "bad", "--bench", self.bench)
		self.assertIn("registration failed", str(ctx.exception.code))

	def test_run_stops_on_auth_error(self):
		cfg = {
			"url": self.server.url, "agent_id": "WAG-1", "agent_secret": "s", "hostname": "h",
			"spool_dir": os.path.join(self.tmp.name, "spool"), "benches": [], "auth_log": False,
		}
		os.makedirs(os.path.dirname(self.config), exist_ok=True)
		with open(self.config, "w") as f:
			json.dump(cfg, f)
		self.server.status = 401
		with mock.patch.object(cli.signal, "signal"):
			code, _ = self.run_cli("run")
		self.assertEqual(code, cli.EXIT_AUTH)

	def test_discover(self):
		code, out = self.run_cli("discover", "--bench", self.bench)
		self.assertEqual(json.loads(out)[0]["name"], "frappe-bench")

	def run_cli_err(self, *argv):
		err = io.StringIO()
		with redirect_stderr(err):
			code, out = self.run_cli(*argv)
		return code, out, err.getvalue()

	def test_v01_options_warn_and_do_nothing(self):
		# Press v1's options, still in old scripts and units: accepted, warned about, ignored
		code, out, err = self.run_cli_err("discover", "--bench", self.bench, "--platform", "press")
		self.assertEqual((code, json.loads(out)[0]["name"]), (0, "frappe-bench"))
		self.assertEqual(err.count("--platform was removed in 0.2: ignored"), 1)

		code, out, err = self.run_cli_err("register", "--url", self.server.url, "--token", "tok", "--bench", self.bench,
		                                  "--platform", "auto")  # fmt: skip
		self.assertEqual(code, 0)
		self.assertIn("--platform was removed in 0.2: ignored", err)
		with open(self.config) as f:
			cfg = json.load(f)
		self.assertNotIn("platform", cfg)
		cfg.update(auth_log=False)
		with open(self.config, "w") as f:
			json.dump(cfg, f)

		code, out, err = self.run_cli_err("check", "--platform", "generic", "--bench", self.bench)
		self.assertEqual(code, 0)
		self.assertEqual(err.count("--platform was removed in 0.2: ignored"), 1)

		code, _, err = self.run_cli_err("mark-deployment", "--bench", "frappe-bench", "--source", "press")
		self.assertEqual(code, 0)
		self.assertIn("--source press was removed in 0.2: ignored", err)
		self.assertEqual(self.server.requests[-1]["body"]["source"], "manual")

		before = len(self.server.requests)
		code, out, err = self.run_cli_err("refresh")
		self.assertEqual((code, out), (0, ""))
		self.assertIn("removed in 0.2: ignored", err)
		self.assertEqual(len(self.server.requests), before)

	def test_the_v01_host_metrics_key_is_ignored(self):
		# v0.1 wrote collect_host_metrics into every config: accepted, warned about, collects nothing
		code, _, err = self.run_cli_err("register", "--url", self.server.url, "--token", "tok", "--bench", self.bench)
		self.assertEqual(code, 0)
		with open(self.config) as f:
			cfg = json.load(f)
		self.assertNotIn("collect_host_metrics", cfg)  # a config written by 0.2 does not carry it
		cfg.update(auth_log=False, collect_host_metrics=True)
		with open(self.config, "w") as f:
			json.dump(cfg, f)

		code, out, err = self.run_cli_err("check")
		self.assertEqual(code, 0)
		self.assertEqual(err.count("the config key collect_host_metrics"), 1)
		self.assertIn("was removed in 0.2: ignored", err)
		names = {m["metric_name"] for m in json.loads(out)["metrics"]}
		self.assertFalse(names & {"cpu_usage", "memory_used_percent", "swap_used_percent", "disk_used_percent",
		                          "load_1m", "load_5m", "load_15m", "load_per_core"}, names)  # fmt: skip

		code, _, err = self.run_cli_err("register", "--url", self.server.url, "--token", "tok", "--bench", self.bench)
		self.assertEqual(code, 0)
		with open(self.config) as f:
			self.assertNotIn("collect_host_metrics", json.load(f))  # re-registering drops it

	def test_run_logs_the_v01_host_metrics_key(self):
		cfg = {
			"url": self.server.url, "agent_id": "WAG-1", "agent_secret": "s", "hostname": "h",
			"spool_dir": os.path.join(self.tmp.name, "spool"), "benches": [], "auth_log": False,
			"collect_host_metrics": False,
		}
		os.makedirs(os.path.dirname(self.config), exist_ok=True)
		with open(self.config, "w") as f:
			json.dump(cfg, f)
		self.server.status = 401  # stops the loop after its first push
		with mock.patch.object(cli.signal, "signal"), self.assertLogs("wolf_agent", "WARNING") as logs:
			self.run_cli("run")
		self.assertEqual(sum("collect_host_metrics was removed in 0.2: ignored" in line for line in logs.output), 1)

	def test_run_warns_on_a_press_v1_config(self):
		cfg = {
			"url": self.server.url, "agent_id": "WAG-1", "agent_secret": "s", "hostname": "h",
			"spool_dir": os.path.join(self.tmp.name, "spool"), "benches": [], "auth_log": False,
			"platform": "press", "press": {"proxy_ip": "10.0.0.3"},
		}
		os.makedirs(os.path.dirname(self.config), exist_ok=True)
		with open(self.config, "w") as f:
			json.dump(cfg, f)
		self.server.status = 401  # stops the loop after its first push
		with mock.patch.object(cli.signal, "signal"), self.assertLogs("wolf_agent", "WARNING") as logs:
			self.run_cli("run")
		self.assertTrue(any("Press v1 is supported by Dodock Wolf v0.1.0 only" in line and "WOLF_AGENT_REF=v0.1.0" in line
		                    for line in logs.output))  # fmt: skip


if __name__ == "__main__":
	unittest.main()
