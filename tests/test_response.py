import unittest

from dodock_wolf.wolf import response


def ev(category, payload, agent="agent-1", event_type="security", host="bench-01", block_agent="same", **extra):
	# block_host / block_agent: the attacked host and the Wolf Agent on it (api/response.py resolves them)
	return {"event_type": event_type, "category": category, "title": category, "agent": agent, "host": host,
	        "bench": None, "site": "erp.example.com", "payload": payload, "block_host": host,
	        "block_agent": agent if block_agent == "same" else block_agent, **extra}  # fmt: skip


class TestChecks(unittest.TestCase):
	def test_blockable(self):
		self.assertEqual(response.blockable("45.33.32.156"), (True, None))
		self.assertEqual(response.blockable("2a03:2880:f12f:83:face:b00c:0:25de"), (True, None))
		for bad in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "::1", "fe80::1", "0.0.0.0", "198.51.100.7", "x", "::ffff:10.0.0.1"):
			with self.subTest(bad):
				self.assertFalse(response.blockable(bad)[0])

	def test_check(self):
		self.assertIsNone(response.check("block_ip", "45.33.32.156", hours=24))
		self.assertIn("1 to 168", response.check("block_ip", "45.33.32.156", hours=500))
		self.assertIn("private", response.check("block_ip", "10.1.2.3"))
		self.assertIn("protected", response.check("disable_user", "Administrator"))
		self.assertIn("own account", response.check("disable_user", "ops@example.com", approver="OPS@example.com"))
		self.assertIsNone(response.check("revoke_api_keys", "intruder@example.com", approver="ops@example.com"))
		self.assertIn("unknown action", response.check("rm_rf", "x"))
		self.assertEqual(response.check("block_ip", ""), "no target")


class TestSuggest(unittest.TestCase):
	def test_ip_blocks_need_someone_on_the_host(self):
		events = [
			ev("ssh_failed_login", {"ip": "45.33.32.156"}),
			ev("ssh_failed_login", {"ip": "45.33.32.156"}),  # same address, same agent: once
			ev("web_attack_probe", {"ip": "45.33.32.156"}, agent="agent-2", host="bench-02"),
			ev("web_attack_probe", {"ip": "10.0.0.9"}),  # private: never proposed
			ev("frappe_failed_login", {"ip": "45.33.32.157", "user": "a@example.com"}, agent=None),  # no agent to block
			ev("traceback", {"ip": "45.33.32.158"}, event_type="error"),
		]
		blocks = [(p["target"], p["agent"]) for p in response.suggest(events) if p["action"] == "block_ip"]
		self.assertEqual(blocks, [("45.33.32.156", "agent-1"), ("45.33.32.156", "agent-2")])

	def test_behind_a_proxy_only_ssh_blocks_on_the_host(self):
		# a Press app server behind its proxy: a web client's packets come from the proxy there
		def proxied(category, ip):
			return {**ev(category, {"ip": ip}, host="f1"), "block_proxy": "10.0.0.3"}

		events = [proxied("web_attack_probe", "45.33.32.156"), proxied("frappe_failed_login", "45.33.32.156"),
		          proxied("api_key_new_ip", "45.33.32.157"), proxied("ssh_failed_login", "45.33.32.158"),
		          proxied("web_attack_probe", "45.33.32.158"), proxied("web_attack_probe", "10.0.0.9")]  # fmt: skip
		blocks = [p["target"] for p in response.suggest(events) if p["action"] == "block_ip"]
		self.assertEqual(blocks, ["45.33.32.158"])  # SSH reaches the host itself
		held = response.held_blocks(events)
		self.assertEqual(held, [{"target": "45.33.32.156", "host": "f1", "via_proxy": "10.0.0.3"},
		                        {"target": "45.33.32.157", "host": "f1", "via_proxy": "10.0.0.3"}])  # fmt: skip
		# direct packets: an accepted SSH login, Wazuh, a network IDS alert on the packet's own source
		direct = [proxied("ssh_accepted", "45.33.32.160"), proxied("hids_alert", "45.33.32.161"),
		          {**proxied("network_ids_alert", "45.33.32.162"), "payload": {"ip": "45.33.32.162", "src_ip": "45.33.32.162"}},
		          {**proxied("network_ids_alert", "45.33.32.163"), "payload": {"ip": "45.33.32.163", "src_ip": "10.0.0.3"}}]  # fmt: skip
		self.assertEqual([p["target"] for p in response.suggest(direct)], ["45.33.32.160", "45.33.32.161", "45.33.32.162"])
		self.assertEqual([h["target"] for h in response.held_blocks(direct)], ["45.33.32.163"])  # an X-Forwarded-For client
		# no proxy: proposed as before, nothing held
		plain = [ev("web_attack_probe", {"ip": "45.33.32.156"})]
		self.assertEqual(len(response.suggest(plain)), 1)
		self.assertEqual(response.held_blocks(plain), [])

	def test_wazuh_blocks_where_no_wolf_agent_runs(self):
		# a Wazuh alert about web-02, sent by the integration: no Wolf Agent on web-02
		events = [ev("hids_alert", {"ip": "45.33.32.159"}, agent="wazuh-integration", host="web-02", block_agent=None),
		          ev("ssh_failed_login", {"ip": "45.33.32.156"})]  # fmt: skip
		def blocks(**kw):
			return [(p["target"], p["host"], p["agent"], p["executors"]) for p in response.suggest(events, **kw)
			        if p["action"] == "block_ip"]  # fmt: skip
		self.assertEqual(blocks(), [("45.33.32.156", "bench-01", "agent-1", ["wolf_agent"])])
		self.assertEqual(blocks(block_with="wazuh", wazuh=True),
		                 [("45.33.32.159", "web-02", None, ["wazuh"]), ("45.33.32.156", "bench-01", None, ["wazuh"])])  # fmt: skip
		self.assertEqual(blocks(block_with="both", wazuh=True),
		                 [("45.33.32.159", "web-02", None, ["wazuh"]),
		                  ("45.33.32.156", "bench-01", "agent-1", ["wolf_agent", "wazuh"])])  # fmt: skip
		self.assertEqual(blocks(block_with="wazuh", wazuh=False), [])  # Wazuh not set up: nobody can block

	def test_only_external_alerts_name_another_host(self):
		probe = {"category": "web_attack_probe", "host": "web-02"}
		self.assertEqual(response.attacked_host(probe, "agent", "web-01"), "web-01")  # its own host, whatever it says
		self.assertEqual(response.attacked_host({**probe, "category": "hids_alert"}, "agent", "wazuh-mgr"), "web-02")
		self.assertEqual(response.attacked_host({**probe, "category": "network_ids_alert"}, "agent", "sensor"), "web-02")
		self.assertEqual(response.attacked_host(probe, "integration", "wazuh-mgr"), "web-02")
		self.assertEqual(response.attacked_host(probe, None, None), "web-02")  # the site's own events

	def test_executors(self):
		self.assertEqual(response.executors("wolf_agent", "a", True), ["wolf_agent"])
		self.assertEqual(response.executors("both", None, True), ["wazuh"])
		self.assertEqual(response.executors(None, "a", False), ["wolf_agent"])
		self.assertEqual(response.executors("wazuh", "a", False), [])

	def test_user_actions_for_site_events(self):
		events = [
			ev("api_key_generated", {"user": "intruder@example.com"}, agent=None),
			ev("privileged_user", {"user": "Administrator"}, agent=None),  # protected
			ev("ssh_failed_login", {"user": "root", "ip": "45.33.32.156"}),  # host account, not a site user
		]
		users = [(p["action"], p["target"]) for p in response.suggest(events) if p["action"] != "block_ip"]
		self.assertEqual(users, [("disable_user", "intruder@example.com"), ("logout_sessions", "intruder@example.com"),
		                         ("revoke_api_keys", "intruder@example.com")])  # fmt: skip

	def test_user_actions_for_a_satellite_s_users(self):
		# a satellite applies them itself; an agent's event (a host account) never proposes one
		events = [
			ev("api_key_new_ip", {"user": "intruder@example.com"}, agent="WAG-SAT", sender_kind="satellite", site="b.example.com"),
			ev("api_key_new_ip", {"user": "intruder@example.com"}, agent=None),  # the same address on the Wolf site
			ev("frappe_failed_login", {"user": "someone@example.com"}, agent="WAG-1", sender_kind="agent"),
		]
		users = [(p["action"], p["target"], p["agent"], p["site"]) for p in response.suggest(events) if p["action"] == "disable_user"]
		self.assertEqual(users, [("disable_user", "intruder@example.com", "WAG-SAT", "b.example.com"),
		                         ("disable_user", "intruder@example.com", None, "erp.example.com")])  # fmt: skip
		self.assertEqual(response.label("disable_user", "intruder@example.com", site="b.example.com"),
		                 "Disable user intruder@example.com on b.example.com")  # fmt: skip

	def test_bounded(self):
		events = [ev("web_attack_probe", {"ip": f"45.33.{i // 250}.{i % 250 + 1}"}) for i in range(100)]
		self.assertEqual(len(response.suggest(events)), response.MAX_PROPOSALS)

	def test_label(self):
		self.assertEqual(response.label("block_ip", "45.33.32.156", 24, "bench-01"), "Block 45.33.32.156 for 24 h on bench-01")
		self.assertEqual(response.label("block_ip", "45.33.32.156", 24, "web-02", ["wazuh"]),
		                 "Block 45.33.32.156 for 24 h on web-02 with Wazuh")  # fmt: skip


if __name__ == "__main__":
	unittest.main()
