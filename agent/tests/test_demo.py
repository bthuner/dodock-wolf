import json
import os
import random
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wolf_agent import cli  # noqa: E402
from wolf_agent.collector import Collector  # noqa: E402
from wolf_agent.config import DEFAULTS  # noqa: E402
from wolf_agent.demo import build, core  # noqa: E402
from wolf_agent.demo.bench import BenchDemo  # noqa: E402
from wolf_agent.demo.press import PressDemo  # noqa: E402
from wolf_agent.shipper import MAX_METRICS, Spool  # noqa: E402

LIVE_SINCE = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
STORY = LIVE_SINCE + timedelta(minutes=1)  # the first live storyline


class DemoRoundTrip:
	"""The demo's files, read by the real Collector: what Wolf would get from a real agent."""

	host = None

	def make_demo(self, root):
		raise NotImplementedError

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.spool = os.path.join(self.tmp.name, "spool")
		self.marks = []
		self.demo = self.make_demo(os.path.join(self.tmp.name, "demo"))
		self.demo.layout()
		cfg = dict(DEFAULTS)
		cfg.update(self.demo.agent_overrides())
		cfg.update({"hostname": self.host, "spool_dir": self.spool, "collect_host_metrics": False})
		self.collector = Collector(cfg, state_path=os.path.join(self.spool, "tail-state.json"))

	def tearDown(self):
		self.collector.close()
		self.demo.logs.close()
		self.tmp.cleanup()

	def collect(self):
		return self.collector.collect(datetime.now(timezone.utc))

	def run_first_cycle(self):
		self.collect()  # the agent opens the empty files (and reads the empty job history)
		self.assertTrue(self.demo.ready())
		core.wait_for_agent(self.spool, self.demo.tracked_paths(), self.demo.ready, timeout=0)
		self.demo.simulate(LIVE_SINCE, STORY + timedelta(minutes=27), LIVE_SINCE, cycle=30)
		return self.collect()

	def test_agent_reads_every_storyline_signal(self):
		metrics, events = self.run_first_cycle()
		self.assertEqual({b["name"] for b in self.collector.benches}, set(self.demo.benches))
		kinds = Counter((e["type"], e["category"]) for e in events)
		for kind in [("error", "http_502"), ("error", "traceback"), ("cron_failure", "scheduled_job"),
		             ("worker_failure", "worker_crash"), ("security", "ssh_failed_login"), ("security", "web_attack_probe")]:  # fmt: skip
			self.assertIn(kind, kinds)

		# cycle 0 deploys the first site; its 502s land in the outage minutes, by log time
		target = self.demo.sites[0]
		self.check_deployment(events, target)
		e502 = [m for m in metrics if m["metric_name"] == "http_502" and m["value"]]
		self.assertEqual({m["site"] for m in e502}, {target.name})
		self.assertEqual({m["bench"] for m in e502}, {target.bench})
		self.assertGreaterEqual(sum(m["value"] for m in e502), 10)  # the preset's threshold over 5 min
		for m in e502:
			self.assertTrue(core.utc_iso(STORY) <= m["timestamp"] <= core.utc_iso(STORY + timedelta(minutes=4)))
		# custom domains are mapped to their site, so no unknown vhost shows up
		self.assertTrue({m["site"] for m in metrics} <= {s.name for s in self.demo.sites})

		ssh = sum(e["payload"].get("count", 1) for e in events if e["category"] == "ssh_failed_login")
		self.assertGreaterEqual(ssh, 20)  # SSH brute force preset
		probes = sum(e["payload"]["count"] for e in events if e["category"] == "web_attack_probe")
		self.assertGreaterEqual(probes, 100)  # Web attack scan preset
		cron = next(e for e in events if e["type"] == "cron_failure")
		self.assertEqual(cron["timestamp"], core.utc_iso(STORY + timedelta(minutes=8)))

	def test_history_metrics_go_to_the_spool(self):
		start = LIVE_SINCE - timedelta(hours=2)
		self.demo.simulate(start, LIVE_SINCE, LIVE_SINCE, cycle=30, history=True)
		bodies = [body for _, body in Spool(os.path.join(self.spool, "outbox")).items()]
		samples = [m for body in bodies for m in body["metrics"]]
		self.assertTrue(all(len(body["metrics"]) <= MAX_METRICS for body in bodies))
		self.assertEqual({b["hostname"] for b in bodies}, {self.host})
		cpu = [m for m in samples if m["metric_name"] == "cpu_usage"]
		self.assertEqual(len(cpu), 120)
		self.assertEqual(cpu[0]["timestamp"], core.utc_iso(start))

	def test_wait_for_agent_times_out_with_what_is_missing(self):
		with self.assertRaisesRegex(TimeoutError, "access.log"):
			core.wait_for_agent(self.spool, self.demo.tracked_paths(), timeout=0)


class PressDemoTest(DemoRoundTrip, unittest.TestCase):
	host = "f1-demo-press"

	def make_demo(self, root):
		return PressDemo(root, host=self.host, spool_dir=self.spool, rng=random.Random(7))

	def check_deployment(self, events, target):
		deploy = next(e for e in events if e["type"] == "deployment")
		self.assertEqual((deploy["site"], deploy["bench"]), (target.name, target.bench))
		self.assertEqual(deploy["timestamp"], core.utc_iso(STORY))

	def test_stories(self):
		day = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
		start = day - timedelta(days=1)
		history = self.demo.stories(start, day, LIVE_SINCE, cycle=30)
		# from the day before `start` (a storyline may cross midnight): one daily storyline and one
		# nightly cron failure per day, at their local times
		starts = sorted(actions[0][0] for actions, _ in history)
		self.assertEqual(len(starts), 6)
		self.assertEqual({core.local(t).strftime("%H:%M") for t in starts}, {"10:30", "02:10"})
		self.assertTrue(any(start <= t < day for t in starts))
		# a live window starting mid-storyline still gets that storyline's remaining actions
		running = self.demo.stories(STORY + timedelta(minutes=20), STORY + timedelta(minutes=21), LIVE_SINCE, cycle=30)
		times = [t for actions, _ in running for t, _ in actions]
		self.assertIn(STORY + timedelta(minutes=19), times)  # the web scan of cycle 0


class MultiDemoTest(DemoRoundTrip, unittest.TestCase):
	host = "dokos-multi-1"
	kind = "multi"

	def make_demo(self, root):
		mark = lambda bench, site, note, at: self.marks.append((bench, site, at))  # noqa: E731
		return BenchDemo(self.kind, root, host=self.host, spool_dir=self.spool, rng=random.Random(7), mark_deployment=mark)

	def check_deployment(self, events, target):
		# plain benches: marked through the deployment endpoint, with the deployment's own time
		self.assertEqual(self.marks, [(target.bench, target.name, STORY)])

	def test_failed_deploy_and_bench_failure_are_tracebacks(self):
		self.collect()
		self.demo.deploy(STORY, self.demo.sites[0], failed=True)
		self.demo.bench_failure(STORY + timedelta(minutes=2), self.demo.sites[0].bench)
		self.demo.logs.flush()
		_, events = self.collect()
		titles = {e["title"] for e in events if e["category"] == "traceback"}
		self.assertTrue(any("OperationalError" in t for t in titles), titles)
		self.assertTrue(any("CalledProcessError" in t for t in titles), titles)

	def test_a_failing_mark_does_not_stop_the_demo(self):
		def broken(*_):
			raise OSError("connection refused")

		self.demo.mark_deployment = broken
		with self.assertLogs("wolf_agent.demo.bench", "WARNING"):
			self.demo.deploy(STORY, self.demo.sites[0])


class SingleDemoTest(MultiDemoTest):
	host = "dokos-single-1"
	kind = "single"


class CliTest(unittest.TestCase):
	def test_configure_merges_into_the_agent_config(self):
		with tempfile.TemporaryDirectory() as tmp:
			for kind, platform in (("press", "press"), ("multi", "generic"), ("single", "generic")):
				path = os.path.join(tmp, f"{kind}.json")
				root = os.path.join(tmp, kind)
				with open(path, "w") as f:
					json.dump({"url": "http://wolf", "agent_id": "a", "agent_secret": "s", "spool_dir": tmp}, f)
				cli.main(["--config", path, "demo", kind, "--root", root, "--configure"])
				with open(path) as f:
					cfg = json.load(f)
				self.assertEqual(cfg["platform"], platform)
				self.assertEqual(cfg["agent_secret"], "s")
				self.assertNotIn("watchdog", cfg)  # only the demo's keys are written, not every default
				if kind == "press":
					self.assertEqual(cfg["press"]["agent_dir"], os.path.join(root, "agent"))
				else:
					self.assertTrue(all(b["path"].startswith(root) for b in cfg["benches"]))

	def test_build_defaults(self):
		cfg = {"hostname": "h", "spool_dir": "/tmp/x"}
		self.assertEqual(build("multi", cfg).root, "/home/frappe/demo-multi")
		self.assertEqual(len(build("single", cfg).sites), 1)
		self.assertIsNone(build("single", cfg).mark_deployment)  # no credentials: bench.log only
		self.assertIsNotNone(build("multi", dict(cfg, url="http://w", agent_id="a", agent_secret="s")).mark_deployment)


if __name__ == "__main__":
	unittest.main()
