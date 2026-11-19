import unittest
from datetime import datetime, timedelta

from dodock_wolf.wolf import catalog
from dodock_wolf.wolf.presets import PRESETS, REMOVED_PRESETS

NOW = datetime(2026, 10, 30, 12, 0)


def series(metric="queue_length", ago=timedelta(seconds=20), **scope):
	return {"metric_name": metric, "last_at": NOW - ago if ago is not None else None, "host": "h1", "bench": None, "site": None, **scope}


class TestCatalog(unittest.TestCase):
	def test_every_metric_rule_preset_is_in_the_catalog(self):
		for p in PRESETS:
			if p.get("signal_type") == "metric":
				self.assertIn(p["metric_name"], catalog.CATALOG, p["rule_name"])

	def test_kinds(self):
		self.assertEqual(catalog.CATALOG["rq_failed_jobs_added"]["kind"], "interval_count")
		self.assertEqual(catalog.CATALOG["rq_failed_jobs"]["kind"], "gauge")  # registry size, not "failed lately"
		self.assertIn("part of 5xx", catalog.CATALOG["http_502"]["label"])

	def test_stale_after_follows_cadence(self):
		self.assertEqual(catalog.stale_after("queue_length"), timedelta(minutes=5))
		self.assertEqual(catalog.stale_after("tls_days_left"), timedelta(hours=3))

	def test_every_metric_the_agent_sends_is_catalogued(self):
		import pathlib
		import re

		src = "".join(p.read_text() for p in pathlib.Path(__file__).parents[1].joinpath("agent/wolf_agent").rglob("*.py"))
		sent = set(re.findall(r'(?:metric|add)\("([a-z0-9_]+)"', src))
		self.assertTrue(sent)
		self.assertEqual(sent - set(catalog.CATALOG), set())
		self.assertEqual(sent & catalog.REMOVED_METRICS, set())  # the agent no longer collects them


class TestRemovedMetrics(unittest.TestCase):
	"""The host resource metrics 0.2 removed (#136, step 2c): Frappe Cloud v2 and Pilot report them."""

	def test_they_left_the_catalog_and_the_presets(self):
		self.assertEqual(catalog.REMOVED_METRICS, {"cpu_usage", "memory_used_percent", "swap_used_percent", "disk_used_percent",
		                                           "load_1m", "load_5m", "load_15m", "load_per_core"})  # fmt: skip
		self.assertEqual(catalog.REMOVED_METRICS & set(catalog.CATALOG), set())
		self.assertEqual(catalog.REMOVED_METRICS & catalog.SECURITY_METRICS, set())
		self.assertEqual({p.get("metric_name") for p in PRESETS} & catalog.REMOVED_METRICS, set())
		self.assertEqual({p["rule_name"] for p in PRESETS} & set(REMOVED_PRESETS), set())
		# the agent's setup checks stay: the host group is not empty
		self.assertIn("host", {spec["group"] for spec in catalog.CATALOG.values()})

	def test_ingest_drops_them(self):
		import pathlib

		src = pathlib.Path(__file__).parents[1].joinpath("dodock_wolf/api/ingest.py").read_text()
		self.assertIn('if metric["metric_name"] in catalog.REMOVED_METRICS:\n\t\t\tcontinue', src)

	def test_the_upgrade_patch_runs(self):
		import pathlib

		root = pathlib.Path(__file__).parents[1].joinpath("dodock_wolf")
		self.assertIn("dodock_wolf.patches.remove_host_metrics", root.joinpath("patches.txt").read_text().split("[post_model_sync]")[1])
		self.assertTrue(root.joinpath("patches/remove_host_metrics.py").exists())


class TestSecurityMetrics(unittest.TestCase):
	"""The metrics security reads (#136, step 2): named once, so the operations metrics can go."""

	def test_they_are_catalogued(self):
		self.assertEqual(catalog.SECURITY_METRICS - set(catalog.CATALOG), set())
		self.assertEqual(catalog.role("tls_days_left"), "security")
		self.assertEqual(catalog.role("queue_length"), "operations")

	def test_the_security_score_reads_only_them(self):
		import pathlib
		import re

		src = pathlib.Path(__file__).parents[1].joinpath("dodock_wolf/api/security.py").read_text()
		read = set(re.findall(r'_latest\("([a-z0-9_]+)"', src)) | set(re.findall(r'"metric_name": "([a-z0-9_]+)"', src))
		self.assertTrue(read)
		self.assertEqual(read - catalog.SECURITY_METRICS, set())

	def test_every_metric_preset_is_one_or_the_other(self):
		# a security preset on an operations metric would break when those go
		security = {p["metric_name"] for p in PRESETS if p.get("signal_type") == "metric"} & catalog.SECURITY_METRICS
		self.assertEqual(security, {"backup_age_hours", "tls_days_left", "exposed_services", "site_config_risks",
		                            "security_score", "agent_setup_failed"})  # fmt: skip


class TestState(unittest.TestCase):
	RULE = {"name": "R1", "metric_name": "queue_length", "filter_host": None, "filter_bench": None, "filter_site": None}

	def test_missing_stale_and_unwatched_are_different(self):
		self.assertEqual(catalog.state(series(ago=None), NOW), "missing")
		self.assertEqual(catalog.state(series(ago=timedelta(minutes=6)), NOW), "stale")
		self.assertEqual(catalog.state(series(), NOW), "unwatched")
		# a slow signal is not stale after 6 minutes
		self.assertEqual(catalog.state(series("backup_age_hours", timedelta(minutes=12), site="a"), NOW), "unwatched")

	def test_watched_and_firing(self):
		self.assertEqual(catalog.state(series(), NOW, [self.RULE]), "watched")
		incident = {"alert_rule": "R1", "host": "h1", "bench": None, "site": None}
		self.assertEqual(catalog.state(series(), NOW, [self.RULE], [incident]), "firing")
		other_host = {**incident, "host": "h2"}
		self.assertEqual(catalog.state(series(), NOW, [self.RULE], [other_host]), "watched")

	def test_rule_filters_limit_where_it_applies(self):
		only_h2 = {**self.RULE, "filter_host": "h2"}
		self.assertFalse(catalog.rule_applies(only_h2, series()))
		self.assertEqual(catalog.state(series(), NOW, [only_h2]), "unwatched")
		self.assertFalse(catalog.rule_applies({**self.RULE, "metric_name": "rq_workers"}, series()))

	def test_firing_stays_firing_when_samples_stop(self):
		# a host that went silent mid-incident stays on top, and says its data stopped
		incident = {"alert_rule": "R1", "host": "h1"}
		silent = series(ago=timedelta(hours=1))
		self.assertEqual(catalog.state(silent, NOW, [self.RULE], [incident]), "firing")
		self.assertTrue(catalog.is_stale(silent, NOW))

	def test_no_recent_value_is_stale(self):
		# TLS last seen 2.5 h ago: under its 3 h cadence, but no value to show as current
		tls = series("tls_days_left", timedelta(hours=2, minutes=30), site="a", recent=False)
		self.assertEqual(catalog.state(tls, NOW), "stale")

	def test_label_incident_concerns_its_label_only(self):
		incident = {"alert_rule": "R1", "host": "h1", "group_key": "host=h1,label_key=queue=default"}
		root, data = series(label_key="queue=default"), series(label_key="queue=long")
		self.assertEqual(catalog.state(root, NOW, [self.RULE], [incident]), "firing")
		self.assertEqual(catalog.state(data, NOW, [self.RULE], [incident]), "watched")
		host_wide = {"alert_rule": "R1", "host": "h1", "group_key": "host=h1"}
		self.assertEqual(catalog.state(data, NOW, [self.RULE], [host_wide]), "firing")


if __name__ == "__main__":
	unittest.main()
