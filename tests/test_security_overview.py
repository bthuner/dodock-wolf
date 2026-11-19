import unittest
from datetime import datetime, timedelta

from dodock_wolf.wolf import security_overview as so

NOW = datetime(2026, 11, 19, 12, 0)


class ScoreRows(unittest.TestCase):
	def test_worst_first_and_unscored_last_never_zero(self):
		rows = so.score_rows(
			["a.example.com", "b.example.com", "new.example.com"],
			{"a.example.com": (82.0, NOW - timedelta(minutes=20)), "b.example.com": (41.0, NOW - timedelta(minutes=20)),
			 "gone.example.com": (60.0, NOW - timedelta(hours=30))},  # fmt: skip
			{"a.example.com": 79.0},
			NOW,
		)
		self.assertEqual([r["site"] for r in rows], ["b.example.com", "gone.example.com", "a.example.com", "new.example.com"])
		unscored = rows[-1]
		self.assertIsNone(unscored["score"])
		self.assertIsNone(unscored["at"])
		self.assertIsNone(unscored["change"])

	def test_change_only_when_a_score_was_recorded_a_day_earlier(self):
		rows = {r["site"]: r for r in so.score_rows([], {"a": (82.4, NOW), "b": (50.0, NOW)}, {"a": 85.0}, NOW)}
		self.assertEqual(rows["a"]["score"], 82)
		self.assertEqual(rows["a"]["change"], -3)
		self.assertIsNone(rows["b"]["change"])  # not "unchanged": nothing to compare with

	def test_no_change_when_the_current_score_is_not_newer_than_the_day_before(self):
		# the job stopped a day ago: the newest score is also the one of the "before" window
		rows = {r["site"]: r for r in so.score_rows([], {"a": (70.0, NOW - timedelta(hours=24)), "b": (70.0, NOW - timedelta(hours=23)),
		                                                 "c": (72.0, NOW - timedelta(hours=22))}, {"a": 70.0, "b": 70.0, "c": 70.0}, NOW)}  # fmt: skip
		self.assertIsNone(rows["a"]["change"])  # not "unchanged in 24 h"
		self.assertIsNone(rows["b"]["change"])  # the window's end itself
		self.assertEqual(rows["c"]["change"], 2)
		self.assertTrue(rows["a"]["late"])

	def test_a_zero_score_is_a_score(self):
		rows = so.score_rows(["a", "b"], {"a": (0.0, NOW)}, {"a": 0.0}, NOW)
		self.assertEqual([(r["site"], r["score"], r["change"]) for r in rows], [("a", 0, 0), ("b", None, None)])

	def test_late_after_missed_hourly_runs(self):
		rows = {r["site"]: r for r in so.score_rows([], {"fresh": (70, NOW - timedelta(hours=1)), "old": (70, NOW - timedelta(hours=4))}, {}, NOW)}
		self.assertFalse(rows["fresh"]["late"])
		self.assertTrue(rows["old"]["late"])


class SeverityCounts(unittest.TestCase):
	def test_exact_counts_and_empty_severity_as_info(self):
		counts = so.severity_counts([("critical", 2), ("warning", 1), (None, 3), ("critical", 1)])
		self.assertEqual(counts, {"critical": 3, "warning": 1, "info": 3, "total": 7})

	def test_nothing(self):
		self.assertEqual(so.severity_counts([]), {"critical": 0, "warning": 0, "info": 0, "total": 0})


class JournalState(unittest.TestCase):
	def test_signing_keeps_up(self):
		state = so.journal_state(12, NOW - timedelta(minutes=1), 2, NOW - timedelta(seconds=40), NOW)
		self.assertEqual((state["last_seq"], state["pending"], state["behind"]), (12, 2, False))

	def test_behind_when_an_entry_waits_more_than_five_minutes(self):
		state = so.journal_state(12, NOW - timedelta(minutes=30), 4, NOW - timedelta(minutes=6), NOW)
		self.assertTrue(state["behind"])

	def test_empty_journal(self):
		state = so.journal_state(0, None, 0, None, NOW)
		self.assertEqual(state, {"last_seq": None, "last_at": None, "pending": 0, "oldest_pending_at": None, "behind": False})

	def test_nothing_signed_yet_but_waiting(self):
		state = so.journal_state(0, None, 3, NOW - timedelta(minutes=10), NOW)
		self.assertIsNone(state["last_seq"])
		self.assertTrue(state["behind"])


class AgentSummary(unittest.TestCase):
	def test_counts_and_hosts_to_fix_as_monitoring_shows_them(self):
		setup = lambda failed, warnings: {"failed": failed, "warnings": warnings, "problems": []}  # noqa: E731
		agents = [
			{"kind": "agent", "state": "fresh", "hostname": "h2", "setup": setup(1, 0)},
			{"kind": "agent", "state": "fresh", "hostname": "h1", "setup": setup(0, 2)},
			{"kind": "agent", "state": "fresh", "hostname": "ok", "setup": setup(0, 0)},
			{"kind": "agent", "state": "fresh", "hostname": "new", "setup": None},
			# silent: its last report says nothing about now
			{"kind": "agent", "state": "stale", "hostname": "old", "setup": setup(3, 0)},
			{"kind": "agent", "state": "never_seen", "hostname": "x", "setup": None},
			{"kind": "satellite", "state": "fresh", "hostname": "s.example.com", "setup": None},
			{"kind": None, "state": "disabled", "hostname": "d", "setup": None},
		]
		out = so.agent_summary(agents)
		self.assertEqual(out["agents"], {"fresh": 4, "stale": 1, "never_seen": 1, "disabled": 1, "total": 7})
		self.assertEqual(out["satellites"], {"fresh": 1, "stale": 0, "never_seen": 0, "disabled": 0, "total": 1})
		self.assertEqual(out["setup_reported"], 3)
		self.assertEqual([h["hostname"] for h in out["to_fix"]], ["h1", "h2"])
		self.assertEqual(out["to_fix"][1], {"hostname": "h2", "failed": 1, "warnings": 0})


if __name__ == "__main__":
	unittest.main()
