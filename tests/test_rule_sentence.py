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
			"condition no longer holds; if it matches again within 1 h of being resolved, the same incident reopens. "
			"It notifies ntfy and 2 Email."
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

	def test_what_the_evaluator_does_besides(self):
		# a cooldown reopens whoever resolved the incident
		self.assertIn("It stays open until someone resolves it; if it matches again within 30 min of being resolved, the same "
		              "incident reopens.", text({"auto_resolve": 0, "cooldown_minutes": 30}))  # fmt: skip
		# [from, to) is empty: the rule never runs
		self.assertIn("It is never checked: Active From and Active To are both 02:00.",
		              text({"active_from": "02:00:00", "active_to": "2:00"}))  # fmt: skip
		self.assertIn("between 02:00 and 02:00:30", text({"active_from": "02:00:00", "active_to": "02:00:30"}))
		# a pager closes its own alert even when resolutions are not sent
		self.assertIn("It notifies PagerDuty (PagerDuty still hears when it is acknowledged or resolved).",
		              text({"channels": [{"channel_type": "PagerDuty", "enabled": 1}], "notify_on_resolve": 0}))  # fmt: skip
		rows = [{"channel_type": "Email"}, {"channel_type": "ntfy"}, {"channel_type": "Email"}]
		self.assertIn("It notifies 2 Email and ntfy", text({"channels": rows}))
		# Min Samples counts events for an event rule, its field hidden or not
		self.assertIn("at least 4 distinct events", text({"signal_type": "event", "event_type": "error", "min_samples": 4}))
		self.assertIn("over the last (no window set)", text({"window_minutes": 0}))

	def test_garbage_from_a_direct_call_never_raises(self):
		for rule in ({"window_minutes": "1e999"}, {"active_from": "1e999", "active_to": "1"}, {"channels": "x"},
		             {"operator": [">"], "use_resolve_threshold": 1, "group_by": {}, "signal_type": ["x"]},
		             {"channels": [None, 3]}, {"aggregation": {}, "sequence_entity": []}):  # fmt: skip
			self.assertTrue(text(rule).startswith("Opens a warning incident when "), rule)

	def test_a_translation_moves_the_values_with_its_words(self):
		french = {
			"Opens a {0} incident when {1}": "Ouvre un incident {0} quand {1}",
			"{0} over the last {1} is {2} {3}": "{0} sur les {1} dernières est {2} {3}",
			"the lowest {0}": "la plus basse valeur de {0}",
			"above": "supérieure à",
			"{0} min": "{0} min",
			"per host": "par hôte",
		}
		head = rule_sentence.describe({"severity": "critical", "aggregation": "min", "metric_name": "disk", "threshold": 90,
		                               "group_by": "host"}, lambda t: french.get(t, t))[0]  # fmt: skip
		self.assertEqual("".join(t for t, _v in head),
		                 "Ouvre un incident critical quand la plus basse valeur de disk sur les 5 min dernières est supérieure à 90, par hôte.")  # fmt: skip
		self.assertEqual([t for t, v in head if v], ["critical", "disk", "5 min", "supérieure à", "90", "par hôte"])

	def test_every_preset_reads(self):
		for preset in presets.PRESETS:
			out = text(preset)
			self.assertNotIn("None", out, preset["rule_name"])
			self.assertTrue(out.endswith("."), preset["rule_name"])


if __name__ == "__main__":
	unittest.main()
