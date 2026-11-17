import unittest

from dodock_wolf.wolf import wazuh_ar as w


class TestWazuhActiveResponse(unittest.TestCase):
	def test_command_needs_a_timeout(self):
		self.assertEqual(w.command_seconds("firewall-drop86400"), 86400)
		self.assertEqual(w.command_seconds("firewall-drop60"), 60)
		self.assertIsNone(w.command_seconds("restart-wazuh0"))
		self.assertIsNone(w.command_seconds("firewall-drop"))
		self.assertIsNone(w.command_error("firewall-drop86400"))
		self.assertIn("never removed", w.command_error("!firewall-drop"))
		self.assertIn("no timeout", w.command_error("firewall-drop"))
		self.assertIn("longer than 168 h", w.command_error("firewall-drop999999"))
		self.assertIn("set the Wazuh", w.command_error(""))

	def test_find_agent_by_name_then_address(self):
		agents = [{"id": "000", "name": "wazuh-manager", "ip": "127.0.0.1"}, {"id": "001", "name": "web-01", "ip": "10.0.0.5"},
		          {"id": "002", "name": "db", "ip": "10.0.0.6"}]  # fmt: skip
		self.assertEqual(w.find_agent(agents, {"WEB-01"}, set()), "001")
		self.assertEqual(w.find_agent(agents, {"db-01.example.com"}, {"10.0.0.6"}), "002")
		self.assertIsNone(w.find_agent(agents, {"wazuh-manager"}, {"127.0.0.1"}))  # the manager never blocks
		self.assertIsNone(w.find_agent(agents, {"nope"}, {"10.9.9.9"}))

	def test_body_and_answer(self):
		self.assertEqual(w.block_body("firewall-drop60", "203.0.113.5"),
		                 {"command": "firewall-drop60", "alert": {"data": {"srcip": "203.0.113.5"}}})  # fmt: skip
		with self.assertRaises(ValueError):
			w.block_body("firewall-drop60", "203.0.113.5; rm -rf /")
		# the answers a Wazuh 4.9.2 manager gave
		ok = {"data": {"affected_items": ["001"], "total_affected_items": 1, "failed_items": []}, "error": 0}
		self.assertEqual(w.applied(ok, "001"), (True, "sent to Wazuh agent 001"))
		manager = {"data": {"affected_items": [], "failed_items": [{"error": {"code": 1703,
		           "message": "Action not available for Manager (agent 000)"}, "id": ["000"]}]}, "error": 1}  # fmt: skip
		self.assertEqual(w.applied(manager, "000"), (False, "Action not available for Manager (agent 000)"))


if __name__ == "__main__":
	unittest.main()
