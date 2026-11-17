import unittest

from dodock_wolf.wolf import attack, detectors as d


class TestDetectors(unittest.TestCase):
	def test_sides(self):
		self.assertEqual(d.detector_of("web_attack_probe"), ("web", "own"))
		self.assertEqual(d.detector_of("network_ids_alert"), ("web", "external"))
		self.assertEqual(d.detector_of("ssh_failed_login"), ("host", "own"))
		self.assertEqual(d.detector_of("hids_alert"), ("host", "external"))
		self.assertEqual(d.detector_of("web_sensitive_file_exposed"), (None, None))  # Suricata cannot see the answer
		self.assertEqual(d.other_side("web", "own"), ("network_ids_alert",))
		for detector in d.DETECTORS.values():
			for category in detector["own"] + detector["external"]:
				self.assertIn(category, attack.CATEGORIES)

	def test_mode_defaults_to_own(self):
		self.assertEqual(d.mode({}, "web"), "own")
		self.assertEqual(d.mode({"web_detection_mode": "bogus"}, "web"), "own")
		self.assertEqual(d.mode({"host_detection_mode": "external"}, "host"), "external")
		self.assertEqual(d.mode({"web_detection_mode": "both"}, None), "own")

	def test_same_finding_needs_a_common_technique_when_both_name_some(self):
		probe = {"mitre_attack": [{"id": "T1595.003"}, {"id": "T1190"}]}
		self.assertTrue(d.same_finding(probe, {"mitre_attack": [{"id": "T1190"}]}))
		self.assertTrue(d.same_finding(probe, {"mitre_attack": ["T1595.002"]}))  # sub-techniques count as their base
		self.assertFalse(d.same_finding(probe, {"mitre_attack": [{"id": "T1110"}]}))
		self.assertTrue(d.same_finding(probe, {}))  # an alert without techniques: the IP and the time decide
		self.assertTrue(d.same_finding(None, None))

	def test_only_alerts_that_watch_the_same_thing_stand_in(self):
		self.assertTrue(d.covers("host", {"groups": ["syslog", "sshd", "authentication_failed"]}))
		self.assertTrue(d.covers("host", {"mitre_attack": [{"id": "T1110.001"}]}))
		self.assertFalse(d.covers("host", {"groups": ["ossec", "syscheck"], "mitre_attack": [{"id": "T1565"}]}))  # file integrity
		self.assertTrue(d.covers("web", {"app_proto": "http"}))
		self.assertTrue(d.covers("web", {"http_hostname": "erp.example.com"}))
		self.assertTrue(d.covers("web", {"mitre_attack": [{"id": "T1190"}]}))
		self.assertFalse(d.covers("web", {"app_proto": "tls", "mitre_attack": [{"id": "T1071"}]}))  # a C2 alert
		self.assertFalse(d.covers("web", None))

	def test_source_labels(self):
		self.assertEqual([d.source_label(s) for s in ("suricata", "Wazuh", "frappe", "nginx", "sshd", None)],
		                 ["Suricata", "Wazuh", "Wolf site", "Wolf agent", "Wolf agent", "Wolf agent"])  # fmt: skip


if __name__ == "__main__":
	unittest.main()
