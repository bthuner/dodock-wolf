import unittest
from datetime import datetime, timedelta

from dodock_wolf.wolf import sequences as s

T = datetime(2026, 11, 17, 10, 0)


def pair(value, a, b, a_min=0, b_min=12, **kw):
	return {"value": value, "a_name": a, "a_at": T + timedelta(minutes=a_min), "a_category": "web_attack_probe",
	        "b_name": b, "b_at": T + timedelta(minutes=b_min), "b_seen": T + timedelta(minutes=b_min),
	        "b_category": "new_admin_ip", "b_host": "web-1", "b_bench": "b", "b_site": "erp.example.com",
	        "a_ip": value, "b_ip": value, **kw}  # fmt: skip


class TestSequences(unittest.TestCase):
	def test_categories(self):
		self.assertEqual(s.categories("a\nb, c  d"), ["a", "b", "c", "d"])
		self.assertEqual(s.categories(None), [])

	def test_one_row_per_entity(self):
		rows = s.group([pair("45.33.32.1", "A1", "B1"), pair("45.33.32.1", "A2", "B2", b_min=20),
		                pair("45.33.32.1", "A1", "B2", b_min=20), pair("45.33.32.9", "A3", "B3")], "ip")  # fmt: skip
		by = {r["group_key"]: r for r in rows}
		self.assertEqual(set(by), {"ip=45.33.32.1", "ip=45.33.32.9"})
		row = by["ip=45.33.32.1"]
		self.assertEqual((row["value"], row["samples"]), (2, 2))  # two second events
		self.assertEqual(row["events"], ["A1", "B1", "A2", "B2"])
		self.assertEqual((row["first_at"], row["last_at"]), (T, T + timedelta(minutes=20)))
		self.assertEqual((row["site"], row["label"], row["gap_minutes"]), ("erp.example.com", "ip 45.33.32.1", 20))
		self.assertIn("web_attack_probe then new_admin_ip 20 min later, same ip 45.33.32.1 (2 times in 10 min)",
		              s.summary(row, 10))  # fmt: skip

	def test_ip_must_be_the_public_remote_address_of_both(self):
		self.assertEqual(s.group([pair("10.0.0.5", "A", "B")], "ip"), [])  # private
		self.assertEqual(s.group([pair("45.33.32.1", "A", "B", a_ip="198.51.100.7")], "ip"), [])  # the server's dest_ip
		self.assertEqual(s.group([pair("45.33.32.1", "A", "B", b_ip=None)], "ip"), [])

	def test_user_needs_the_same_site(self):
		same = pair("jane@example.com", "A", "B", a_site="erp.example.com")
		other = pair("administrator", "A", "B", a_site="other.example.com")
		self.assertEqual(len(s.group([same], "user")), 1)
		self.assertEqual(s.group([other], "user"), [])

	def test_linked_events_are_capped(self):
		pairs = [pair("45.33.32.1", f"A{i}", f"B{i}") for i in range(s.MAX_EVENTS)]
		(row,) = s.group(pairs, "ip")
		self.assertEqual((row["value"], len(row["events"])), (s.MAX_EVENTS, s.MAX_EVENTS))


if __name__ == "__main__":
	unittest.main()
