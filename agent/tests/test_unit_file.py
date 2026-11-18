"""agent/wolf-agent.service must let sudo run: the agent starts its root helpers through sudo
(wolf-block for approved blocks, wolf-outbound-log), and systemd settings that forbid gaining
privileges make every `sudo -n` fail ("The no new privileges flag is set")."""

import os
import unittest

from wolf_agent import config

UNIT = os.path.join(os.path.dirname(__file__), "..", "wolf-agent.service")


def directives(path):
	out = {}
	with open(path) as f:
		for line in f:
			line = line.strip()
			if line and not line.startswith(("#", ";", "[")) and "=" in line:
				key, value = line.split("=", 1)
				out.setdefault(key.strip(), []).append(value.strip())
	return out


class TestUnitFile(unittest.TestCase):
	def test_sudo_can_run(self):
		d = directives(UNIT)
		self.assertTrue(config.DEFAULTS["response"]["command"][0] == "sudo", "the response command goes through sudo")
		for key in ("NoNewPrivileges", "RestrictSUIDSGID", "PrivateUsers", "DynamicUser"):
			self.assertNotIn(d.get(key, ["no"])[-1].lower(), ("yes", "true", "1", "on"), f"{key}= blocks sudo")
		self.assertNotIn("", d.get("CapabilityBoundingSet", ["x"]), "an empty CapabilityBoundingSet= blocks sudo")
		self.assertNotIn("SystemCallFilter", d, "a syscall filter can kill sudo's setuid calls")

	def test_still_hardened(self):
		d = directives(UNIT)
		self.assertEqual(d["ProtectSystem"], ["strict"])
		self.assertEqual(d["ProtectHome"], ["read-only"])
		self.assertEqual(d["PrivateTmp"], ["yes"])
		self.assertEqual(d["ReadWritePaths"], ["/var/lib/wolf-agent"])


if __name__ == "__main__":
	unittest.main()
