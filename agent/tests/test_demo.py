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
from wolf_agent.demo import core  # noqa: E402
from wolf_agent.demo.press import PressDemo  # noqa: E402
from wolf_agent.shipper import MAX_METRICS, Spool  # noqa: E402

LIVE_SINCE = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
STORY = LIVE_SINCE + timedelta(minutes=1)  # the first live storyline


class PressDemoTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		root = os.path.join(self.tmp.name, "demo-press")
		self.spool = os.path.join(self.tmp.name, "spool")
		self.demo = PressDemo(root, host="f1-demo-press", spool_dir=self.spool, rng=random.Random(7))
		self.demo.layout()
		cfg = dict(DEFAULTS)
		cfg.update(self.demo.agent_overrides())
		cfg.update({"hostname": "f1-demo-press", "spool_dir": self.spool, "collect_host_metrics": False})
		self.collector = Collector(cfg, state_path=os.path.join(self.spool, "tail-state.json"))

	def tearDown(self):
		self.collector.close()
		self.demo.logs.close()
		self.tmp.cleanup()

	def collect(self):
		return self.collector.collect(datetime.now(timezone.utc))

	def test_agent_reads_every_storyline_signal(self):
		self.collect()  # the agent opens the empty files and reads the empty job history
		self.assertTrue(self.demo.jobs_ready())
		core.wait_for_agent(self.spool, self.demo.tracked_paths(), self.demo.jobs_ready, timeout=0)

		self.demo.simulate(LIVE_SINCE, STORY + timedelta(minutes=27), LIVE_SINCE, cycle=30)
		metrics, events = self.collect()

		self.assertEqual({b["name"] for b in self.collector.benches}, set(self.demo_benches()))
		kinds = Counter((e["type"], e["category"]) for e in events)
		self.assertIn(("deployment", "press"), kinds)
		self.assertIn(("error", "http_502"), kinds)
		self.assertIn(("error", "traceback"), kinds)
		self.assertIn(("cron_failure", "scheduled_job"), kinds)
		self.assertIn(("worker_failure", "worker_crash"), kinds)
		self.assertIn(("security", "ssh_failed_login"), kinds)
		self.assertIn(("security", "web_attack_probe"), kinds)

		# cycle 0 migrates acme on its bench; the 502s land in its outage minutes, by log time
		deploy = next(e for e in events if e["type"] == "deployment")
		self.assertEqual((deploy["site"], deploy["bench"]), ("acme.press.test", "bench-0012-000431-f1-demo"))
		self.assertEqual(deploy["timestamp"], core.utc_iso(STORY))
		e502 = [m for m in metrics if m["metric_name"] == "http_502" and m["value"]]
		self.assertEqual({m["site"] for m in e502}, {"acme.press.test"})
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
		self.assertEqual({b["hostname"] for b in bodies}, {"f1-demo-press"})
		cpu = [m for m in samples if m["metric_name"] == "cpu_usage"]
		self.assertEqual(len(cpu), 120)
		self.assertEqual(cpu[0]["timestamp"], core.utc_iso(start))

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

	def test_wait_for_agent_times_out_with_what_is_missing(self):
		with self.assertRaisesRegex(TimeoutError, "access.log"):
			core.wait_for_agent(self.spool, self.demo.tracked_paths(), timeout=0)

	def test_configure_merges_into_the_agent_config(self):
		path = os.path.join(self.tmp.name, "config.json")
		with open(path, "w") as f:
			json.dump({"url": "http://wolf", "agent_id": "a", "agent_secret": "s", "spool_dir": self.spool}, f)
		cli.main(["--config", path, "demo", "press", "--root", self.demo.root, "--configure"])
		with open(path) as f:
			cfg = json.load(f)
		self.assertEqual(cfg["platform"], "press")
		self.assertEqual(cfg["press"]["agent_dir"], os.path.join(self.demo.root, "agent"))
		self.assertEqual(cfg["agent_secret"], "s")
		self.assertNotIn("watchdog", cfg)  # only the demo's keys are written, not every default

	def demo_benches(self):
		return {site.bench for site in self.demo.sites}


if __name__ == "__main__":
	unittest.main()
