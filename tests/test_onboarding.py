import unittest

from dodock_wolf.wolf import onboarding

DONE = {"agents": 2, "fresh": 2, "setup_reported": 2, "setup_failing": 0, "scheduler_enabled": True, "tick_seconds": 60,
        "rules": 40, "channels": 3, "tested": True}  # fmt: skip


def by_id(facts):
	return {s["id"]: s for s in onboarding.steps(facts)}


class TestOnboarding(unittest.TestCase):
	def test_a_fresh_install_has_everything_to_do_in_order(self):
		items = onboarding.steps({})
		self.assertEqual([s["id"] for s in items], ["agent", "reporting", "host_setup", "scheduler", "rules", "channel", "test"])
		self.assertEqual([s["done"] for s in items], [False] * 7)
		self.assertEqual(items[0]["detail"], "No host agent has registered with this site yet.")
		self.assertEqual(items[0]["action"]["href"], "https://bthuner.github.io/dodock-wolf/install/wolf-agent")

	def test_a_working_site_is_done(self):
		summary = onboarding.summary(onboarding.steps(DONE))
		self.assertEqual((summary["done"], summary["total"]), (7, 7))

	def test_each_step_says_what_is_left(self):
		s = by_id({**DONE, "fresh": 1, "setup_failing": 1, "tick_seconds": 240, "channels": 0, "tested": False})
		self.assertEqual(s["reporting"]["detail"], "1 of 2 reporting")  # its own string: French agrees with 1
		self.assertTrue(s["reporting"]["done"])  # one is enough to go on
		self.assertEqual((s["host_setup"]["done"], s["host_setup"]["detail"]), (False, "1 host to fix"))
		self.assertEqual(s["scheduler"]["detail"], "Frappe's scheduler ticks every 240 s: set scheduler_tick_interval to 60.")
		self.assertFalse(s["scheduler"]["done"])
		self.assertFalse(s["channel"]["done"])
		self.assertFalse(s["test"]["done"])

	def test_a_host_not_checked_yet_keeps_the_step_open(self):
		s = by_id({**DONE, "setup_reported": 1})
		self.assertEqual((s["host_setup"]["done"], s["host_setup"]["detail"]),
		                 (False, "1 of 2 hosts checked; agents check their host every hour."))  # fmt: skip

	def test_an_unknown_tick_does_not_keep_the_list_up(self):
		s = by_id({**DONE, "tick_seconds": None})
		self.assertTrue(s["scheduler"]["done"])
		self.assertEqual(s["scheduler"]["detail"], "The scheduler is on; this Frappe does not say how often it ticks.")
		self.assertFalse(by_id({**DONE, "scheduler_enabled": False})["scheduler"]["done"])

	def test_no_setup_reported_yet_is_not_done(self):
		s = by_id({**DONE, "setup_reported": 0})
		self.assertEqual((s["host_setup"]["done"], s["host_setup"]["detail"]), (False, "Agents check their host every hour; none has reported yet."))

	def test_the_docs_follow_the_language(self):
		s = by_id({**DONE, "docs": "https://bthuner.github.io/dodock-wolf/fr", "scheduler_anchor": "rythme-du-planificateur"})
		self.assertEqual(s["scheduler"]["action"]["href"], "https://bthuner.github.io/dodock-wolf/fr/install/wolf-app#rythme-du-planificateur")


if __name__ == "__main__":
	unittest.main()
