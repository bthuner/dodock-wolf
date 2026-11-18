import unittest

from dodock_wolf.wolf import presets, rule_sentence


def text(rule):
	return rule_sentence.as_text(rule_sentence.describe(rule))


class TestRuleSentence(unittest.TestCase):
	def test_a_metric_rule(self):
		rule = {"rule_name": "Disk", "severity": "critical", "signal_type": "metric", "metric_name": "disk_used_percent",
		        "aggregation": "min", "operator": ">", "threshold": 90.0, "window_minutes": 5, "group_by": "host",
		        "min_samples": 3, "auto_resolve": 1, "cooldown_minutes": 60, "filter_bench": "prod",
		        "channels": [{"channel_type": "ntfy", "enabled": 1}, {"channel_type": "Email", "enabled": 1},
		                     {"channel_type": "Email", "enabled": 1}, {"channel_type": "Slack", "enabled": 0}],
		        "notify_on_resolve": 0}  # fmt: skip
		self.assertEqual(text(rule), (
			"Opens a critical incident when the lowest disk_used_percent over the last 5 min is above 90, per host, "
			"only for bench prod. It needs at least 3 samples in the window. It resolves by itself once the "
			"condition no longer holds; matching again within 1 h reopens the same incident. It notifies ntfy and 2 Email."
		))  # fmt: skip

	def test_values_are_marked(self):
		head = rule_sentence.describe({"signal_type": "event", "event_type": "security", "event_category": "ssh", "threshold": 5})[0]
		self.assertEqual([t for t, value in head if value], ["warning", "security", "ssh", "5 min", "above", "5", "across everything it watches"])

	def test_an_event_rule_with_timing_and_hysteresis(self):
		rule = {"severity": "warning", "signal_type": "event", "event_type": "cron_failure", "min_severity": "critical",
		        "operator": ">=", "threshold": 1, "window_minutes": 15, "group_by": "site", "active_from": "22:00:00",
		        "active_to": "4:00", "require_recent_deployment": 1, "deployment_window_minutes": 0,
		        "fire_after_evaluations": 3, "use_resolve_threshold": 1, "resolve_threshold": 0.5,
		        "resolve_after_evaluations": 2, "cooldown_minutes": 0}  # fmt: skip
		self.assertEqual(text(rule), (
			"Opens a warning incident when the number of cron_failure events at critical severity over the last 15 min "
			"is at least 1, per site. It is checked only between 22:00 and 04:00 (over midnight), server time. "
			"It fires only within 30 min of a deployment. It waits until the condition holds 3 evaluations in a row. "
			"It resolves by itself once the value is below 0.50 for 2 evaluations in a row. "
			"It notifies nobody: the incident shows in Wolf only."
		))  # fmt: skip

	def test_a_sequence_rule(self):
		rule = {"signal_type": "sequence", "sequence_entity": "ip", "first_categories": "ssh_failed_login\nweb_attack_probe",
		        "then_categories": "ssh_login", "sequence_minutes": 120, "operator": ">", "threshold": 0,
		        "window_minutes": 10, "auto_resolve": 0}  # fmt: skip
		self.assertTrue(text(rule).startswith(
			"Opens a warning incident when the same IP address sets off ssh_failed_login or web_attack_probe and then "
			"ssh_login within 2 h of it, and the number of times it happens over the last 10 min is above 0. "
			"It stays open until someone resolves it."
		))  # fmt: skip

	def test_disabled_channels_and_escalation(self):
		rule = {"enabled": 0, "channels": [{"channel_type": "ntfy", "enabled": 0}], "escalate_after_minutes": 15,
		        "escalation_channels": [{"channel_type": "PagerDuty", "enabled": 1}]}  # fmt: skip
		out = text(rule)
		self.assertTrue(out.startswith("Disabled: would open a warning incident"))
		self.assertIn("Its channels are all disabled: it notifies nobody.", out)
		self.assertIn("Not acknowledged after 15 min, it also notifies PagerDuty.", out)
		rule["escalation_channels"] = []
		self.assertIn("It would escalate after 15 min, but has no enabled escalation channel.", text(rule))

	def test_a_half_filled_form_still_reads(self):
		# a new rule, a field being typed: never an error
		for rule in ({}, {"signal_type": "metric", "threshold": "", "window_minutes": None},
		             {"signal_type": "sequence"}, {"threshold": "abc", "active_from": "22:00", "active_to": "late"}):  # fmt: skip
			self.assertTrue(text(rule).startswith("Opens a warning incident when "))
		self.assertIn("(no metric set)", text({}))

	def test_every_preset_reads(self):
		for preset in presets.PRESETS:
			out = text(preset)
			self.assertNotIn("None", out, preset["rule_name"])
			self.assertTrue(out.endswith("."), preset["rule_name"])


if __name__ == "__main__":
	unittest.main()
