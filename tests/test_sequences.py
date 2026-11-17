import unittest
from datetime import datetime, timedelta

from dodock_wolf.wolf import sequences as s

T = datetime(2026, 11, 17, 10, 0)


def pair(value, b, a=None, a_min=0, b_min=12, **kw):
	"""A query_sequence row: second event `b`, the newest first event `a` last seen at `a_min`."""
	row = {"value": value, "a_at": T + timedelta(minutes=a_min), "a_last": T + timedelta(minutes=a_min),
	       "b_name": b, "b_at": T + timedelta(minutes=b_min), "b_last": T + timedelta(minutes=b_min),
	       "b_seen": T + timedelta(minutes=b_min), "b_category": "new_admin_ip", "b_host": "web-1", "b_bench": "b",
	       "b_site": "erp.example.com", "b_ip": value, **kw}  # fmt: skip
	if a:
		row.update(a_name=a, a_category="web_attack_probe")
	return row


class TestSequences(unittest.TestCase):
	def test_categories(self):
		self.assertEqual(s.categories("a\nb, c  d"), ["a", "b", "c", "d"])
		self.assertEqual(s.categories(None), [])

	def test_gap_is_measured_to_the_latest_second_occurrence(self):
		self.assertTrue(s.keep(pair("45.33.32.1", "B", b_min=60), "ip", 60))
		self.assertFalse(s.keep(pair("45.33.32.1", "B", b_min=61), "ip", 60))
		# a repeat of the second event, folded into one record that first came long before
		repeat = pair("jane@example.com", "B", a_min=100, b_min=110, b_at=T)
		self.assertTrue(s.keep(repeat, "user", 60))
		# a first event that went on after the second started still came before it
		self.assertTrue(s.keep(pair("web-1", "B", a_min=30, b_min=12), "host", 60))

	def test_ip_must_be_the_public_remote_address_of_the_second(self):
		self.assertTrue(s.keep(pair("45.33.32.1", "B"), "ip", 60))
		self.assertFalse(s.keep(pair("10.0.0.5", "B"), "ip", 60))  # private
		self.assertFalse(s.keep(pair("45.33.32.1", "B", b_ip="198.51.100.7"), "ip", 60))  # not its remote address
		self.assertFalse(s.keep(pair("45.33.32.1", "B", b_ip=None), "ip", 60))
		self.assertTrue(s.keep(pair("web-1", "B", b_ip=None), "host", 60))

	def test_one_row_per_entity(self):
		rows = s.group([pair("45.33.32.1", "B1", "A1"), pair("45.33.32.1", "B2", "A2", a_min=5, b_min=20),
		                pair("45.33.32.1", "B3", b_min=15), pair("45.33.32.9", "B4", "A4")], "ip")  # fmt: skip
		by = {r["group_key"]: r for r in rows}
		self.assertEqual(set(by), {"ip=45.33.32.1", "ip=45.33.32.9"})
		row = by["ip=45.33.32.1"]
		self.assertEqual((row["value"], row["samples"]), (3, 3))  # three second events
		self.assertEqual(row["events"], ["A1", "B1", "A2", "B2", "B3"])  # B3's first event was not looked up
		self.assertEqual((row["first_at"], row["last_at"]), (T, T + timedelta(minutes=20)))
		self.assertEqual((row["site"], row["label"], row["gap_minutes"]), ("erp.example.com", "ip 45.33.32.1", 15))
		self.assertEqual(s.summary(row, 10),
		                 "web_attack_probe then new_admin_ip 15 min later, same ip 45.33.32.1 (3 times in 10 min)")  # fmt: skip
		(lone,) = s.group([pair("45.33.32.1", "B")], "ip")
		self.assertTrue(s.summary(lone, 10).startswith("first event then new_admin_ip"))

	def test_linked_events_are_capped(self):
		pairs = [pair("45.33.32.1", f"B{i}", f"A{i}") for i in range(s.MAX_EVENTS)]
		(row,) = s.group(pairs, "ip")
		self.assertEqual((row["value"], len(row["events"])), (s.MAX_EVENTS, s.MAX_EVENTS))


if __name__ == "__main__":
	unittest.main()
