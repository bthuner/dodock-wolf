"""wolf-block.sh and wolf-block-fail2ban.sh, run for real with stub nft, fail2ban-client and systemd-run in PATH."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "wolf-block-fail2ban.sh")
NFT_SCRIPT = os.path.join(HERE, "..", "wolf-block.sh")

STUB = """#!/bin/sh
echo "$@" >> "{log}"
[ "$1" = status ] && [ "{jail}" = yes ] && exit 0
[ "$1" = status ] && exit 255
exit 0
"""


def read(path):
	with open(path) as f:
		return f.read()


@unittest.skipUnless(shutil.which("sh"), "needs a POSIX shell")
class TestFail2banHelper(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.mkdtemp()
		self.addCleanup(shutil.rmtree, self.dir)
		self.state = os.path.join(self.dir, "state", "fail2ban.state")
		self.log = os.path.join(self.dir, "calls.log")
		with open(SCRIPT) as f:
			script = f.read().replace("STATE=/var/lib/wolf-block/fail2ban.state", f"STATE={self.state}")
		self.script = os.path.join(self.dir, "wolf-block-fail2ban")
		with open(self.script, "w") as f:
			f.write(script)
		os.chmod(self.script, 0o755)
		self.bin = os.path.join(self.dir, "bin")
		os.mkdir(self.bin)

		# always shadow the host's systemd-run: a test must never schedule a real unit
		self.stub("systemd-run")

	def stub(self, name, jail="yes", code=0):
		path = os.path.join(self.bin, name)
		with open(path, "w") as f:
			f.write(STUB.format(log=self.log, jail=jail) if code == 0 else f"#!/bin/sh\nexit {code}\n")
		os.chmod(path, 0o755)

	def run_script(self, *args):
		env = {"PATH": f"{self.bin}:/usr/bin:/bin"}
		done = subprocess.run([self.script, *args], capture_output=True, text=True, env=env, timeout=20)
		calls = read(self.log).splitlines() if os.path.exists(self.log) else []
		return done, calls

	def test_ban_records_and_schedules_the_unban(self):
		self.stub("fail2ban-client")
		done, calls = self.run_script("45.33.32.156", "3600")
		self.assertEqual(done.returncode, 0, done.stderr)
		self.assertIn("banned 45.33.32.156 for 3600s in fail2ban jail wolf; unban scheduled", done.stdout)
		self.assertIn("set wolf banip 45.33.32.156", calls)
		timer = next(c for c in calls if c.startswith("--quiet"))
		self.assertIn("--on-active=3600s", timer)
		# the timer sweeps (unbans only what $STATE says is due), never a bare unbanip
		self.assertTrue(timer.endswith(f"{self.script} --sweep"), timer)
		addr, until = read(self.state).split()
		self.assertEqual(addr, "45.33.32.156")
		self.assertAlmostEqual(int(until), time.time() + 3600, delta=30)

	@unittest.skipIf(os.geteuid() == 0, "root writes through a read-only mode")
	def test_no_ban_when_its_expiry_cannot_be_recorded(self):
		# under the agent's unit a read-only state folder made the script ban, then exit before the
		# unban: the address stayed banned for the jail's bantime
		self.stub("fail2ban-client")
		os.makedirs(os.path.dirname(self.state))
		os.chmod(os.path.dirname(self.state), 0o500)
		self.addCleanup(os.chmod, os.path.dirname(self.state), 0o700)
		done, calls = self.run_script("45.33.32.156", "3600")
		self.assertNotEqual(done.returncode, 0)
		self.assertNotIn("set wolf banip 45.33.32.156", calls)

	def test_without_systemd_the_sweep_unbans(self):
		self.stub("fail2ban-client")
		self.stub("systemd-run", code=1)  # no systemd (a container) or no bus
		done, _ = self.run_script("2001:db8::7", "120")
		self.assertIn("no timer: --sweep unbans it", done.stdout)
		with open(self.state, "a") as f:
			f.write("203.0.113.9 1\n")  # an expired one, as after a reboot
		done, calls = self.run_script("--sweep")
		self.assertEqual(done.stdout.strip(), "unbanned 203.0.113.9")
		self.assertIn("set wolf unbanip 203.0.113.9", calls)
		self.assertEqual(read(self.state).split()[0], "2001:db8::7")  # the other one is kept

	def test_a_ban_again_keeps_the_later_expiry(self):
		# a 1 h approval on a second incident must not cut short the 7-day block of the first
		self.stub("fail2ban-client")
		self.run_script("45.33.32.156", "60")
		self.run_script("45.33.32.156", "7200")
		done, calls = self.run_script("45.33.32.156", "120")
		self.assertEqual(done.returncode, 0, done.stderr)
		self.assertIn("already banned for", done.stdout)
		self.assertIn("set wolf banip 45.33.32.156", calls)  # banned again all the same
		self.assertEqual(sum(c.startswith("--quiet") for c in calls), 2)  # no timer for the kept one
		lines = read(self.state).splitlines()
		self.assertEqual(len(lines), 1)
		self.assertAlmostEqual(int(lines[0].split()[1]), time.time() + 7200, delta=30)
		# the first ban's timer fires after 60 s: its sweep leaves the longer ban alone
		done, calls = self.run_script("--sweep")
		self.assertEqual(done.stdout.strip(), "")
		self.assertNotIn("set wolf unbanip 45.33.32.156", calls)

	def test_refusals(self):
		self.stub("fail2ban-client")
		for args, why in ((("1.2.3.4;id", "60"), "invalid address"), (("45.33.32.156", "30"), "between 60 and 604800"),
		                  (("45.33.32.156", "1h"), "whole number"), (("45.33.32.156",), "usage")):  # fmt: skip
			with self.subTest(args):
				done, calls = self.run_script(*args)
				self.assertEqual(done.returncode, 2)
				self.assertIn(why, done.stderr)
				self.assertFalse(any("banip" in c for c in calls), calls)

	def test_missing_jail(self):
		self.stub("fail2ban-client", jail="no")
		done, calls = self.run_script("45.33.32.156", "3600")
		self.assertEqual(done.returncode, 1)
		self.assertIn("no jail 'wolf'", done.stderr)
		self.assertFalse(any("banip" in c for c in calls), calls)


NFT_STUB = """#!/bin/sh
echo "$@" >> "{log}"
if [ "$1" = -f ]; then cat >> "{log}"; exit 0; fi
if [ "$1" = get ]; then
	[ -n "{expires}" ] || exit 1
	printf 'table inet wolf {{\\n\\tset blocked4 {{\\n\\t\\telements = {{ x timeout 7d expires {expires} }}\\n\\t}}\\n}}\\n'
fi
exit 0
"""


@unittest.skipUnless(shutil.which("sh") and shutil.which("awk"), "needs a POSIX shell and awk")
class TestNftablesHelper(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.mkdtemp()
		self.addCleanup(shutil.rmtree, self.dir)
		self.log = os.path.join(self.dir, "calls.log")
		self.bin = os.path.join(self.dir, "bin")
		os.mkdir(self.bin)

	def run_script(self, *args, expires=""):
		path = os.path.join(self.bin, "nft")
		with open(path, "w") as f:
			f.write(NFT_STUB.format(log=self.log, expires=expires))
		os.chmod(path, 0o755)
		env = {"PATH": f"{self.bin}:/usr/bin:/bin"}
		done = subprocess.run(["sh", NFT_SCRIPT, *args], capture_output=True, text=True, env=env, timeout=20)
		return done, read(self.log) if os.path.exists(self.log) else ""

	def test_a_new_address_is_added(self):
		done, calls = self.run_script("45.33.32.156", "3600")
		self.assertEqual(done.returncode, 0, done.stderr)
		self.assertIn("add element inet wolf blocked4 { 45.33.32.156 timeout 3600s }", calls)
		self.assertNotIn("delete element", calls)

	def test_a_longer_block_is_kept(self):
		done, calls = self.run_script("45.33.32.156", "3600", expires="6d23h59m58s120ms")
		self.assertEqual(done.returncode, 0, done.stderr)
		self.assertIn("already blocked for 604798s more", done.stdout)
		self.assertNotIn("add element", calls)

	def test_a_shorter_block_is_replaced_in_one_transaction(self):
		done, calls = self.run_script("2600:3c01::f03c:91ff:fe18:bb2f", "7200", expires="8m20s774ms")
		self.assertEqual(done.returncode, 0, done.stderr)
		self.assertIn("blocked 2600:3c01::f03c:91ff:fe18:bb2f for 7200s (inet wolf blocked6)", done.stdout)
		batch = calls[calls.index("add element inet wolf blocked6 { 2600:3c01::f03c:91ff:fe18:bb2f }\n"):]
		self.assertIn("delete element inet wolf blocked6 { 2600:3c01::f03c:91ff:fe18:bb2f }\nadd element inet wolf blocked6 "
		              "{ 2600:3c01::f03c:91ff:fe18:bb2f timeout 7200s }", batch)  # fmt: skip

	def test_only_addresses(self):
		# never a name nft would resolve, nor a hex word (the shape only: the agent refuses non-public ones)
		for ip in ("cafe", "dead.beef", "1.2.3", "1.2.3.4.5", "1..2.3", "a.b.c.d", "1:2", "1.2.3.4;id", ""):
			with self.subTest(ip):
				if os.path.exists(self.log):
					os.unlink(self.log)
				done, calls = self.run_script(ip, "60")
				self.assertEqual(done.returncode, 2, done.stdout)
				self.assertIn("invalid address", done.stderr)
				self.assertNotIn("element", calls)
		for ip in ("45.33.32.156", "2001:db8::1", "::ffff:45.33.32.156", "1:2:3:4:5:6:7:8"):
			with self.subTest(ip):
				done, _ = self.run_script(ip, "60")
				self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
	unittest.main()
