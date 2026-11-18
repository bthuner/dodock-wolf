"""The Suricata and Wazuh mappings on real output (#72 tests), scrubbed: see tests/data/README.md.

- suricata_eve_et_open.json: Suricata 7.0 with ET Open in front of nginx; attacks from a client
  (log4j, Shellshock, Fortinet traversal, .env, masscan, a password in a POST body) and the
  server's own outbound DNS, TLS and HTTP (IP lookup services, .onion, tunnels, file transfer).
- wazuh_alerts_lab.json: a Wazuh 4.9.2 manager reading syslog relayed from bench-01 and a web
  access log, watching a bench folder, and a real agent (bench-02) under an IPv6 SSH brute force.
"""

import ipaddress
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wolf_agent.parsers.suricata import SuricataParser  # noqa: E402
from wolf_agent.parsers.wazuh import WazuhParser  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "data")
NOW = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)
SERVER, ATTACKER, RESOLVER = "192.0.2.10", "198.51.100.23", "203.0.113.53"


def read(name):
	with open(os.path.join(DATA, name)) as f:
		return f.read().splitlines()


def suricata(**kw):
	p = SuricataParser("bench-01", log_file="eve.json", local={SERVER}, site_benches={"erp.example.com": "frappe-bench"}, **kw)
	for line in read("suricata_eve_et_open.json"):
		p.feed(line)
	return p.drain(NOW)[1]


def wazuh(**kw):
	p = WazuhParser("wazuh-manager", log_file="alerts.json", **kw)
	for line in read("wazuh_alerts_lab.json"):
		p.feed(line)
	return {e["payload"]["rule_id"]: e for e in p.drain(NOW)[1]}


class TestSuricataEtOpen(unittest.TestCase):
	def setUp(self):
		self.events = suricata()
		self.by_sig = {e["payload"]["signature"]: e for e in self.events}

	def test_only_alerts_become_events(self):
		alerts = sum(1 for line in read("suricata_eve_et_open.json") if json.loads(line)["event_type"] == "alert")
		# stats, http, flow, fileinfo and tls records are skipped; so are 2 decoder alerts and 1 excluded rule
		self.assertEqual(len(self.events), alerts - 3)
		self.assertEqual({e["category"] for e in self.events}, {"network_ids_alert"})

	def test_inbound_attacks_name_the_client_and_the_site(self):
		inbound = [e for e in self.events if e["payload"].get("app_proto") == "http" and e.get("site")]
		self.assertEqual(len(inbound), 13)
		for e in inbound:
			self.assertEqual((e["payload"]["ip"], e["site"], e["bench"]), (ATTACKER, "erp.example.com", "frappe-bench"))
		# both ends in HOME_NET: ET's "(Outbound)" twin of a rule is still about the client
		twin = self.by_sig["ET EXPLOIT Apache log4j RCE Attempt (tcp ldap) (Outbound) (CVE-2021-44228)"]
		self.assertEqual(twin["payload"]["ip"], ATTACKER)

	def test_severity_and_techniques(self):
		log4j = self.by_sig["ET EXPLOIT Apache log4j RCE Attempt (http ldap) (CVE-2021-44228)"]
		self.assertEqual((log4j["severity"], log4j["payload"]["priority"], log4j["payload"]["attack_techniques"]), ("critical", 1, ["T1190"]))
		fortinet = self.by_sig["ET EXPLOIT Fortinet FortiOS/FortiProxy SSL VPN Web Portal Path Traversal (CVE-2018-13379)"]
		self.assertEqual((fortinet["severity"], fortinet["payload"]["attack_techniques"]), ("critical", ["T1083"]))
		ipinfo = self.by_sig["ET INFO Possible External IP Lookup Domain Observed in SNI (ipinfo. io)"]
		self.assertEqual((ipinfo["severity"], ipinfo["payload"]["attack_techniques"]), ("warning", ["T1614"]))
		self.assertEqual(self.by_sig["ET SCAN NETWORK Incoming Masscan detected"]["severity"], "info")

	def test_outbound_names_the_service_called(self):
		tls = self.by_sig["ET INFO External IP Address Lookup Domain (ipify .org) in TLS SNI"]
		self.assertEqual((tls["payload"]["ip"], tls["payload"]["tls_sni"], tls.get("site")), ("203.0.113.12", "api.ipify.org", None))
		dns = {e["payload"]["dns_query"]: e for e in self.events if e["payload"].get("app_proto") == "dns"}
		self.assertEqual(sorted(dns), ["api.ipify.org", "check.torproject.org", "example.onion", "ipinfo.io", "ngrok.io", "transfer.sh"])
		self.assertEqual({e["payload"]["ip"] for e in dns.values()}, {RESOLVER})  # the DNS server asked, not the name
		self.assertEqual(dns["example.onion"]["severity"], "critical")
		self.assertEqual(dns["ngrok.io"]["payload"]["attack_techniques"], ["T1572"])

	def test_noise_is_skipped(self):
		# ET marks a password in a request body priority 1: behind a TLS terminator, every Frappe
		# login would be a critical alert
		cleartext = "ET INFO Http Client Body contains pwd= in cleartext"
		self.assertNotIn(cleartext, self.by_sig)
		again = {e["payload"]["signature"]: e for e in suricata(exclude_sids=[])}
		self.assertEqual((again[cleartext]["severity"], again[cleartext]["payload"]["sid"]), ("critical", 2012888))
		# decoder alerts carry no address: nothing to correlate or block, whatever the settings
		self.assertFalse([s for s in again if "truncated packet" in s])
		# an operator's own list replaces the default
		self.assertNotIn("ET SCAN NETWORK Incoming Masscan detected",
		                 {e["payload"]["signature"] for e in suricata(exclude_sids=["2017616", 2017615, "x"])})

	def test_max_priority(self):
		self.assertEqual({e["payload"]["priority"] for e in suricata(max_priority=1)}, {1})


class TestWazuhLab(unittest.TestCase):
	def test_default_floor(self):
		events = wazuh()
		# level 7 and up, SCA left out: below it are failed logins one by one (5710, 5760, 5503), the
		# web rules for 400s, XSS and Shellshock (31101, 31104, 31106, 31166: level 5 and 6)
		self.assertEqual(set(events), {"31103", "40112", "510", "550", "553", "5404", "5763", "5902"})
		self.assertTrue(all(e["category"] == "hids_alert" and e["source"] == "wazuh" for e in events.values()))

	def test_hosts(self):
		events = wazuh()
		self.assertEqual(events["5404"]["host"], "bench-01")  # syslog relayed to the manager: the host in the line
		self.assertEqual(events["5763"]["host"], "bench-02")  # a Wazuh agent: its name
		self.assertEqual(events["5763"]["payload"]["wazuh_agent"]["id"], "001")
		self.assertEqual(events["550"]["host"], "wazuh-manager")  # the manager's own integrity check

	def test_entities_and_severity(self):
		events = wazuh()
		brute, success = events["5763"], events["40112"]
		self.assertEqual((brute["payload"]["ip"], brute["payload"]["user"], brute["severity"]), ("2001:db8:4::17", "root", "warning"))
		self.assertEqual((success["severity"], success["payload"]["attack_techniques"]), ("critical", ["T1078", "T1110"]))
		self.assertEqual((events["31103"]["payload"]["ip"], events["31103"]["payload"]["attack_techniques"]), (ATTACKER, ["T1190"]))
		self.assertEqual(events["5902"]["payload"]["user"], "backup2")
		self.assertEqual(events["553"]["payload"]["attack_techniques"], ["T1070.004", "T1485"])

	def test_lower_floor(self):
		events = wazuh(min_level=5)
		self.assertTrue({"31166", "31104", "5710", "5760"} <= set(events))
		self.assertEqual(events["5760"]["payload"]["count"], 3)  # one event per rule and address, with a count
		self.assertFalse(any("sca" in e["payload"].get("groups", []) for e in events.values()))  # SCA still left out

	def test_sca_when_asked(self):
		self.assertIn("19007", wazuh(exclude_groups=[]))


# documentation ranges, multicast, and what the older fixtures were captured with: the Docker
# network of a Frappe bench (172.18.0.0/16) and scanme.nmap.org
DOCUMENTATION = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]
ALLOWED = {"45.33.32.156"} | {f"172.18.0.{i}" for i in range(256)}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", re.IGNORECASE)


def strings(value, key=""):
	if isinstance(value, dict):
		for k, v in value.items():
			if k != "cis":  # CIS check numbers (1.1.1.1) look like addresses
				yield from strings(v, k)
	elif isinstance(value, list):
		for v in value:
			yield from strings(v, key)
	elif isinstance(value, str):
		yield value


def allowed(text):
	try:
		ip = ipaddress.ip_address(text)
	except ValueError:
		return True  # a version or a time, not an address
	return ip.is_multicast or str(ip) in ALLOWED or any(ip in n for n in DOCUMENTATION)


class TestFixturesAreScrubbed(unittest.TestCase):
	def test_only_documentation_addresses(self):
		"""Every address in every string, free text too (URLs, log lines, User-Agents)."""
		for name in sorted(os.listdir(DATA)):
			if not name.endswith(".json"):
				continue
			for line in read(name):
				for text in strings(json.loads(line)):
					for found in IPV4.findall(text) + IPV6.findall(text):
						self.assertTrue(allowed(found), f"{name}: {found} in {text[:80]!r}")

	def test_the_check_catches_a_leak(self):
		self.assertFalse(allowed("172.20.0.3"))
		self.assertFalse(allowed("9.9.9.9"))
		self.assertEqual(IPV4.findall("${jndi:ldap://8.8.4.4:1389/a}"), ["8.8.4.4"])


if __name__ == "__main__":
	unittest.main()
