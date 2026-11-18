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
		for caps in d.get("CapabilityBoundingSet", []):  # a set must keep what sudo and nft need
			for cap in ("CAP_SETUID", "CAP_SETGID", "CAP_NET_ADMIN"):
				self.assertIn(cap, caps.split(), f"CapabilityBoundingSet= without {cap}")
		self.assertNotIn("SystemCallFilter", d, "a syscall filter can kill sudo's setuid calls")
		# the helpers change the host's firewall: not a private network, netlink kept
		self.assertNotIn(d.get("PrivateNetwork", ["no"])[-1].lower(), ("yes", "true", "1", "on"), "PrivateNetwork= hides the host's firewall")
		for families in d.get("RestrictAddressFamilies", []):
			self.assertIn("AF_NETLINK", families.split(), "nft talks netlink")

	def test_helpers_can_write_what_they_write(self):
		# sudo's child shares the unit's mount namespace: ProtectSystem=strict applies to it too
		self.assertIn("-/var/lib/wolf-block", directives(UNIT)["ReadWritePaths"])  # wolf-block-fail2ban's expiries

	def test_still_hardened(self):
		d = directives(UNIT)
		self.assertEqual(d["ProtectSystem"], ["strict"])
		self.assertEqual(d["ProtectHome"], ["read-only"])
		self.assertEqual(d["PrivateTmp"], ["yes"])
		self.assertEqual(d["ReadWritePaths"][0], "/var/lib/wolf-agent")
		self.assertTrue(all(p == "/var/lib/wolf-agent" or p.lstrip("-").startswith("/var/lib/") for p in d["ReadWritePaths"]))

class TestPilotExportUnit(unittest.TestCase):
	def test_its_folder_keeps_the_agent_group(self):
		# on a group mismatch systemd chowns a StateDirectory to the unit's user and group at every
		# start: root:root for a moment, when the agent could not read the export (dev/pilot, 532 of
		# 1862 reads failed while it ran)
		d = directives(os.path.join(os.path.dirname(__file__), "..", "wolf-pilot-export.service"))
		self.assertEqual(d.get("StateDirectory"), ["wolf-pilot-export"])
		self.assertEqual(d.get("Group"), ["wolf-agent"])
		self.assertNotIn("User", d)  # root: it reads each bench as its own user

if __name__ == "__main__":
	unittest.main()
