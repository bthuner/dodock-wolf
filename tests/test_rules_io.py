import datetime
import unittest

from dodock_wolf.wolf import rules_io

# a slice of the Wolf Alert Rule and Wolf Alert Channel DocTypes: (fieldtype, default)
FIELDS = {
	"rule_name": ("Data", None), "enabled": ("Check", "1"), "signal_type": ("Select", "metric"),
	"severity": ("Select", "warning", "info\nwarning\ncritical"), "is_preset": ("Check", "0"), "metric_name": ("Data", None),
	"aggregation": ("Select", "avg"), "operator": ("Select", ">"), "threshold": ("Float", None),
	"window_minutes": ("Int", "5"), "group_by": ("Select", "none"), "active_from": ("Time", None),
	"active_to": ("Time", None), "first_categories": ("Small Text", None), "last_fired": ("Datetime", None),
	"evaluation_state": ("Long Text", None),
}  # fmt: skip
CHANNEL = {
	"channel_type": ("Select", None), "enabled": ("Check", "1"),
	"recipients": ("Small Text", None), "webhook_url": ("Data", None), "ntfy_server": ("Data", None),
	"ntfy_topic": ("Data", None), "ntfy_token": ("Password", None), "chat_webhook_url": ("Password", None),
}  # fmt: skip
SECRETS = {"ntfy": ("ntfy_token",), "Slack": ("chat_webhook_url",)}


def stored(**over):
	rule = {"rule_name": "Worker queue backlog", "enabled": 1, "signal_type": "metric", "severity": "warning", "is_preset": 1,
	        "metric_name": "queue_length", "aggregation": "max", "operator": ">", "threshold": 90.0,
	        "window_minutes": 10, "group_by": "host", "active_from": None, "active_to": None,
	        "last_fired": "2026-11-18 20:00:00", "evaluation_state": '{"x": 1}',
	        "channels": [{"name": "c1", "channel_type": "ntfy", "enabled": 1, "ntfy_server": "https://ntfy.sh",
	                      "ntfy_topic": "ops", "ntfy_token": "*****"}],
	        "escalation_channels": []}  # fmt: skip
	rule.update(over)
	return rule


class TestExport(unittest.TestCase):
	def test_only_what_differs_from_the_defaults_and_no_secret(self):
		doc = rules_io.export_rules([stored()], FIELDS, CHANNEL, SECRETS)
		self.assertEqual(doc["version"], 1)
		rule = doc["rules"][0]
		self.assertEqual(rule, {
			"rule_name": "Worker queue backlog", "enabled": 1, "metric_name": "queue_length", "aggregation": "max",
			"threshold": 90, "window_minutes": 10, "group_by": "host",
			"channels": [{"channel_type": "ntfy", "ntfy_server": "https://ntfy.sh", "ntfy_topic": "ops"}],
		})  # fmt: skip
		self.assertNotIn("ntfy_token", str(doc))  # secrets, runtime state and the preset marker stay out
		self.assertNotIn("evaluation_state", rule)
		self.assertNotIn("is_preset", rule)

	def test_times_and_text(self):
		rule = stored(active_from=datetime.timedelta(hours=1), active_to="4:0", first_categories="a\r\nb ")
		out = rules_io.export_rules([rule], FIELDS, CHANNEL, SECRETS)["rules"][0]
		self.assertEqual((out["active_from"], out["active_to"], out["first_categories"]), ("01:00:00", "04:00:00", "a\nb"))


class TestImport(unittest.TestCase):
	def test_parse_rejects_what_would_silently_do_nothing(self):
		with self.assertRaises(rules_io.DocumentError):
			rules_io.parse({"rules": []}, FIELDS, CHANNEL)  # no version
		with self.assertRaises(rules_io.DocumentError):
			rules_io.parse([1, 2], FIELDS, CHANNEL)
		doc = {"version": 1, "rules": [
			{"rule_name": "A", "treshold": 3},  # a typo
			{"rule_name": "A"},  # twice
			{"enabled": 1},  # no name
			{"rule_name": "B", "channels": [{"channel_type": "ntfy", "topic": "x"}, {"enabled": 1}]},
			{"rule_name": "C", "last_fired": "now"},  # runtime: not importable
		]}  # fmt: skip
		errors = [errs for _rule, errs in rules_io.parse(doc, FIELDS, CHANNEL)]
		self.assertEqual(errors, [
			["unknown field(s): treshold"],
			["this rule_name appears twice in the document"],
			["a rule needs a rule_name"],
			["channels #1: unknown field(s): topic", "channels #2: a channel needs a channel_type"],
			["unknown field(s): last_fired"],
		])  # fmt: skip

	def test_a_left_out_field_goes_back_to_its_default(self):
		wanted = rules_io.target({"rule_name": "Worker queue backlog", "metric_name": "queue_length", "threshold": 95}, FIELDS)
		self.assertEqual((wanted["aggregation"], wanted["window_minutes"], wanted["threshold"], wanted["enabled"]), ("avg", 5, 95, 1))
		self.assertNotIn("evaluation_state", wanted)
		self.assertEqual(rules_io.changes(stored(), wanted, FIELDS), ["aggregation", "group_by", "threshold", "window_minutes"])

	def test_an_export_imports_back_unchanged(self):
		rule = stored()
		doc = rules_io.export_rules([rule], FIELDS, CHANNEL, SECRETS)
		parsed = rules_io.parse(doc, FIELDS, CHANNEL)[0][0]
		self.assertEqual(rules_io.changes(rule, rules_io.target(parsed, FIELDS), FIELDS), [])
		rows, notes = rules_io.merge_channels(parsed["channels"], rule["channels"], CHANNEL, SECRETS)
		self.assertFalse(rules_io.channel_rows_differ(rule["channels"], rows, CHANNEL, SECRETS))
		self.assertEqual((rows[0]["name"], rows[0]["ntfy_token"], notes), ("c1", "*****", []))  # its row, its secret

	def test_a_new_channel_without_its_secret_comes_in_disabled(self):
		incoming = [{"channel_type": "ntfy", "ntfy_server": "https://ntfy.sh", "ntfy_topic": "ops"},
		            {"channel_type": "ntfy", "ntfy_server": "https://ntfy.sh", "ntfy_topic": "night"},
		            {"channel_type": "Email", "recipients": "ops@example.com"}]  # fmt: skip
		rows, notes = rules_io.merge_channels(incoming, stored()["channels"], CHANNEL, SECRETS)
		self.assertEqual([(r.get("name"), r["enabled"]) for r in rows], [("c1", 1), (None, 0), (None, 1)])
		self.assertEqual(notes, ["ntfy #2: imported disabled, set ntfy_token in the form, then enable it"])
		self.assertTrue(rules_io.channel_rows_differ(stored()["channels"], rows, CHANNEL, SECRETS))



class TestReviewCases(unittest.TestCase):
	def test_values_a_field_cannot_take(self):
		doc = {"version": 1, "rules": [{"rule_name": "A", "severity": "high", "threshold": "abc", "window_minutes": 2.5,
		       "active_from": 1320, "active_to": "25:00", "enabled": "yes"}]}  # fmt: skip
		errors = rules_io.parse(doc, FIELDS, CHANNEL)[0][1]
		self.assertEqual(errors, [
			"severity: 'high' is not one of info, warning, critical",
			"threshold: expected a number, got 'abc'",
			"window_minutes: expected a whole number, got 2.5",
			"active_from: write times quoted, as '22:00' (YAML reads an unquoted 22:00 as a number)",
			"active_to: '25:00' is not a time of day",
			"enabled: expected 0 or 1, got 'yes'",
		])  # fmt: skip
		ok = {"version": 1, "rules": [{"rule_name": "B", "severity": "critical", "threshold": "90", "active_from": "22:00"}]}
		self.assertEqual(rules_io.parse(ok, FIELDS, CHANNEL)[0][1], [])

	def test_a_secret_in_a_file_is_refused(self):
		doc = {"version": 1, "rules": [{"rule_name": "A", "channels": [{"channel_type": "ntfy", "ntfy_token": "tk"}]}]}
		self.assertEqual(rules_io.parse(doc, FIELDS, CHANNEL)[0][1],
		                 ["channels #1: ntfy_token: secrets are not read from a file (keep them out of git): set them in the form"])  # fmt: skip

	def test_every_password_field_stays_out_of_an_export(self):
		# a Password field of another type, left on the row: still not written
		rule = stored(channels=[{"name": "c1", "channel_type": "ntfy", "ntfy_server": "https://n", "ntfy_topic": "t",
		                         "ntfy_token": "*****", "chat_webhook_url": "https://hooks.slack.com/x"}])  # fmt: skip
		self.assertNotIn("hooks.slack.com", str(rules_io.export_rules([rule], FIELDS, CHANNEL, SECRETS)))

	def test_reordered_channels_keep_their_own_secrets(self):
		existing = [{"name": "a", "channel_type": "ntfy", "ntfy_server": "https://n", "ntfy_topic": "A", "ntfy_token": "tok-a"},
		            {"name": "b", "channel_type": "ntfy", "ntfy_server": "https://n", "ntfy_topic": "B", "ntfy_token": "tok-b"}]  # fmt: skip
		incoming = [{"channel_type": "ntfy", "ntfy_server": "https://n", "ntfy_topic": "B"},
		            {"channel_type": "ntfy", "ntfy_server": "https://n", "ntfy_topic": "A"}]  # fmt: skip
		rows, notes = rules_io.merge_channels(incoming, existing, CHANNEL, SECRETS)
		self.assertEqual([(r["ntfy_topic"], r["name"], r["ntfy_token"]) for r in rows], [("B", "b", "tok-b"), ("A", "a", "tok-a")])
		self.assertEqual(notes, [])

	def test_a_deleted_slack_row_never_lends_its_webhook(self):
		# Slack has nothing but its secret webhook to tell rows apart: after a deletion, position says nothing
		existing = [{"name": "s1", "channel_type": "Slack", "enabled": 1, "chat_webhook_url": "*****"},
		            {"name": "s2", "channel_type": "Slack", "enabled": 1, "chat_webhook_url": "*****"}]  # fmt: skip
		rows, notes = rules_io.merge_channels([{"channel_type": "Slack"}], existing, CHANNEL, SECRETS)
		self.assertEqual((rows[0].get("name"), rows[0]["enabled"]), (None, 0))
		self.assertIn("set chat_webhook_url in the form", notes[0])
		# the same number of rows: kept by position, and said so when it is more than one
		rows, notes = rules_io.merge_channels([{"channel_type": "Slack"}, {"channel_type": "Slack"}], existing, CHANNEL, SECRETS)
		self.assertEqual([r["name"] for r in rows], ["s1", "s2"])
		self.assertEqual(notes, ["Slack: 2 rows kept their stored secrets by position: check their order in the form"])


class TestLegacyFiles(unittest.TestCase):
	def test_a_v0_1_export_with_digests_still_imports(self):
		doc = {"version": 1, "rules": [{"rule_name": "A", "channels": [{"channel_type": "Email", "recipients": "a@example.com",
		                                                                "digest": "hourly"}]}]}  # fmt: skip
		rule, errors = rules_io.parse(doc, FIELDS, CHANNEL)[0]
		self.assertEqual(errors, [])
		self.assertNotIn("digest", rule["channels"][0])


if __name__ == "__main__":
	unittest.main()
