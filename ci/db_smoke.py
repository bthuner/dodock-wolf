"""Exercise every Wolf SQL path against a site's database (MariaDB or Postgres).

Run from the bench's sites/ directory:  ../env/bin/python /path/to/ci/db_smoke.py <site>
Inserts demo rows, runs ingest, rules, correlation, timeline, charts, channels, purge and the
incident workflow (assignment, comments, merge/split, postmortem, metrics report),
and prints one line per check ("ok" or "FAIL"). Exits non-zero on the first failure.
CI runs it from ci/integration.sh.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import frappe
from frappe.utils import now_datetime

SITE = sys.argv[1] if len(sys.argv) > 1 else "wolf.localhost"
HOST = "smoke-host"
ROLL_HOST = "smoke-roll"
WF_SITE = "wf.localhost"


def check(name, fn):
	try:
		out = fn()
		frappe.db.commit()
		print(f"ok    {name}: {out}", flush=True)
	except Exception:
		frappe.db.rollback()
		print(f"FAIL  {name}\n{frappe.get_traceback()}", flush=True)
		print(f"smoke test FAILED at check '{name}'", flush=True)
		sys.exit(1)


def main():
	frappe.init(SITE)
	frappe.connect()
	frappe.set_user("Administrator")
	# the checks write and read straight after: the overview's short read cache would hide their
	# writes. "read cache" turns it on for itself.
	frappe.local.conf["wolf_read_cache_seconds"] = 0
	from dodock_wolf import tasks
	from dodock_wolf.api import ui
	from dodock_wolf.wolf import conditions, events, incidents, rules, schema

	print(f"site {SITE} on {frappe.conf.db_type or 'mariadb'}")
	tz, now = events.system_tz(), now_datetime()

	def ingest():
		metrics = [
			schema.normalize_metric(
				{"metric_name": "disk_used_percent", "value": 95, "host": HOST,
				 "timestamp": None, "labels": {"mount": "/"}}, tz, now - timedelta(minutes=m))
			for m in range(4)
		] + [
			schema.normalize_metric({"metric_name": "http_502", "value": 7, "host": HOST, "bench": "b1",
			                         "site": "smoke.localhost"}, tz, now - timedelta(minutes=m))
			for m in range(3)
		]
		n = events.insert_metrics(metrics)
		ev = schema.normalize_event({"type": "deployment", "host": HOST, "bench": "b1", "site": "smoke.localhost",
		                             "severity": "info", "title": "smoke deploy"}, tz, now - timedelta(minutes=5))
		events.insert_event(ev)
		for _ in range(2):
			e = schema.normalize_event({"type": "cron_failure", "category": "scheduled_job", "host": HOST,
			                            "bench": "b1", "site": "smoke.localhost", "severity": "critical",
			                            "title": "smoke cron"}, tz, now)
			incidents.attach_to_open_incident(events.insert_event(e), e)
		dedup = events.emit("error", "smoke dup", fingerprint="smoke-fp", dedupe_minutes=10, host=HOST, site="smoke.localhost")
		again = events.emit("error", "smoke dup", fingerprint="smoke-fp", dedupe_minutes=10, host=HOST, site="smoke.localhost")
		assert dedup == again, "dedupe did not merge"
		return f"{n} metrics, events + dedupe"

	def rule(name, **kw):
		doc = frappe.get_doc("Wolf Alert Rule", name) if frappe.db.exists("Wolf Alert Rule", name) else frappe.new_doc("Wolf Alert Rule")
		doc.update({"rule_name": name, "enabled": 1, "channels": [], "active_from": None, "active_to": None, **kw})
		doc.save()
		return doc

	def evaluate():
		out = {}
		for doc in (
			rule("smoke disk", signal_type="metric", metric_name="disk_used_percent", aggregation="min",
			     operator=">", threshold=90, window_minutes=5, min_samples=3, group_by="host_label", filter_host=HOST),
			rule("smoke 502", signal_type="metric", metric_name="http_502", aggregation="sum", operator=">=",
			     threshold=10, window_minutes=5, group_by="site", require_recent_deployment=1, filter_host=HOST),
			rule("smoke last", signal_type="metric", metric_name="disk_used_percent", aggregation="last",
			     operator=">", threshold=90, window_minutes=5, group_by="none", filter_host=HOST),
			rule("smoke cron", signal_type="event", event_type="cron_failure", min_severity="warning",
			     operator=">=", threshold=1, window_minutes=10, group_by="bench", filter_host=HOST),
		):
			res = rules.evaluate(doc)
			assert res["fired"] or res["updated"], f"{doc.name} did not fire: {res}"
			out[doc.name] = res["fired"] or res["updated"]
		return out

	def correlate():
		site_incident = frappe.db.get_value("Wolf Incident", {"alert_rule": "smoke 502"}, "name", order_by="creation desc")
		# Sharing the site is not enough: the 500 is context of the site's incident, not its evidence.
		e = schema.normalize_event({"type": "error", "host": HOST, "bench": "b1", "site": "smoke.localhost",
		                            "severity": "critical", "title": "smoke 500"}, tz, now)
		error = events.insert_event(e)
		assert incidents.attach_to_open_incident(error, e) is None, "attached by scope alone"
		assert any(r.name == error for r in incidents.get_timeline(site_incident)), "500 missing from the site's context"
		# The 502 responses behind the metric are the 502 rule's evidence, linked when it evaluates again.
		e = schema.normalize_event({"type": "error", "category": "http_502", "host": HOST, "bench": "b1",
		                            "site": "smoke.localhost", "severity": "critical", "title": "smoke 502 on GET /"}, tz, now)
		responses = events.insert_event(e)
		assert incidents.attach_to_open_incident(responses, e) is None
		rules.evaluate(frappe.get_doc("Wolf Alert Rule", "smoke 502"))
		assert frappe.db.get_value("Wolf Event", responses, "incident") == site_incident, "502 events not the 502 rule's evidence"
		return f"500 is context, 502 events are evidence of {site_incident}"

	def timeline():
		inc = frappe.db.get_value("Wolf Incident", {"alert_rule": "smoke 502"}, "name", order_by="creation desc")
		rows = ui.get_incident_timeline(inc)["events"]
		assert any(r.event_type == "deployment" for r in rows), "deployment missing from timeline"
		return f"{inc}: {len(rows)} events, deployment linked={bool(frappe.db.get_value('Wolf Incident', inc, 'deployment_event'))}"

	def deployment_link():
		# the deployment that preceded the incident, not one made after it started (a fix, a
		# migrate on restart) and seen by a rule evaluated later
		site, link_host = "smoke-deploy.localhost", "smoke-link-host"  # apart from the other checks
		before, after = (events.insert_event(schema.normalize_event(
			{"type": "deployment", "host": link_host, "bench": "b1", "site": site, "severity": "info", "title": title}, tz, at))
			for title, at in (("smoke deploy before", now - timedelta(minutes=20)),
			                  ("smoke deploy after", now - timedelta(minutes=2))))  # fmt: skip
		# its own rule: later checks read the newest "smoke 502" incident as the smoke site's
		doc = rule("smoke deploy link", signal_type="metric", metric_name="http_502", aggregation="sum", operator=">=",
		           threshold=10, window_minutes=5, group_by="site", filter_site=site)
		name, kind = incidents.open_incident(doc, f"site={site}", {"host": link_host, "bench": "b1", "site": site},
		                                     "smoke deployment link", started_at=now - timedelta(minutes=10))
		frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
		linked = frappe.db.get_value("Wolf Incident", name, "deployment_event")
		incidents.resolve(name, "smoke check")
		assert kind == "fired", kind
		assert linked == before, f"linked {linked}, expected {before} (not {after}, made after the start)"
		return f"{name} linked the deployment before its start"

	def reopen_after_resolve():
		# resolved by someone who saw the events: those never reopen it, a newer one does, and says so
		site, reopen_host = "smoke-reopen.localhost", "smoke-reopen-host"  # apart from "smoke cron"

		def failure(at):
			return events.insert_event(schema.normalize_event(
				{"type": "cron_failure", "category": "scheduled_job", "host": reopen_host, "bench": "b2", "site": site,
				 "severity": "critical", "title": "smoke reopen cron"}, tz, at))  # fmt: skip

		doc = rule("smoke reopen", signal_type="event", event_type="cron_failure", min_severity="warning", operator=">=",
		           threshold=1, window_minutes=15, group_by="site", filter_site=site, cooldown_minutes=240)
		failure(now_datetime() - timedelta(minutes=2))
		fired = rules.evaluate(doc, now_datetime())["fired"]
		assert len(fired) == 1, fired
		inc = fired[0]
		incidents.resolve(inc, "smoke: handled")
		again = rules.evaluate(doc, now_datetime())
		status = frappe.db.get_value("Wolf Incident", inc, "status")
		assert not again["fired"] and status == "Resolved", f"reopened on the events it was resolved with: {again}, {status}"
		failure(now_datetime() + timedelta(seconds=2))  # a new failure after the resolution
		third = rules.evaluate(doc, now_datetime() + timedelta(seconds=3))
		assert third["fired"] == [inc], f"not reopened by a new event: {third}"
		note = frappe.db.get_value("Comment", {"reference_doctype": "Wolf Incident", "reference_name": inc,
		                                       "comment_type": "Info"}, "content")  # fmt: skip
		assert note and note.startswith("Reopened by rule smoke reopen"), note
		# without a cooldown the same events would open a brand-new incident: they must not either
		incidents.resolve(inc, "smoke: handled again")
		# resolved after the newer failure (stamped 2 s ahead): it was seen too
		frappe.db.set_value("Wolf Incident", inc, "resolved_at", now_datetime() + timedelta(seconds=3))
		doc.cooldown_minutes = 0
		assert not rules.evaluate(doc, now_datetime() + timedelta(seconds=4))["fired"], "new incident on seen events"
		frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
		return f"{inc}: seen events kept it resolved (with or without cooldown); a newer one reopened it, with a note"

	def skew():
		future = schema.normalize_metric({"metric_name": "smoke_skew", "value": 99, "host": HOST}, tz,
		                                 now + timedelta(hours=11))
		events.insert_metrics([future])
		doc = rule("smoke skew", signal_type="metric", metric_name="smoke_skew", aggregation="max",
		           operator=">", threshold=0, window_minutes=5, group_by="host", filter_host=HOST)
		res = rules.evaluate(doc)
		assert not (res["fired"] or res["updated"]), f"future-dated sample fired a rule: {res}"
		clamped, was = schema.clamp_future(future["timestamp"], now, 300)
		assert was and clamped == now
		frappe.db.set_value("Wolf Alert Rule", "smoke skew", "enabled", 0)
		return "future samples ignored by rules, clamped on ingest"

	def overview():
		data = ui.get_overview(range="1h", host=HOST)
		series = ui.get_metric_series(HOST, metrics=json.dumps(["disk_used_percent", "http_502"]), range="1h")["series"]
		return f"{len(data['open_incidents'])} open, {len(data['events'])} events, series={sorted(series)}"

	def presets_and_signal_rules():
		from dodock_wolf.wolf.presets import PRESETS, install_presets

		install_presets()
		missing = [p["rule_name"] for p in PRESETS if not frappe.db.exists("Wolf Alert Rule", p["rule_name"])]
		assert not missing, f"presets not installed: {missing}"
		samples = [
			schema.normalize_metric({"metric_name": "tls_days_left", "value": 2.5, "host": HOST, "bench": "b1",
			                         "site": "smoke.localhost", "labels": {"domain": "smoke.example.net"}}, tz, now),
			schema.normalize_metric({"metric_name": "backup_age_hours", "value": 30, "host": HOST, "bench": "b1",
			                         "site": "smoke.localhost"}, tz, now),
		]
		events.insert_metrics(samples)
		fired = {}
		for preset in ("TLS certificate expiring within 3 days", "No backup for 26 h"):
			spec = next(p for p in PRESETS if p["rule_name"] == preset)
			doc = rule(f"smoke {preset}", **{k: v for k, v in spec.items() if k != "rule_name"}, filter_host=HOST)
			res = rules.evaluate(doc)
			assert res["fired"] or res["updated"], f"{preset} did not fire: {res}"
			fired[preset] = res["fired"] or res["updated"]
			frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
		return f"{len(PRESETS)} presets installed; fired {fired}"

	def email_queue_signals():
		from dodock_wolf.wolf import email_queue

		names = []
		for status, age in (("Not Sent", 120), ("Error", 1), ("Sent", 120)):
			doc = frappe.get_doc({"doctype": "Email Queue", "sender": "smoke@example.com", "message": "smoke",
			                      "status": status, "name": frappe.generate_hash(length=12)})
			doc.db_insert()
			stamp = now - timedelta(minutes=age)
			frappe.db.sql("update `tabEmail Queue` set creation = %s, modified = %s where name = %s", (stamp, stamp, doc.name))
			names.append(doc.name)
		found = email_queue.check(now)
		assert found["backlog"] >= 1 and found["errors"] >= 1, found
		cats = set(frappe.get_all("Wolf Event", filters={"category": ("in", ["email_queue_backlog", "email_queue_error"])},
		                          pluck="category"))
		assert cats == {"email_queue_backlog", "email_queue_error"}, cats
		again = email_queue.check(now)  # bumps, does not duplicate
		count = frappe.db.count("Wolf Event", {"category": "email_queue_backlog"})
		frappe.db.delete("Email Queue", {"name": ("in", names)})
		return f"{found} then {again}; {count} backlog event(s)"

	def backup_failure_and_geoip():
		import os
		import tempfile

		frappe.log_error(title="Dropbox Backup Failed", message="Traceback: smoke backup failure")
		assert frappe.db.exists("Wolf Event", {"category": "backup_failed"}), "backup failure not captured"

		fd, path = tempfile.mkstemp(suffix=".csv")
		with os.fdopen(fd, "w") as f:
			f.write("start_ip,end_ip,country\n81.2.69.0,81.2.69.255,FR\n89.160.20.0,89.160.23.255,DE\n")
		settings = frappe.get_single("Wolf Settings")
		settings.geoip_database = path
		settings.capture_admin_countries = 1
		settings.capture_admin_logins = 1
		settings.save()
		user = "Administrator"
		for ip in ("81.2.69.10", "81.2.69.11", "89.160.20.7"):
			# Activity Log takes a login's IP from the request, not from the document
			frappe.local.request_ip = ip
			frappe.get_doc({"doctype": "Activity Log", "operation": "Login", "status": "Success", "user": user,
			                "subject": "smoke login", "ip_address": ip}).insert(ignore_permissions=True)
		frappe.local.request_ip = None
		new_ip = frappe.db.count("Wolf Event", {"category": "new_admin_ip"})
		assert new_ip >= 2, f"new_admin_ip events: {new_ip}"
		events_found = frappe.get_all("Wolf Event", filters={"category": "admin_login_new_country"},
		                              fields=["title", "payload"])
		settings.geoip_database = None
		settings.save()
		os.unlink(path)
		assert len(events_found) == 1, events_found
		return events_found[0].title

	def scoped_user():
		"""A Wolf User restricted to one site sees only that site, in lists, forms and Wolf APIs."""
		from dodock_wolf.wolf import access

		user = "smoke-scoped@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Smoke", "send_welcome_email": 0,
			                "roles": [{"role": "Wolf User"}]}).insert(ignore_permissions=True)
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site",
		                "value": "smoke.localhost"}).insert()
		other = events.insert_event(schema.normalize_event(
			{"type": "error", "host": HOST, "bench": "b1", "site": "other.localhost", "severity": "warning",
			 "title": "smoke other site"}, tz, now))
		inc = frappe.db.get_value("Wolf Incident", {"alert_rule": "smoke 502"}, "name", order_by="creation desc")
		access.clear_cache()
		frappe.set_user(user)
		try:
			sites = set(frappe.get_list("Wolf Event", filters={"host": HOST}, pluck="site", limit_page_length=0))
			assert sites == {"smoke.localhost"}, f"list leaked {sites}"
			assert set(frappe.get_list("Wolf Incident", pluck="site", limit_page_length=0)) <= {"smoke.localhost"}
			assert not frappe.has_permission("Wolf Event", "read", doc=other, user=user), "form leaked"
			data = ui.get_overview(range="1h")
			assert {e.site for e in data["events"]} == {"smoke.localhost"}, "overview events leaked"
			assert all(i.site == "smoke.localhost" for i in data["open_incidents"] + data["incidents"])
			assert data["scopes"]["site"] == ["smoke.localhost"], data["scopes"]
			assert not data["agents"] or all(a.hostname == "smoke.localhost" for a in data["agents"])
			series = ui.get_metric_series(HOST, metrics=json.dumps(["disk_used_percent", "http_502"]), range="1h")
			names = {key.split(" [")[0] for key in series["series"]}
			assert names == {"http_502"}, f"metric series leaked {sorted(names)}"  # disk_used_percent has no site
			rows = ui.get_incident_timeline(inc)["events"]
			assert rows and all(r.site == "smoke.localhost" for r in rows), "timeline leaked"
		finally:
			frappe.set_user("Administrator")
		assert frappe.has_permission("Wolf Event", "read", doc=other), "manager restricted"
		admin_sites = set(frappe.get_list("Wolf Event", filters={"host": HOST}, pluck="site", limit_page_length=0))
		assert "other.localhost" in admin_sites
		frappe.db.delete("Wolf Event", {"name": other})
		return f"site-scoped user sees {sorted(sites)}, {len(rows)} timeline rows; Administrator sees {len(admin_sites)} sites"

	def agent_secrets():
		"""Register, authenticate, migrate a legacy Password secret and hit the push rate limit."""
		from frappe.utils.password import get_decrypted_password, set_encrypted_password
		from werkzeug.test import EnvironBuilder

		from dodock_wolf.api import agent as agent_api
		from dodock_wolf.api import ingest
		from dodock_wolf.patches import hash_agent_secrets

		def request(agent_id=None, secret=None, body=None):
			headers = {"X-Wolf-Agent-Id": agent_id, "X-Wolf-Agent-Secret": secret} if agent_id else {}
			frappe.local.request = EnvironBuilder(method="POST", json=body or {}, headers=headers).get_request()
			frappe.local.request_ip = "127.0.0.1"

		def legacy_rows():
			return frappe.db.sql("select count(*) from `__Auth` where doctype = 'Wolf Agent' and fieldname = 'agent_secret'")[0][0]

		saved_request = getattr(frappe.local, "request", None)
		settings = frappe.get_single("Wolf Settings")
		saved_limit = settings.max_pushes_per_minute
		try:
			token = get_decrypted_password("Wolf Settings", "Wolf Settings", "registration_token")
			request(body={"registration_token": token, "hostname": "smoke-agent", "agent_version": "smoke"})
			creds = agent_api.register()
			agent_id, secret = creds["agent_id"], creds["agent_secret"]
			stored = frappe.db.get_value("Wolf Agent", agent_id, "secret_hash")
			assert stored.startswith("hmac-sha256$") and secret not in stored, stored
			assert legacy_rows() == 0, "secret still stored reversibly"
			request(agent_id, secret)
			assert agent_api.authenticate_agent() == agent_id
			request(agent_id, secret[:-1] + ("0" if secret[-1] != "0" else "1"))
			try:
				agent_api.authenticate_agent()
				raise AssertionError("wrong secret accepted")
			except frappe.AuthenticationError:
				frappe.clear_messages()

			# an agent registered before hashing: Password value only, the patch hashes it
			frappe.db.set_value("Wolf Agent", agent_id, "secret_hash", None)
			set_encrypted_password("Wolf Agent", agent_id, "legacy-secret-0123456789", "agent_secret")
			assert legacy_rows() == 1
			hash_agent_secrets.execute()
			assert legacy_rows() == 0, "patch left the Password value"
			request(agent_id, "legacy-secret-0123456789")
			assert agent_api.authenticate_agent() == agent_id, "legacy secret stopped working"

			# lazy migration on first use (code updated, migrate not run yet)
			frappe.db.set_value("Wolf Agent", agent_id, "secret_hash", None)
			set_encrypted_password("Wolf Agent", agent_id, "legacy-secret-lazy", "agent_secret")
			request(agent_id, "legacy-secret-lazy")
			assert agent_api.authenticate_agent() == agent_id
			assert legacy_rows() == 0 and frappe.db.get_value("Wolf Agent", agent_id, "secret_hash")

			settings.max_pushes_per_minute = 1
			settings.save()
			limited = 0
			for _ in range(3):  # 3 pushes: two land in one minute window even across a boundary
				request(agent_id, "legacy-secret-lazy", body={"metrics": [], "events": [], "hostname": "smoke-agent"})
				try:
					ingest.push()
				except frappe.TooManyRequestsError:
					frappe.clear_messages()
					limited += 1
			assert limited, "push rate limit never triggered"
		except Exception:
			frappe.db.rollback()  # Postgres: the failed transaction must end before the cleanup below
			raise
		finally:
			frappe.local.request = saved_request
			settings.reload()
			settings.max_pushes_per_minute = saved_limit
			settings.save()
		frappe.delete_doc("Wolf Agent", agent_id, ignore_permissions=True, force=True)
		return f"hashed secret auth ok, legacy secret migrated, {limited} of 3 pushes rate limited"

	def purge():
		old = events.insert_event(schema.normalize_event(
			{"type": "error", "host": HOST, "severity": "warning", "title": "smoke old unlinked"},
			tz, now - timedelta(days=400)))
		old_delivery = frappe.get_doc({"doctype": "Wolf Delivery", "channel_type": "Email", "kind": "fired",
		                               "at": now - timedelta(days=400)}).insert(ignore_permissions=True).name
		tasks.purge_old_data()
		assert not frappe.db.exists("Wolf Event", old), "old unattached event survived purge"
		assert not frappe.db.exists("Wolf Delivery", old_delivery), "old delivery survived purge"
		kept = frappe.db.count("Wolf Event", {"incident": ("is", "set"), "host": HOST})
		return f"old unattached event purged, {kept} incident-linked events kept"

	def channels():
		"""Native channels against a local fake: secrets encrypted, deliveries recorded, never leaked."""
		from dodock_wolf.wolf import notify

		received = []

		class Fake(BaseHTTPRequestHandler):
			def do_POST(self):
				body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
				received.append((self.path, self.headers.get("Authorization"), body))
				failing = self.path.startswith("/fail")
				self.send_response(500 if failing else 200)
				self.end_headers()
				# A careless receiver echoing the request path (and its token) back.
				self.wfile.write(f"bad request {self.path}".encode() if failing else b"{}")

			def log_message(self, *args):
				pass

		server = HTTPServer(("127.0.0.1", 0), Fake)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		base = f"http://127.0.0.1:{server.server_port}"
		key, token, path_secret = "smoke-routing-key-123", "tk_smoke_secret_456", "SLACKPATHSECRET789"
		try:
			doc = rule(
				"smoke channels", signal_type="event", event_type="security", filter_host="smoke-channels-none", operator=">=", threshold=1,
				window_minutes=5, group_by="none", notify_on_resolve=0,
				channels=[
					{"channel_type": "PagerDuty", "enabled": 1, "pagerduty_url": f"{base}/v2/enqueue",
					 "pagerduty_routing_key": key},
					{"channel_type": "ntfy", "enabled": 1, "ntfy_server": base, "ntfy_topic": "wolf-smoke",
					 "ntfy_token": token},
					{"channel_type": "Slack", "enabled": 1, "chat_webhook_url": f"{base}/fail/services/{path_secret}"},
				],
			)
			pd_row = doc.channels[0].name
			stored = frappe.db.get_value("Wolf Alert Channel", pd_row, "pagerduty_routing_key")
			assert stored != key, "routing key stored in clear"
			assert frappe.get_doc("Wolf Alert Rule", doc.name).channels[0].get_password("pagerduty_routing_key") == key

			res = frappe.get_doc("Wolf Alert Rule", doc.name).send_test_notification()
			outcome = {(r["channel_type"], r.get("action")): r for r in res["results"]}
			assert outcome[("PagerDuty", "trigger")]["ok"] and outcome[("PagerDuty", "resolve")]["ok"], res
			assert outcome[("ntfy", "publish")]["ok"], res
			slack = outcome[("Slack", "post")]
			assert not slack["ok"] and slack["http_status"] == 500, slack
			pd_bodies = [json.loads(b) for p, _a, b in received if p == "/v2/enqueue"]
			assert [b["event_action"] for b in pd_bodies] == ["trigger", "resolve"], pd_bodies
			assert ("/wolf-smoke", f"Bearer {token}") in [(p, a) for p, a, _b in received]

			rows = ui.get_incident_deliveries(res["incident"])
			assert len(rows) == 4, rows
			leaks = [s for s in (key, token, path_secret) for r in rows if s in json.dumps(r, default=str)]
			assert not leaks, f"secret in a delivery row: {leaks}"
			logged = frappe.db.sql("select error from `tabError Log` where error like %s or error like %s",
			                       (f"%{path_secret}%", f"%{token}%"))
			assert not logged, "secret in the Error Log"

			# A person acknowledges, then resolves: only the stateful channel hears it.
			inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke channels incident", "status": "Open",
			                      "severity": "critical", "alert_rule": doc.name, "started_at": now_datetime(),
			                      "notified_at": now_datetime()}).insert(ignore_permissions=True)
			assert notify.has_stateful(doc.name)
			inc.acknowledge()
			before = len(received)
			notify.send(inc.name, "acknowledged")
			notify.send(inc.name, "resolved", only_stateful=True)
			later = [(p, json.loads(b).get("event_action")) for p, _a, b in received[before:]]
			assert later == [("/v2/enqueue", "acknowledge"), ("/v2/enqueue", "resolve")], later
			assert frappe.db.count("Wolf Delivery", {"incident": inc.name, "ok": 1}) == 2
			frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
			return f"{len(received)} requests to the fake, {len(rows)} deliveries on the test incident, no secret stored"
		finally:
			server.shutdown()
			server.server_close()

	def resolve():
		frappe.db.delete("Wolf Metric Sample", {"host": HOST})
		res = rules.evaluate(frappe.get_doc("Wolf Alert Rule", "smoke disk"))
		assert res["resolved"], res
		return f"resolved {res['resolved']}"

	# --- storage: rollups, resolution selection, async ingest, retention -------------------
	from dodock_wolf.api import ingest as ingest_api
	from dodock_wolf.wolf import rollups, storage
	from dodock_wolf.wolf.series import bucket_series
	from dodock_wolf.wolf.storage import HOUR, MINUTE, RAW

	base = storage.floor(now, HOUR) - timedelta(hours=5)  # 3 closed hours of samples from here
	roll_end = base + timedelta(hours=3)
	roll_where = ["host = %(rhost)s", "metric_name = 'smoke_roll'"]
	roll_params = {"rhost": ROLL_HOST}

	def raw_truth(start, end):
		"""Per label: every aggregation computed from the raw samples."""
		rows = frappe.db.sql(
			"""select label_key, `value`, `timestamp` from `tabWolf Metric Sample`
			where host = %(rhost)s and metric_name = 'smoke_roll' and `timestamp` >= %(s)s and `timestamp` < %(e)s""",
			{**roll_params, "s": start, "e": end},
			as_dict=True,
		)
		out = {}
		for r in rows:
			out.setdefault(r.label_key, []).append((r.timestamp, float(r.value)))
		return {
			label: {"avg": sum(v for _, v in vals) / len(vals), "min": min(v for _, v in vals),
			        "max": max(v for _, v in vals), "sum": sum(v for _, v in vals), "count": len(vals),
			        "last": max(vals)[1]}
			for label, vals in out.items()
		}

	def compare(rows, truth, agg, what):
		got = {r.label_key: float(r.value) for r in rows}
		assert set(got) == set(truth), f"{what}: groups {sorted(got)} != {sorted(truth)}"
		for label, expected in truth.items():
			assert abs(got[label] - expected[agg]) <= 1e-6 * max(1.0, abs(expected[agg])), \
				f"{what} {agg} {label}: {got[label]} != {expected[agg]}"

	def compare_rollups(what):
		truth = raw_truth(base, roll_end)
		for res in (MINUTE, HOUR):
			for agg in conditions.AGGREGATIONS:
				rows = rollups.aggregate(roll_where, roll_params, ["label_key"], [], agg, res, base, roll_end)
				compare(rows, truth, agg, f"{what} {storage.LABELS[res]}")
			stored = frappe.db.sql(
				"""select sum(value_count) from `tabWolf Metric Rollup`
				where resolution = %(res)s and host = %(rhost)s and metric_name = 'smoke_roll'""",
				{**roll_params, "res": res},
			)[0][0]
			assert int(stored) == sum(t["count"] for t in truth.values()), f"{what}: {res}s rollups hold {stored} samples"
		return truth

	def rollup():
		samples = []
		for i in range(3 * 120):  # every 30 s for 3 hours
			for label, offset in (("/", 0), ("/data", 50)):
				samples.append(schema.normalize_metric(
					{"metric_name": "smoke_roll", "value": (i * 7) % 23 + offset + 0.25, "host": ROLL_HOST,
					 "labels": {"mount": label}}, tz, base + timedelta(seconds=30 * i + 7)))
		events.insert_metrics(samples)
		frappe.db.commit()
		rollups.run()
		marks = rollups.watermarks()
		assert marks[MINUTE] and marks[MINUTE] >= storage.floor(now, MINUTE) - timedelta(minutes=3), marks
		assert marks[HOUR] and marks[HOUR] >= roll_end, marks
		truth = compare_rollups("first run")
		# `last` per host keeps the label of its sample (which mount); both mounts share each
		# timestamp, so the larger value wins: /data
		for res in (MINUTE, HOUR):
			(row,) = rollups.aggregate(roll_where, roll_params, ["host"], [], "last", res, base, roll_end)
			assert row.label_key == "mount=/data", f"last per host at {storage.LABELS[res]}: label {row.label_key}"

		rollups.run()  # nothing new: no-op
		# force a full recompute: must replace, not add
		frappe.db.sql("update `tabWolf Rollup State` set done_until = %(b)s", {"b": base})
		frappe.db.commit()
		rollups.run()
		compare_rollups("recomputed")

		# a late sample (spool replay) moves the watermarks back and is rolled in
		late = schema.normalize_metric({"metric_name": "smoke_roll", "value": 1000, "host": ROLL_HOST,
		                                "labels": {"mount": "/"}}, tz, base + timedelta(minutes=30, seconds=3))
		events.insert_metrics([late])
		frappe.db.commit()
		moved = rollups.watermarks()
		assert moved[MINUTE] == base + timedelta(minutes=30) and moved[HOUR] == base, moved
		rollups.run()
		truth = compare_rollups("late sample")
		assert truth["mount=/"]["max"] == 1000
		return f"{sum(t['count'] for t in truth.values())} samples, 1m and 1h equal raw for {conditions.AGGREGATIONS}"

	def legacy_names():
		# rows written before #56 were named by a 32-hex hash, outside every name range
		# (rollups.name_passes): while such rows remain, a second pass must read them
		frappe.db.sql(
			"update `tabWolf Metric Rollup` set name = md5(name) where host = %(rhost)s and metric_name = 'smoke_roll'",
			roll_params,
		)
		frappe.db.commit()
		rollups.forget_legacy_names()
		truth = raw_truth(base, roll_end)
		for res in (MINUTE, HOUR):
			for agg in conditions.AGGREGATIONS:
				rows = rollups.aggregate(roll_where, roll_params, ["label_key"], [], agg, res, base, roll_end, ["smoke_roll"])
				compare(rows, truth, agg, f"legacy names {storage.LABELS[res]}")
			cells = rollups.bucket_cells(roll_where, roll_params, ["label_key"], res, base, roll_end, HOUR, True, ["smoke_roll"])
			for label, expected in truth.items():
				got = sum(p["count"] for (group, _start), p in cells.items() if group == (label,))
				assert got == expected["count"], f"legacy names, buckets {storage.LABELS[res]} {label}: {got} != {expected['count']}"
		passes = rollups.name_passes(MINUTE, ["smoke_roll"], base, roll_end)
		if frappe.db.db_type == "postgres":
			assert passes == [("", {})], passes
			return "Postgres reads without name ranges"
		assert len(passes) == 2, passes
		# without the second pass, the renamed rows would be missed: the pass is what reads them
		frappe.local.wolf_legacy_rollup_names = False
		try:
			assert not rollups.aggregate(roll_where, roll_params, ["label_key"], [], "count", MINUTE, base, roll_end, ["smoke_roll"])
		finally:
			rollups.forget_legacy_names()
		return f"{sum(t['count'] for t in truth.values())} samples read from hash-named rollups, 1m and 1h"

	def resolution():
		assert rollups.resolution_for(5 * 60) == RAW
		assert rollups.resolution_for(24 * 3600) == MINUTE
		assert rollups.resolution_for(7 * 86400) == HOUR
		truth = raw_truth(now - timedelta(days=8), now + timedelta(minutes=1))
		out = []
		for minutes, agg in ((1440, "sum"), (1440, "last"), (10080, "min"), (10080, "count"), (10080, "avg")):
			doc = rule(f"smoke roll {minutes} {agg}", signal_type="metric", metric_name="smoke_roll", aggregation=agg,
			           operator=">", threshold=-1, window_minutes=minutes, group_by="host_label", filter_host=ROLL_HOST)
			frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
			compare(rules.query_metric(doc, now - timedelta(minutes=minutes)), truth, agg, f"rule {minutes} min")
			out.append(f"{minutes}min/{agg}")
		# charts: same points as bucketing the raw samples
		raw_rows = frappe.db.sql(
			"""select metric_name, label_key, `timestamp`, `value` from `tabWolf Metric Sample`
			where host = %(rhost)s and metric_name = 'smoke_roll'""", roll_params, as_dict=True)
		for range_key, label in (("24h", "1m"), ("7d", "1h")):
			chart = ui.get_metric_series(ROLL_HOST, metrics=json.dumps(["smoke_roll"]), range=range_key)
			assert chart["resolution"] == label, chart["resolution"]
			expected = bucket_series(raw_rows, chart["bucket_seconds"])
			for key, points in expected.items():
				got = dict(map(tuple, chart["series"][key]))
				for ts, value in points:
					assert abs(got[ts] - value) <= 0.011, f"chart {range_key} {key} {ts}: {got.get(ts)} != {value}"
			out.append(f"chart {range_key}={label}/{chart['bucket_seconds']}s")
		return ", ".join(out)

	def ingest_modes():
		agent = frappe.db.get_value("Wolf Agent", {"hostname": "smoke-ingest"})
		if not agent:
			doc = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "smoke-ingest", "status": "Active", "kind": "agent"})
			doc.insert(ignore_permissions=True)
			agent = doc.name
		frappe.local.request_ip = "127.0.0.1"
		stamp = (now - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
		# Both modes correlate: the pushed events name the IP of an open incident's probe, so they join it.
		# (Sharing a site alone would attach nothing: that is context, not evidence.)
		ip = "45.33.32.178"  # used by no other check: events of one IP would correlate across checks
		seed = schema.normalize_event({"type": "security", "category": "web_attack_probe", "severity": "warning",
		                               "host": HOST, "site": "smoke.localhost", "title": "smoke ingest probe",
		                               "payload": {"ip": ip}}, tz, now - timedelta(minutes=5))  # fmt: skip
		target = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke ingest incident", "severity": "warning",
		                         "status": "Open", "started_at": now - timedelta(minutes=10),
		                         "site": "smoke.localhost"}).insert(ignore_permissions=True)  # fmt: skip
		incidents.link_events(target.name, [events.insert_event(seed)])

		def payload(tag):
			# the sync push has no sent_at (older agents), the async one has
			sent_at = {"sent_at": (now - timedelta(seconds=2)).isoformat()} if tag == "async" else {}
			return {**sent_at, "hostname": "smoke-ingest", "agent_version": "smoke",
			        "metrics": [{"metric_name": "smoke_ingest", "value": 1, "labels": {"mode": tag}}],
			        "events": [{"type": "security", "category": "web_attack_probe", "severity": "warning", "host": HOST,
			                    "bench": "b1", "site": "smoke.localhost", "title": f"smoke {tag} probe",
			                    "fingerprint": f"smoke-{tag}-{stamp}", "payload": {"ip": ip}}]}

		def set_mode(mode):
			settings = frappe.get_single("Wolf Settings")
			settings.ingest_mode = mode
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()

		def stored(tag):
			return (frappe.db.count("Wolf Metric Sample", {"metric_name": "smoke_ingest", "label_key": f"mode={tag}"}),
			        frappe.db.get_value("Wolf Event", {"fingerprint": f"smoke-{tag}-{stamp}"}, "incident"))

		set_mode("sync")
		res = ingest_api.accept(agent, payload("sync"))
		assert res["queued"] is False and res["metrics"] == 1 and res["events"] == 1, res
		count, incident = stored("sync")
		assert count == 1 and incident == target.name, f"sync push not stored/correlated: {count}, {incident}"

		set_mode("async")
		before = frappe.db.get_value("Wolf Agent", agent, "last_seen")
		res = ingest_api.accept(agent, payload("async"))
		assert res["queued"] is True and res["metrics"] == 1 and res["events"] == 1 and "health" in res, res
		assert stored("async") == (0, None), "async push stored inline"
		assert frappe.db.get_value("Wolf Agent", agent, "last_seen") >= before, "heartbeat not updated"
		from frappe.utils.background_jobs import get_queue
		jobs = [j for j in get_queue(ingest_api.INGEST_QUEUE).get_jobs()
		        if (j.kwargs or {}).get("method") == ingest_api.STORE_METHOD
		        and (j.kwargs.get("kwargs") or {}).get("agent") == agent]
		assert jobs, "no ingest job queued"
		for job in jobs:  # no worker in CI: run the queued payload (it went through Redis)
			kwargs = job.kwargs["kwargs"]
			assert kwargs["correlate"] is True
			ingest_api.store_batch(**kwargs)
			job.delete()
		count, incident = stored("async")
		assert count == 1 and incident == target.name, f"queued push not stored/correlated: {count}, {incident}"
		return f"sync stored inline, async queued {len(jobs)} job(s) then stored, both attached to {incident}"

	def purge_metrics():
		raw_hours, minute_days, hour_days = rollups.retention()
		old_raw = schema.normalize_metric({"metric_name": "smoke_purge", "value": 1, "host": ROLL_HOST}, tz,
		                                  now - timedelta(hours=raw_hours + 24))
		events.insert_metrics([old_raw])
		key = ("smoke_purge", ROLL_HOST, None, None, None)
		part = storage.new_partial(1.0, now)
		old_minute = storage.floor(now - timedelta(days=minute_days + 5), MINUTE)
		old_hour = storage.floor(now - timedelta(days=hour_days + 5), HOUR)
		rollups.replace_buckets(MINUTE, old_minute, old_minute + timedelta(minutes=1), {(*key, old_minute): part})
		rollups.replace_buckets(HOUR, old_hour, old_hour + timedelta(hours=1), {(*key, old_hour): part})
		# a raw sample older than the raw retention but not rolled up yet must survive
		marks = rollups.watermarks()
		held = now - timedelta(hours=raw_hours + 2)
		frappe.db.set_value("Wolf Rollup State", "1m", "done_until", held - timedelta(hours=1))
		unrolled = schema.normalize_metric({"metric_name": "smoke_purge_keep", "value": 1, "host": ROLL_HOST}, tz, held)
		events.insert_metrics([unrolled])
		frappe.db.commit()
		cutoffs = rollups.purge()
		left = {m: frappe.db.count("Wolf Metric Sample", {"metric_name": m}) for m in ("smoke_purge", "smoke_purge_keep")}
		rolled = frappe.db.count("Wolf Metric Rollup", {"metric_name": "smoke_purge"})
		# a satellite rolls nothing up: its raw samples follow the raw retention, watermark or not
		rollups.purge(rolled=False)
		satellite_left = frappe.db.count("Wolf Metric Sample", {"metric_name": "smoke_purge_keep"})
		frappe.db.set_value("Wolf Rollup State", "1m", "done_until", marks[MINUTE])
		frappe.db.commit()
		assert left == {"smoke_purge": 0, "smoke_purge_keep": 1}, left
		assert satellite_left == 0, "raw retention not applied without rollups"
		assert rolled == 0, f"{rolled} expired rollups left"
		assert frappe.db.count("Wolf Metric Rollup", {"host": ROLL_HOST, "metric_name": "smoke_roll"}), "recent rollups purged"
		return f"expired raw/1m/1h purged, unrolled raw kept unless satellite (cutoffs {', '.join(f'{k}<{v}' for k, v in cutoffs.items())})"

	from dodock_wolf.api import incident as inc_api

	wf = {}

	def wf_event(title, minutes_ago, severity="warning"):
		return events.insert_event(schema.normalize_event(
			{"type": "error", "host": HOST, "bench": "b1", "site": WF_SITE, "severity": severity, "title": title},
			tz, now - timedelta(minutes=minutes_ago)))

	def workflow():
		e = [wf_event("wf a", 30), wf_event("wf b", 20, "critical"), wf_event("wf c", 10), wf_event("wf d", 5)]
		a, b = inc_api.open_from_event(e[0]), inc_api.open_from_event(e[1])
		for name in e[2:]:
			frappe.db.set_value("Wolf Event", name, "incident", b)
		incidents.refresh_event_count(b)
		doc = frappe.get_doc("Wolf Incident", b)
		doc.assign_to_me()
		doc.reload()
		assert doc.assigned_to == "Administrator", doc.assigned_to
		assert frappe.db.exists("ToDo", {"reference_type": "Wolf Incident", "reference_name": b, "status": "Open"}), "no ToDo"
		doc.acknowledge()
		inc_api.add_comment(b, "smoke <b>comment</b>")
		inc_api.add_comment(a, "comment that moves with the merge")
		activity = ui.get_incident_timeline(b)["activity"]
		comments = [x for x in activity if x["kind"] == "comment"]
		assert comments and "<b>" not in comments[0]["content"], comments
		assert any(x["kind"] == "status" and x["to"] == "Acknowledged" for x in activity), activity
		wf.update(events=e, a=a, b=b)
		return f"{a}, {b}: assigned, acknowledged, {len(activity)} activity entries"

	def merge_split():
		from dodock_wolf.api import incident_view as view

		a, b, e = wf["a"], wf["b"], wf["events"]
		# the Wolf UI's dry runs: what would move, before anything does
		pre = view.merge_preview(a, b)
		assert a not in {c["name"] for c in pre["candidates"]}, "an incident offered as its own destination"
		p = pre["preview"]
		assert not p["error"] and p["source_after"] == {"status": "Resolved", "merged_into": b}, p
		assert p["events"] == frappe.db.count("Wolf Event", {"incident": a}), p
		assert frappe.db.get_value("Wolf Incident", a, "status") != "Resolved", "the preview wrote"
		assert view.merge_preview(a, a)["preview"]["error"], "merging into itself not refused"
		res = inc_api.merge(a, b)
		src = frappe.db.get_value("Wolf Incident", a, ["status", "merged_into"], as_dict=True)
		assert (src.status, src.merged_into) == ("Resolved", b), src
		assert frappe.db.get_value("Wolf Event", e[0], "incident") == b
		assert frappe.db.get_value("Wolf Incident", b, "event_count") == 4
		assert frappe.db.count("Comment", {"reference_doctype": "Wolf Incident", "reference_name": b,
		                                   "comment_type": "Comment"}) == 2, "comment not moved"
		try:
			inc_api.merge(a, b)
			raise AssertionError("merged twice")
		except frappe.ValidationError:
			frappe.clear_messages()
		sp = view.split_preview(b, json.dumps([e[0], e[1]]))
		assert sp["preview"]["moved"] == 2 and not sp["preview"]["error"], sp["preview"]
		assert sp["preview"]["kept"] == len(sp["events"]) - 2, sp["preview"]
		every = view.split_preview(b, json.dumps([x["name"] for x in sp["events"]]))["preview"]
		assert every["error"], "a split that empties the incident was not refused"
		assert view.get_incident(b)["can"]["split"], "split not offered on an incident with several events"
		c = inc_api.split(b, json.dumps([e[0], e[1]]), "smoke split")
		new = frappe.db.get_value("Wolf Incident", c, ["split_from", "alert_rule", "severity", "event_count"], as_dict=True)
		assert (new.split_from, new.alert_rule, new.severity, new.event_count) == (b, None, "critical", 2), new
		assert frappe.db.get_value("Wolf Incident", b, "event_count") == 2
		try:
			inc_api.split(b, json.dumps([e[2], e[3]]))
			raise AssertionError("split emptied the incident")
		except frappe.ValidationError:
			frappe.clear_messages()
		# a rule incident merged by hand: further breaches feed the target, no new incident
		cron = frappe.db.get_value("Wolf Incident", {"alert_rule": "smoke cron", "status": ("in", ("Open", "Acknowledged"))}, "name")
		assert cron, "smoke cron incident not open"
		inc_api.merge(cron, b)
		again = rules.evaluate(frappe.get_doc("Wolf Alert Rule", "smoke cron"))
		assert again["updated"] == [b] and not again["fired"], again
		wf["c"] = c
		return f"merged {res['events']} event(s) + {res['comments']} comment(s) into {b}, split {c}, rule follows merge"

	def postmortem():
		c = wf["c"]
		frappe.get_doc("Wolf Incident", c).resolve()
		pm = inc_api.create_postmortem(c)
		assert inc_api.create_postmortem(c) == pm, "second postmortem created"
		doc = frappe.get_doc("Wolf Postmortem", pm)
		assert "wf a" in doc.timeline_snapshot and doc.duration_minutes is not None, doc.timeline_snapshot
		assert frappe.db.get_value("Wolf Incident", c, "postmortem") == pm
		return f"{pm} for {c}, {doc.duration_minutes} min"

	def metrics():
		from dodock_wolf.dodock_wolf.report.wolf_incident_metrics import wolf_incident_metrics as report
		from dodock_wolf.wolf import stats

		today = now.date()
		out = {}
		for group_by in stats.GROUP_FIELDS:
			cols, data, _msg, _chart = report.execute(
				{"from_date": str(today - timedelta(days=1)), "to_date": str(today), "group_by": group_by})
			assert cols and data, group_by
			out[group_by] = len(data)
		site = report.execute({"from_date": str(today - timedelta(days=1)), "to_date": str(today), "group_by": "site",
		                       "site": WF_SITE})[1]
		row = next(r for r in site if r["group"] == WF_SITE)
		# the two merged incidents are left out: b and the split c remain
		assert row["incidents"] == 2 and row["acknowledged"] == 1 and row["resolved"] == 1, row
		return f"groups {out}, {WF_SITE}: mttr={row['mttr']} mtta={row['mtta']}"

	def ui_counts():
		"""Exact KPI counts past list limits, bench-under-host, and the same access rules for a scoped user."""
		from dodock_wolf.api import scope as scope_api

		kpi_host, kpi_site = "smoke-kpi-host", "kpi.localhost"
		frappe.db.delete("Wolf Incident", {"host": kpi_host})
		for i in range(60):  # more than the 50 rows the overview lists
			frappe.get_doc({
				"doctype": "Wolf Incident", "title": f"smoke kpi {i}", "host": kpi_host, "bench": "frappe-bench",
				"site": kpi_site if i < 55 else None, "severity": "critical" if i < 7 else "warning",
				"status": "Acknowledged" if i % 3 == 0 else "Open", "started_at": now - timedelta(minutes=i),
			}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke kpi resolved", "host": kpi_host, "site": kpi_site,
		                "severity": "critical", "status": "Resolved", "started_at": now}).insert(ignore_permissions=True)
		frappe.db.commit()
		got = scope_api.get_counts(range="24h", host=kpi_host)
		inc = got["incidents"]
		assert inc["unresolved"] == 60 and inc["critical_unresolved"] == 7, inc
		assert inc["unacknowledged"] == 40 and inc["by_status"]["Acknowledged"] == 20, inc
		assert inc["sites_with_unresolved"] == 1 and inc["unresolved_without_site"] == 5, inc
		assert inc["opened_in_window"] == 61 and inc["resolved_in_window"] == 1, inc
		assert got["window"]["relative"] == "24h" and got["window"]["since"].endswith("Z"), got["window"]
		bench_only = scope_api.get_counts(range="24h", host=kpi_host, bench="frappe-bench")["incidents"]["unresolved"]
		try:
			scope_api.get_counts(bench="frappe-bench")
			raise AssertionError("bench without host accepted")
		except frappe.ValidationError:
			pass
		from dodock_wolf.wolf import window

		since_utc = window.to_utc(now - timedelta(minutes=10), tz)
		explicit = scope_api.get_counts(since=since_utc, host=kpi_host)
		assert explicit["window"]["relative"] is None and explicit["window"]["since"] == since_utc, explicit["window"]
		assert explicit["incidents"]["opened_in_window"] == 12, explicit["incidents"]  # 11 started 0..10 min ago, plus the resolved one

		full = scope_api.get_inventory()
		kpi = [h for h in full["hosts"] if h["host"] == kpi_host]
		assert kpi and kpi[0]["sources"] == ["incidents"], kpi  # learnt from telemetry only, and says so
		assert [b["bench"] for b in kpi[0]["benches"]] == ["frappe-bench"], kpi

		# the host's agent registers its bench: a quiet site (no telemetry) and a sibling site;
		# a satellite on the same host is counted with it
		quiet, hidden = "quiet.localhost", "hidden.localhost"
		frappe.db.delete("Wolf Agent", {"hostname": ("in", (kpi_host, "sat.kpi.localhost"))})
		for doc in (
			{"hostname": kpi_host, "kind": "agent", "benches": json.dumps([{"name": "frappe-bench", "sites": [kpi_site, quiet, hidden]}])},
			{"hostname": "sat.kpi.localhost", "kind": "satellite", "benches": json.dumps([{"name": "frappe-bench", "host": kpi_host, "sites": []}])},
		):
			frappe.get_doc({"doctype": "Wolf Agent", "status": "Active", "last_seen": now, **doc}).insert(ignore_permissions=True)
		frappe.db.commit()
		agents = scope_api.get_counts(host=kpi_host)["agents"]
		assert agents["agent"]["fresh"] == 1 and agents["satellite"]["fresh"] == 1, agents

		user = "smoke-scoped@example.com"
		frappe.db.delete("Wolf User Scope", {"user": user})
		for site in (kpi_site, quiet):
			frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site", "value": site}).insert()
		from dodock_wolf.wolf import access

		access.clear_cache()
		frappe.set_user(user)
		try:
			scoped = scope_api.get_counts(range="24h")
			assert scoped["restricted"] and scoped["incidents"]["unresolved"] == 55, scoped["incidents"]
			assert scoped["incidents"]["unresolved_without_site"] == 0, "host-wide incidents leaked"
			inv = scope_api.get_inventory()
			sites = {s["site"] for h in inv["hosts"] for b in h["benches"] for s in b["sites"]}
			sites |= {s["site"] for h in inv["hosts"] for s in h["sites"]} | {s["site"] for s in inv["unplaced_sites"]}
			# the quiet site comes from the agent's registration; the sibling site is not granted
			assert sites == {kpi_site, quiet}, f"inventory {sorted(sites)}"
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()
		frappe.db.delete("Wolf Agent", {"hostname": ("in", (kpi_host, "sat.kpi.localhost"))})
		frappe.db.delete("Wolf Incident", {"host": kpi_host})
		return (f"60 unresolved counted past the 50-row list (7 critical, 40 unacknowledged), bench filter {bench_only}, "
		        f"satellite counted on its host, scoped user sees 55 and only {kpi_site} + the quiet {quiet}")

	def incident_view():
		"""Incident page APIs: detail, timeline pages with ties, families, access, actions, deleted deployment."""
		from dodock_wolf.api import incident as inc_api
		from dodock_wolf.api import incident_view as view
		from dodock_wolf.wolf import access

		site, other = "tl.localhost", "tl-other.localhost"
		at = now - timedelta(minutes=20)

		def ev(title, site_, minutes=0, typ="error", bench="b1"):
			return events.insert_event(schema.normalize_event(
				{"type": typ, "host": HOST, "bench": bench, "site": site_, "severity": "critical", "title": title},
				tz, at + timedelta(minutes=minutes)))

		# 90 min before: older than the 30-min timeline padding, linked by the deployment window
		deploy = ev("tl deploy", site, -90, "deployment")
		linked = [ev(f"tl linked {i}", site) for i in range(7)]  # seven rows at the same time
		context = [ev(f"tl context {i}", site, 2) for i in range(3)]
		# another site on another bench: out of scope (a site on the same bench would be context)
		hidden = ev("tl other site", other, 1, bench="b9")
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "tl incident", "host": HOST, "bench": "b1",
		                      "site": site, "severity": "critical", "status": "Open", "started_at": at,
		                      "deployment_event": deploy, "deployment_at": at - timedelta(minutes=90)}).insert()
		for name in linked:
			frappe.db.set_value("Wolf Event", name, "incident", inc.name)
		frappe.db.set_value("Wolf Event", linked[0], "count", 5)  # a deduplicated record: 5 occurrences
		for i in range(3):
			frappe.get_doc({"doctype": "Wolf Delivery", "incident": inc.name, "at": at, "kind": "webhook",
			                "channel_type": "webhook", "action": "opened", "ok": i != 2, "http_status": 200 if i != 2 else 500,
			                "target": "https://hooks.example.test/x"}).insert(ignore_permissions=True)
		inc_api.add_comment(inc.name, "Looking <b>now</b>")
		# a comment typed in Desk's editor: paragraphs, not <br>
		frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Wolf Incident",
		                "reference_name": inc.name, "comment_email": "Administrator",
		                "content": '<div class="ql-editor read-mode"><p>Restarted workers</p><p>Looks fine now</p></div>'}).insert(
			ignore_permissions=True)
		frappe.db.commit()

		detail = view.get_incident(inc.name)
		assert detail["deployment"]["available"] and detail["event_records"] == 7, detail
		# records and the occurrences they report are not the same number
		assert (detail["event_count"], detail["event_occurrences"]) == (7, 11), detail
		assert detail["can"]["acknowledge"] and detail["can"]["resolve"], detail["can"]
		full = view.get_timeline(inc.name, limit=500)
		ids = [r["id"] for r in full["rows"]]
		assert not full["paging"]["has_more"] and len(ids) == len(set(ids)), "duplicates in one page"
		assert f"event:{hidden}" not in ids, "other site's event in the timeline"
		assert {f"event:{n}" for n in linked + context + [deploy]} <= set(ids), "events missing"
		deploy_row = next(r for r in full["rows"] if r["id"] == f"event:{deploy}")
		assert deploy_row["relation"] == "preceding_change", deploy_row
		texts = [r["text"] for r in full["rows"] if r.get("activity") == "comment"]
		assert "Looking <b>now</b>" in texts, texts  # plain text as typed, never HTML to render
		assert "Restarted workers\nLooks fine now" in texts, texts
		results = sorted(r["result"] for r in full["rows"] if r["kind"] == "delivery")
		assert results == ["accepted", "accepted", "failed"], results
		# every page size gives the same rows, once each, in the same order
		for limit in (1, 2, 3, 7):
			paged, cursor = [], None
			while True:
				page = view.get_timeline(inc.name, cursor=cursor, limit=limit)
				paged += [r["id"] for r in page["rows"]]
				if not page["paging"]["has_more"]:
					break
				cursor = page["paging"]["next_cursor"]
			assert paged == ids, f"limit {limit}: {len(paged)} rows vs {len(ids)}"
		evidence = view.get_timeline(inc.name, families="evidence")["rows"]
		assert {r["family"] for r in evidence} == {"evidence"} and len(evidence) == 7, evidence
		try:
			view.get_timeline(inc.name, cursor="garbage")
			raise AssertionError("bad cursor accepted")
		except frappe.ValidationError:
			pass

		user = "smoke-scoped@example.com"
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site", "value": other}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			try:
				view.get_incident(inc.name)
				raise AssertionError("scoped user read another site's incident")
			except frappe.PermissionError:
				pass
			listed = view.list_incidents(status="all", limit=200)["incidents"]
			assert inc.name not in {i["name"] for i in listed}, "incident listed to a scoped user"
		finally:
			frappe.set_user("Administrator")
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site", "value": site}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			assert not view.get_incident(inc.name)["can"]["acknowledge"], "Wolf User offered an action"
			try:
				view.act(inc.name, "acknowledge")
				raise AssertionError("Wolf User acknowledged")
			except frappe.PermissionError:
				pass
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()

		acked = view.act(inc.name, "acknowledge")
		assert acked["status"] == "Acknowledged" and acked["acknowledged"]["by"] == "Administrator", acked
		mine = view.act(inc.name, "assign_to_me")
		assert mine["assigned_to"]["user"] == "Administrator", mine
		statuses = [r["summary"] for r in view.get_timeline(inc.name, families="activity")["rows"]]
		assert any("acknowledged" in s for s in statuses), statuses

		# retention deleted the deployment event: the incident still says one happened
		frappe.db.delete("Wolf Event", {"name": deploy})
		frappe.db.commit()
		gone = view.get_incident(inc.name)["deployment"]
		rows = view.get_timeline(inc.name)["rows"]
		unavailable = [r for r in rows if r["id"] == f"deployment:{inc.name}"]
		assert not gone["available"] and unavailable and unavailable[0]["unavailable"], (gone, unavailable)

		first = view.list_incidents(status="all", limit=1)
		assert first["paging"]["has_more"] and first["paging"]["next_cursor"], first["paging"]
		second = view.list_incidents(status="all", limit=1, cursor=first["paging"]["next_cursor"])
		assert second["incidents"][0]["name"] != first["incidents"][0]["name"], "list page repeated"
		view.act(inc.name, "resolve")
		try:
			view.act(inc.name, "acknowledge")  # a page left open still shows the button
			raise AssertionError("acknowledge reopened a resolved incident")
		except frappe.ValidationError:
			pass
		assert frappe.db.get_value("Wolf Incident", inc.name, "status") == "Resolved"

		# an incident without any scope has no context of its own ("same scope" would be every site),
		# only the health events of the scopes its events came from: here the linked event's site
		bare = frappe.get_doc({"doctype": "Wolf Incident", "title": "tl bare", "severity": "warning", "status": "Open",
		                       "started_at": at}).insert()
		frappe.db.set_value("Wolf Event", linked[0], "incident", bare.name)
		bare_rows = view.get_timeline(bare.name, families="evidence,context")["rows"]
		assert [r["id"] for r in bare_rows if r["relation"] == "linked"] == [f"event:{linked[0]}"], bare_rows
		assert {r["scope"]["site"] for r in bare_rows} == {site}, [r["scope"] for r in bare_rows]  # not `other`
		assert {r["event_type"] for r in bare_rows} <= set(incidents.HEALTH_TYPES), [r["event_type"] for r in bare_rows]
		empty = frappe.get_doc({"doctype": "Wolf Incident", "title": "tl empty", "severity": "warning", "status": "Open",
		                        "started_at": at}).insert()  # fmt: skip
		assert not view.get_timeline(empty.name, families="evidence,context")["rows"], "context from every site"
		assert not incidents.get_timeline(empty.name), "Desk context from every site"
		frappe.delete_doc("Wolf Incident", empty.name, force=True)
		frappe.delete_doc("Wolf Incident", bare.name, force=True)
		frappe.db.delete("Wolf Event", {"name": ("in", linked + context + [hidden])})
		frappe.db.commit()
		return (f"{inc.name}: {len(ids)} rows identical at page sizes 1/2/3/7, deployment outside the window shown, "
		        f"other site hidden, comments as text, 2 accepted + 1 failed deliveries, Wolf User denied, "
		        f"acknowledged and assigned, stale acknowledge refused, deleted deployment kept, bare incident has only its linked site's health")

	def dashboards():
		"""Signals with honest states, HTTP series with gaps and deployments, monitoring."""
		from dodock_wolf.api import dashboard
		from dodock_wolf.wolf import access

		dash, dsite = "smoke-dash", "dash.localhost"

		def sample(name, value, minutes_ago, **scope):
			return schema.normalize_metric({"metric_name": name, "value": value, "host": dash, **scope}, tz,
			                               now - timedelta(minutes=minutes_ago))

		events.insert_metrics([
			sample("disk_used_percent", 93, 0.2, labels={"mount": "/"}),
			sample("disk_used_percent", 40, 0.2, labels={"mount": "/data"}),
			sample("cpu_usage", 12, 20),  # stopped 20 min ago: stale
			sample("tls_days_left", 40, 30, site=dsite, bench="b1", labels={"domain": dsite}),  # hourly: fresh
			*[sample("http_requests", 100, m, site=dsite, bench="b1") for m in (50, 49, 5)],
			*[sample("http_5xx", 6, m, site=dsite, bench="b1") for m in (50, 5)],
			sample("http_502", 4, 5, site=dsite, bench="b1"),
		])
		rule = frappe.get_doc({"doctype": "Wolf Alert Rule", "rule_name": "smoke dash disk", "enabled": 1,
		                       "signal_type": "metric", "metric_name": "disk_used_percent", "aggregation": "max",
		                       "operator": ">", "threshold": 90, "window_minutes": 5, "group_by": "host_label",
		                       "filter_host": dash, "severity": "warning"}).insert(ignore_permissions=True)
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke dash disk", "alert_rule": rule.name, "host": dash,
		                      "group_key": f"host={dash},label_key=mount=/", "severity": "warning", "status": "Open",
		                      "started_at": now}).insert(ignore_permissions=True)
		deploy = events.insert_event(schema.normalize_event(
			{"type": "deployment", "host": dash, "bench": "b1", "site": dsite, "title": "smoke dash deploy"}, tz,
			now - timedelta(minutes=30)))
		# a bench-wide deployment (several sites updated at once): no site
		bench_deploy = events.insert_event(schema.normalize_event(
			{"type": "deployment", "host": dash, "bench": "b1", "title": "smoke dash bench update"}, tz,
			now - timedelta(minutes=20)))
		frappe.db.commit()

		sig = dashboard.get_signals(host=dash)
		by_metric = {s["metric_name"]: s for s in sig["series"] if s["label_key"] != "mount=/data"}
		data_disk = next(s for s in sig["series"] if s["label_key"] == "mount=/data")
		assert data_disk["state"] == "watched" and not data_disk["incidents"], data_disk  # / is full, /data is not
		assert by_metric["disk_used_percent"]["state"] == "firing", by_metric["disk_used_percent"]
		assert by_metric["disk_used_percent"]["incidents"] == [inc.name], by_metric["disk_used_percent"]
		assert by_metric["disk_used_percent"]["value"] == 93, by_metric["disk_used_percent"]
		assert by_metric["cpu_usage"]["state"] == "stale", by_metric["cpu_usage"]
		assert by_metric["tls_days_left"]["state"] in ("watched", "unwatched"), by_metric["tls_days_left"]  # not stale
		missing = {m["metric"] for m in sig["missing"]}
		assert "backup_age_hours" in missing and "redis_used_memory_percent" in missing, missing
		assert "http_5xx" not in by_metric, "HTTP belongs to the HTTP chart"
		assert sig["counts"]["host"]["firing"] == 1 and sig["counts"]["host"]["stale"] == 1, sig["counts"]

		http = dashboard.get_http(range="1h", host=dash, site=dsite)
		points = {m: [v for _, v in http["series"][m]] for m in http["series"]}
		assert sum(v for v in points["http_5xx"] if v) == 12 and sum(v for v in points["http_502"] if v) == 4, points
		assert None in points["http_5xx"], "an empty bucket became a zero"
		assert len(points["http_requests"]) == len(points["http_502"]), "series of different lengths"
		assert [d["name"] for d in http["deployments"]] == [deploy], http["deployments"]
		site_only = dashboard.get_http(range="1h", site=dsite)
		assert {d["name"] for d in site_only["deployments"]} == {deploy, bench_deploy}, site_only["deployments"]
		assert http["window"]["relative"] == "1h" and http["resolution"] == "raw", http["window"]

		mon = dashboard.get_monitoring()
		assert {"health", "rollups", "agents", "mode"} <= set(mon), sorted(mon)
		# how often Frappe's scheduler runs Wolf's "every minute" jobs (4 min unless configured)
		from frappe.utils.scheduler import get_scheduler_tick

		tick = mon["health"]["scheduler"]["tick_seconds"]
		assert tick == get_scheduler_tick(), (tick, get_scheduler_tick())

		user = "smoke-scoped@example.com"
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "host", "value": dash}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			scoped = dashboard.get_signals(host=dash)
			rules = [r for s in scoped["series"] for r in s["rules"]]
			assert rules and all("filter_host" not in r for r in rules), rules  # what it checks, not whom it names
			other = dashboard.get_signals(host="smoke-host")
			assert not other["series"], "another host's signals leaked"
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()
		frappe.delete_doc("Wolf Incident", inc.name, force=True)
		frappe.delete_doc("Wolf Alert Rule", rule.name, force=True)
		frappe.db.delete("Wolf Event", {"name": ("in", [deploy, bench_deploy])})
		frappe.db.commit()
		return (f"disk / firing ({inc.name}), /data not, cpu stale, tls fresh at 30 min, {len(missing)} signals missing; "
		        f"site dashboard has the bench-wide deployment; "
		        f"5xx 12 with 502 4 inside it, gaps kept; restricted user sees no rule filters")

	def read_cache_check():
		"""The overview's cached reads: one value for every caller, filtered by each caller's grants."""
		from dodock_wolf.api import dashboard
		from dodock_wolf.api import scope as scope_api
		from dodock_wolf.wolf import access, read_cache

		mine, theirs, late = "smoke-cache-mine", "smoke-cache-theirs", "smoke-cache-late"

		def sample(host):
			return schema.normalize_metric({"metric_name": "cpu_usage", "value": 5, "host": host}, tz,
			                               now_datetime() - timedelta(seconds=10))

		def hosts(sig):
			return {s["host"] for s in sig["series"]}

		events.insert_metrics([sample(mine), sample(theirs)])
		user = "smoke-scoped@example.com"
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "host", "value": mine}).insert()
		frappe.db.commit()
		frappe.local.conf["wolf_read_cache_seconds"] = 30
		read_cache.clear()
		access.clear_cache()
		try:
			# Administrator reads first: the cache holds every host's series and triples
			full, full_inv = dashboard.get_signals(), scope_api.get_inventory()
			assert {mine, theirs} <= hosts(full), sorted(hosts(full))
			frappe.set_user(user)
			try:
				sig, inv = dashboard.get_signals(), scope_api.get_inventory()
			finally:
				frappe.set_user("Administrator")
			# served from what Administrator's read cached, then cut to the user's grant
			assert sig["as_of"] == full["as_of"] and inv["as_of"] == full_inv["as_of"], "not read from the cache"
			assert hosts(sig) == {mine}, f"cached signals leaked {sorted(hosts(sig))}"
			assert sum(sum(c.values()) for c in sig["counts"].values()) == sig["total_series"], sig["counts"]
			# raw samples are not rolled yet: the inventory knows other hosts (from events), not these
			assert HOST in {h["host"] for h in full_inv["hosts"]}, full_inv["hosts"]
			assert {h["host"] for h in inv["hosts"]} <= {mine} and not inv["unplaced_sites"], f"cached inventory leaked {inv['hosts']}"
			# a series that starts after the read shows once the cached value goes
			events.insert_metrics([sample(late)])
			frappe.db.commit()
			assert late not in hosts(dashboard.get_signals()), "the cache was not used"
			read_cache.clear()
			fresh = dashboard.get_signals()
			assert late in hosts(fresh), sorted(hosts(fresh))

			# fresh for 1 s here: past it, the value is still served and read again in the background
			from frappe.utils.background_jobs import get_job, is_job_enqueued

			frappe.local.conf["wolf_read_cache_seconds"] = 1
			read_cache.clear()
			first = dashboard.get_signals()
			time.sleep(1.5)
			stale = dashboard.get_signals()
			job_id = "wolf_read_cache|signals|{}"
			assert stale["as_of"] == first["as_of"], "the request read a stale value again itself"
			assert is_job_enqueued(job_id), "no background read queued for a stale value"
			dashboard.get_signals()  # a second page while it is queued: still one job (deduplicated)
			read_cache.refresh("signals", "{}")  # what the queued job runs
			get_job(job_id).delete()
			again = dashboard.get_signals()
			assert again["as_of"] > first["as_of"], (again["as_of"], first["as_of"])
			# between visits, the scheduler reads again what was asked for and is no longer fresh
			time.sleep(1.5)
			read_cache.refresh_active()
			warm = dashboard.get_signals()
			assert warm["as_of"] > again["as_of"], (warm["as_of"], again["as_of"])
			if job := get_job(job_id):
				job.delete()
		finally:
			frappe.local.conf["wolf_read_cache_seconds"] = 0
			read_cache.clear()
			frappe.db.delete("Wolf User Scope", {"user": user})
			frappe.db.delete("Wolf Metric Sample", {"host": ("in", (mine, theirs, late))})
			frappe.db.commit()
			access.clear_cache()
		return (f"a host-scoped user gets {len(sig['series'])} of {full['total_series']} cached series, its host only; "
		        "a new series shows once the cache goes; a stale value is served and read again by one job, "
		        "and by the scheduler between visits")

	def explorers():
		"""Event list paging and search, error groups across sites, a scoped user's view of a group."""
		from dodock_wolf.api import explore
		from dodock_wolf.wolf import access

		xhost, sa, sb = "smoke-explore", "xa.localhost", "xb.localhost"
		fp = "smoke-explore-fp"

		def err(site, minutes_ago, title="KeyError: 'customer' in 100%_sync", **extra):
			return events.insert_event(schema.normalize_event(
				{"type": "error", "host": xhost, "bench": "b1", "site": site, "severity": "critical", "title": title,
				 "fingerprint": fp, "payload": {"traceback": "Traceback (most recent call last):\n  KeyError: 'customer'"}, **extra},
				tz, now - timedelta(minutes=minutes_ago)))

		# a record first seen 3 days ago and seen again today: active in a 24h window, with old repeats
		old = err(sa, 3 * 24 * 60)
		frappe.db.set_value("Wolf Event", old, {"count": 40, "last_seen": now - timedelta(minutes=5)})
		recent = [err(sa, 10), err(sb, 20)]
		ancient = err(sa, 5 * 24 * 60)  # last seen 5 days ago: outside a 24h window, still in the group
		same_time = [err(sb, 30, title=f"smoke explore tie {i}") for i in range(5)]  # identical timestamps
		other = events.insert_event(schema.normalize_event(
			{"type": "error", "host": xhost, "bench": "b1", "site": sa, "title": "unrelated", "fingerprint": "smoke-other"},
			tz, now - timedelta(minutes=15)))
		frappe.db.commit()

		groups = explore.list_error_groups(range="24h", host=xhost)["groups"]
		g = next(x for x in groups if x["fingerprint"] == fp)
		assert g["records"] == 9 and g["records_in_window"] == 8 and g["sites"] == 2, g  # the whole group, as its page
		assert g["occurrences"] == 48, g  # 40 on the old record, inside the window or not
		assert g["first_seen"] < explore.list_error_groups(range="24h", host=xhost)["window"]["since"], g  # first seen days ago
		found = explore.list_events(range="24h", host=xhost, q="100%_sync")["events"]
		assert {e["name"] for e in found} == {old, *recent}, found  # % and _ matched literally
		assert not explore.list_events(range="24h", host=xhost, q="100x_sync")["events"], "_ matched a wildcard"
		# page through equal timestamps one by one: each record once
		seen, cursor = [], None
		while True:
			page = explore.list_events(range="24h", host=xhost, limit=2, cursor=cursor)
			seen += [e["name"] for e in page["events"]]
			if not page["paging"]["has_more"]:
				break
			cursor = page["paging"]["next_cursor"]
		assert len(seen) == len(set(seen)) == 9 and set(same_time) <= set(seen), seen
		assert not explore.list_events(range="24h", host=xhost, event_type="security")["events"]
		try:
			explore.list_events(event_type="gossip")
			raise AssertionError("unknown event type accepted")
		except frappe.ValidationError:
			pass
		detail = explore.get_error_group(fp)
		assert detail["records"] == 9 and len(detail["scopes"]) == 2, detail["scopes"]
		assert detail["title"] == g["title"] and detail["representative"]["name"] == g["latest"]["name"], (detail["title"], g)
		assert "KeyError" in detail["representative"]["payload"]["traceback"], detail["representative"]
		assert explore.get_event(recent[0])["payload"]["traceback"].startswith("Traceback"), "payload"

		user = "smoke-scoped@example.com"
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site", "value": sb}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			scoped = explore.get_error_group(fp)
			assert scoped["records"] == 6 and [s["site"] for s in scoped["scopes"]] == [sb], scoped["scopes"]
			sg = next(x for x in explore.list_error_groups(range="24h")["groups"] if x["fingerprint"] == fp)
			assert sg["sites"] == 1 and sg["occurrences"] == 6, sg  # the other site's 41 stay hidden
			try:
				explore.get_event(old)
				raise AssertionError("scoped user read another site's event")
			except frappe.PermissionError:
				pass
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()
		frappe.db.delete("Wolf Event", {"name": ("in", [old, ancient, *recent, *same_time, other])})
		frappe.db.commit()
		return ("group of 9 records (8 in the window) on 2 sites, 48 occurrences, same newest record in list and page, literal % _ search, "
		        "9 events paged by 2 without repeats, scoped user sees 6 records on 1 site")

	def metrics_explorer():
		"""Catalog rules, groups by label, interval sums, gaps, clipping and a scoped user."""
		from dodock_wolf.api import metrics
		from dodock_wolf.wolf import access

		mhost = "smoke-metrics"

		def sample(name, value, minutes_ago, **kw):
			return schema.normalize_metric({"metric_name": name, "value": value, "host": mhost, **kw}, tz,
			                               now - timedelta(minutes=minutes_ago))

		samples = []
		for m in range(3, 30):  # the last half hour: no data before it, so earlier buckets are gaps
			for mount, level in (("/", 50), ("/data", 91), ("/boot", 20)):
				samples.append(sample("disk_used_percent", level + (m % 3), m, labels={"mount": mount}))
			for site, count in (("ma.localhost", 3), ("mb.localhost", 5)):
				samples.append(sample("http_5xx", count, m, site=site, bench="b1"))
		samples.append(sample("smoke_custom_gauge", 7, 40))
		events.insert_metrics(samples)
		frappe.db.commit()
		rollups.run()  # the custom metric's minute is rolled: the catalog lists it as seen

		cat = {m["metric"]: m for m in metrics.get_metric_catalog()["metrics"]}
		assert cat["smoke_custom_gauge"]["kind"] == "unknown" and cat["smoke_custom_gauge"]["seen"], cat.get("smoke_custom_gauge")
		assert cat["http_5xx"]["default_aggregation"] == "sum" and "last" not in cat["http_5xx"]["aggregations"]

		disk = metrics.query_metric("disk_used_percent", "max", "host_label", range="1h", host=mhost)
		names = [s["name"] for s in disk["series"]]
		assert names == [f"{mhost} · mount=/data", f"{mhost} · mount=/", f"{mhost} · mount=/boot"], names  # highest first
		points = disk["series"][0]["points"]
		assert points[0][1] is None and any(v is not None for _, v in points), "early buckets are gaps, not zeros"
		assert disk["resolution"] == "raw" and disk["bucket_seconds"] == 60 and not disk["retention"]["clipped"], disk
		one = metrics.query_metric("disk_used_percent", "avg", "host", label="mount=/boot", range="1h", host=mhost)
		assert len(one["series"]) == 1 and one["series"][0]["value"] < 25, one["series"]

		http = metrics.query_metric("http_5xx", "sum", "site", range="1h", host=mhost)
		totals = {s["group"]["site"]: s["value"] for s in http["series"]}
		in_window = sum(1 for _, v in http["series"][0]["points"] if v is not None)
		assert set(totals) == {"ma.localhost", "mb.localhost"} and totals["mb.localhost"] > totals["ma.localhost"], totals
		assert sum(v for _, v in next(s for s in http["series"] if s["group"]["site"] == "mb.localhost")["points"] if v) == 5 * in_window
		for bad in (("disk_used_percent", "sum", None), ("http_5xx", "last", None), ("cpu_usage", "avg", "site")):
			try:
				metrics.query_metric(bad[0], bad[1], bad[2], range="1h")
				raise AssertionError(f"accepted {bad}")
			except frappe.ValidationError:
				pass
		assert metrics.query_metric("disk_used_percent", range="400d", host=mhost)["retention"]["clipped"], "clipping"
		from dodock_wolf.wolf import window as win_mod

		past = metrics.query_metric("disk_used_percent", host=mhost, since=win_mod.to_utc(now - timedelta(minutes=40), tz),
		                            until=win_mod.to_utc(now - timedelta(minutes=20), tz))
		assert not past["live"] and not any(s["stale"] for s in past["series"]), "a past window called stale"
		# minute rollups of the last hours count: the mounts are listed before any hourly rollup closes
		labels = metrics.get_labels("disk_used_percent", host=mhost)
		assert {"mount=/", "mount=/data", "mount=/boot"} <= set(labels["labels"]), labels
		day = metrics.query_metric("disk_used_percent", "max", "host_label", range="24h", host=mhost)
		assert day["live"] and not any(s["stale"] for s in day["series"]), "fresh series called stale on a 24h window"
		assert day["bucket_seconds"] == 720 and day["resolution"] == "1m", day["resolution"]

		user = "smoke-scoped@example.com"
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "host", "value": "smoke-host"}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			assert not metrics.query_metric("disk_used_percent", range="1h", host=mhost)["series"], "another host leaked"
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()
		return (f"3 mounts ranked by max with early gaps, mb 5xx summed per bucket, wrong aggregations refused, "
		        f"custom metric listed, 400d clipped, scoped user sees nothing of {mhost}")

	def live_updates():
		from dodock_wolf.wolf import live

		sent = []
		original = frappe.publish_realtime

		def record(event=None, message=None, room=None, **kw):
			if event == live.EVENT:  # Frappe's own docinfo/doc/list updates are not Wolf's
				sent.append((event, message, room))

		frappe.publish_realtime = record
		cache = frappe.cache()
		for kind in live.LIST_DOCTYPES:
			cache.delete_value(live._THROTTLE_KEY + kind)
			cache.delete_value(live._DIRTY_KEY + kind)
		frappe.db.commit()  # start from a fresh transaction: the bookkeeping is per transaction
		inc = None
		try:
			inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke live", "severity": "warning"})
			inc.insert(ignore_permissions=True)
			room = live.doc_room("Wolf Incident", inc.name)
			assert (live.EVENT, {"kind": "incident", "incident": inc.name}, room) in sent, sent
			assert (live.EVENT, {"kind": "incidents"}, live.doctype_room("Wolf Incident")) in sent, sent
			assert all(m.get("incident") in (None, inc.name) for _, m, _ in sent), "a list message names an incident"
			n = len(sent)
			inc.add_comment("Comment", "live smoke")
			assert len(sent) == n, f"second message to a room in one transaction: {sent[n:]}"

			frappe.db.commit()  # the next transaction, within the throttle window
			sent.clear()
			inc.add_comment("Comment", "live smoke 2")
			assert [r for _, _, r in sent] == [room], sent
			assert not cache.get_value(live._DIRTY_KEY + "incidents"), "marked dirty before the commit"
			frappe.db.commit()
			assert cache.get_value(live._DIRTY_KEY + "incidents"), "a throttled list message was dropped"

			sent.clear()
			live.flush()
			assert [m for _, m, _ in sent] == [{"kind": "incidents"}], sent
			assert not cache.get_value(live._DIRTY_KEY + "incidents")
			frappe.db.commit()

			sent.clear()
			inc.add_comment("Comment", "live smoke 3 (rolled back)")
			frappe.db.rollback()
			assert not cache.get_value(live._DIRTY_KEY + "incidents"), "a rolled-back change was marked dirty"
			inc.reload()
			inc.add_comment("Comment", "live smoke 4")  # the room is announced again after a rollback
			assert [r for _, _, r in sent].count(room) == 2, sent
		finally:
			frappe.publish_realtime = original
			frappe.flags.wolf_live_sent = None
			if inc:
				# Frappe keeps the comments of a deleted doc and gives its name back to the series:
				# the next incident would inherit them
				frappe.db.delete("Comment", {"reference_doctype": "Wolf Incident", "reference_name": inc.name})
				frappe.delete_doc("Wolf Incident", inc.name, force=True, ignore_permissions=True)
		return "doc and DocType rooms, one message per room and transaction, dirty only after commit, flushed"

	def app_security():
		from types import SimpleNamespace

		from dodock_wolf.wolf import local_signals

		frappe.db.set_single_value("Wolf Settings", "capture_app_security", 1)
		frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		since = now_datetime() - timedelta(seconds=1)

		def last(category):
			rows = frappe.get_all("Wolf Event", filters={"category": category, "creation": (">=", since)},
			                      fields=["title", "severity", "payload"], order_by="creation desc", limit=1)
			assert rows, f"no {category} event"
			return rows[0]

		seen = {}
		cleanup = []
		try:
			script = frappe.get_doc({"doctype": "Server Script", "name": "wolf-smoke-ping", "script_type": "API",
			                         "api_method": "wolf_smoke_ping", "script": "frappe.response['message'] = 'pong'"})
			script.insert(ignore_permissions=True)
			cleanup.append(("Server Script", script.name))
			e = last("server_script_change")
			assert e.severity == "critical" and "created" in e.title, e  # API scripts are critical
			script.description = "only the description"
			script.save(ignore_permissions=True)
			assert frappe.db.count("Wolf Event", {"category": "server_script_change", "creation": (">=", since)}) == 1
			seen["server script"] = e.title

			frappe.get_doc({"doctype": "Console Log", "script": "print(1)", "type": "Python"}).insert(ignore_permissions=True)
			seen["console"] = last("console_execution").title

			ss = frappe.get_doc("System Settings")
			# a site that never ran the setup wizard has no language / time zone, and Frappe
			# refuses the save: fill them with what the site already uses
			ss.language = ss.language or "en"
			ss.time_zone = ss.time_zone or events.system_tz()
			original = ss.session_expiry
			ss.session_expiry = "999:00"
			ss.save(ignore_permissions=True)
			e = last("security_settings_weakened")
			assert json.loads(e.payload)["changes"][0]["field"] == "session_expiry", e
			ss.reload()
			ss.session_expiry = original
			ss.save(ignore_permissions=True)
			seen["settings"] = e.title

			user = frappe.get_doc({"doctype": "User", "email": "wolf-apikey@example.com", "first_name": "Key",
			                       "send_welcome_email": 0}).insert(ignore_permissions=True)
			cleanup.append(("User", user.name))
			from frappe.core.doctype.user.user import generate_keys

			generate_keys(user.name)
			e = last("api_key_generated")
			assert e.severity == "warning" and user.name in e.title, e  # not a privileged user
			seen["api key"] = e.title

			# Webhook is named by prompt: give it one, as the Desk form asks for
			hook = frappe.get_doc({"doctype": "Webhook", "name": "wolf-smoke-hook", "__newname": "wolf-smoke-hook",
			                       "webhook_doctype": "ToDo", "webhook_docevent": "after_insert",
			                       "request_url": "https://hooks.example.com/wolf", "request_structure": "JSON",
			                       "webhook_json": "{}", "enabled": 1}).insert(ignore_permissions=True)
			cleanup.append(("Webhook", hook.name))
			assert json.loads(last("webhook_external").payload)["domain"] == "hooks.example.com"
			seen["webhook"] = "hooks.example.com"

			profile = frappe.get_doc({"doctype": "Role Profile", "role_profile": "Wolf Smoke Profile",
			                          "roles": [{"role": "System Manager"}]}).insert(ignore_permissions=True)
			cleanup.append(("Role Profile", profile.name))
			assert "created" in last("permission_change").title

			frappe.form_dict.update({"doctype": "ToDo", "role": "Guest", "permlevel": 0, "ptype": "read", "value": 1})
			local_signals.after_request(
				response=SimpleNamespace(status_code=200),
				request=SimpleNamespace(path="/api/method/frappe.core.page.permission_manager.permission_manager.update"),
			)
			e = last("permission_change")
			assert e.title == "Permission rule changed: Guest on ToDo", e
			assert any(t["id"] == "T1098" for t in json.loads(e.payload)["mitre_attack"]), e
			seen["permission manager"] = e.title
		finally:
			for key in ("doctype", "role", "permlevel", "ptype", "value"):
				frappe.form_dict.pop(key, None)
			for doctype, name in reversed(cleanup):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		return seen

	def permission_drift():
		"""Custom DocPerm and User Permission changes outside the Role Permission Manager, and a
		Website user given desk access (permission_change)."""
		from types import SimpleNamespace

		frappe.db.set_single_value("Wolf Settings", "capture_app_security", 1)
		frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		since = now_datetime() - timedelta(seconds=1)

		def drift(kind):
			rows = frappe.get_all("Wolf Event", filters={"category": "permission_change", "creation": (">=", since)},
			                      fields=["title", "severity", "payload"], order_by="creation desc")  # fmt: skip
			return [r for r in rows if json.loads(r.payload).get("kind") == kind]

		seen = {}
		cleanup = []
		request = getattr(frappe.local, "request", None)
		try:
			# a copy of a standard rule grants nothing (Frappe copies them all before the first custom one)
			standard = frappe.get_all("DocPerm", filters={"parent": "ToDo"}, fields="*", limit=1)[0]
			copy = frappe.new_doc("Custom DocPerm")
			copy.update({k: v for k, v in standard.items() if k not in ("name", "creation", "modified", "owner", "modified_by")})
			copy.insert(ignore_permissions=True)
			cleanup.append(("Custom DocPerm", copy.name))
			assert not drift("custom_docperm"), drift("custom_docperm")

			# Guest given read on ToDo, as Data Import or the REST API would: critical
			rule = frappe.get_doc({"doctype": "Custom DocPerm", "parent": "ToDo", "parenttype": "DocType", "parentfield": "permissions",
			                       "role": "Guest", "permlevel": 0, "read": 1}).insert(ignore_permissions=True)  # fmt: skip
			cleanup.append(("Custom DocPerm", rule.name))
			e = drift("custom_docperm")[0]
			# Custom DocPerm's defaults come with it (export, print, email...): all granted to Guest
			assert e.severity == "critical" and e.title.startswith("Permission rule added: Guest on ToDo, grants read"), e
			assert any(t["id"] == "T1098" for t in json.loads(e.payload)["mitre_attack"]), e
			seen["custom docperm"] = e.title

			# inside a Role Permission Manager call, after_request records it: no second event
			frappe.local.request = SimpleNamespace(path="/api/method/frappe.core.page.permission_manager.permission_manager.update")
			frappe.db.delete("Wolf Event", {"category": "permission_change", "creation": (">=", since)})
			rule.reload()
			rule.write = 1
			rule.save(ignore_permissions=True)
			assert not drift("custom_docperm"), drift("custom_docperm")
			frappe.local.request = request

			# User Permissions: the first restricts, the second widens, removing the last lifts it
			user = frappe.get_doc({"doctype": "User", "email": "wolf-drift@example.com", "first_name": "Drift",
			                       "send_welcome_email": 0}).insert(ignore_permissions=True)  # fmt: skip
			cleanup.append(("User", user.name))
			assert user.user_type == "Website User", user.user_type
			first = frappe.get_doc({"doctype": "User Permission", "user": user.name, "allow": "Role", "for_value": "Guest",
			                        "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)  # fmt: skip
			cleanup.append(("User Permission", first.name))
			assert not drift("user_permission"), drift("user_permission")
			second = frappe.get_doc({"doctype": "User Permission", "user": user.name, "allow": "Role", "for_value": "All",
			                         "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)  # fmt: skip
			e = drift("user_permission")[0]
			assert e.title == f"User Permission added: {user.name} may also see Role All", e
			frappe.delete_doc("User Permission", second.name, force=True, ignore_permissions=True)
			assert len(drift("user_permission")) == 1  # one of two removed: still restricted
			frappe.db.delete("Wolf Event", {"category": "permission_change", "creation": (">=", since)})
			frappe.delete_doc("User Permission", first.name, force=True, ignore_permissions=True)
			cleanup.remove(("User Permission", first.name))
			assert drift("user_permission")[0].title == f"User Permission removed: {user.name} no longer restricted on Role"
			seen["user permission"] = "second value added, last one removed"

			# the portal user gets a desk role
			desk_role = frappe.get_all("Role", filters={"desk_access": 1, "name": ("not in", ("Administrator", "System Manager"))},
			                           pluck="name", limit=1)[0]  # fmt: skip
			user.reload()
			user.append("roles", {"role": desk_role})
			user.save(ignore_permissions=True)
			assert user.user_type == "System User", user.user_type
			e = drift("desk_access")[0]
			assert e.title == f"Website user {user.name} given desk access ({desk_role})", e
			seen["desk access"] = e.title
		finally:
			frappe.local.request = request
			for doctype, name in reversed(cleanup):
				if frappe.db.exists(doctype, name):
					frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		return seen

	def exfiltration_check():
		"""Exports and list reads counted per user and hour, flushed as user_export_bytes, compared
		with each user's largest hour (data_exfiltration)."""
		from types import SimpleNamespace

		import redis

		from dodock_wolf.api import exfiltration as exfil

		frappe.db.set_single_value("Wolf Settings", {"capture_exfiltration": 1, "exfiltration_floor_mb": 1, "exfiltration_factor": 5})
		frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		frappe.cache.delete_keys("wolf_exfil")
		since = now_datetime() - timedelta(seconds=1)
		users = {k: f"wolf-exfil-{k}@example.com" for k in ("new", "usual", "never")}
		export = "/api/method/frappe.desk.reportview.export_query"

		def request(user, path, size, args=None, message=None):
			frappe.set_user(user)
			frappe.form_dict.clear()
			frappe.form_dict.update(args or {"doctype": "Customer"})
			frappe.local.response["message"] = message
			try:
				exfil.after_request(response=SimpleNamespace(status_code=200, content_length=size),
				                    request=SimpleNamespace(path=path, method="POST"))  # fmt: skip
			finally:
				frappe.set_user("Administrator")
				frappe.form_dict.clear()
				frappe.local.response.pop("message", None)

		def found(user):
			return frappe.get_all("Wolf Event", filters={"category": "data_exfiltration", "creation": (">=", since),
			                      "title": ("like", f"%{user}%")}, fields=["title", "severity", "payload"], order_by="creation")  # fmt: skip

		seen = {}
		try:
			# a site without history yet: a first large export is a warning, not critical
			request(users["new"], "/api/method/frappe.client.get_count", 5_000_000)  # not data taken out
			assert not found(users["new"])
			request(users["new"], export, 600_000)
			assert not found(users["new"])  # below the 1 MB floor
			request(users["new"], "/api/method/frappe.client.get_list", 600_000, message=[{"name": i} for i in range(40)])
			e = found(users["new"])
			assert [r.severity for r in e] == ["warning"] and "no export history" in e[0].title, e
			payload = json.loads(e[0].payload)
			assert payload["hour_bytes"] == 1_200_000 and payload["hour_rows"] == 40, payload
			assert {t["id"] for t in payload["mitre_attack"]} == {"T1567", "T1030"}, payload["mitre_attack"]
			request(users["new"], export, 600_000)
			assert len(found(users["new"])) == 1  # one event per user, hour and severity
			seen["no history"] = e[0].title

			# the hourly flush: last hour's counters become one sample per user
			last_hour = frappe.cache.make_key(f"wolf_exfil|{exfil._hour() - 1}")
			frappe.cache.hincrby(last_hour, f"{users['usual']}|bytes", 400_000)
			frappe.cache.hincrby(last_hour, f"{users['usual']}|requests", 3)
			assert exfil.flush_volumes() == 1 and not redis.Redis.exists(frappe.cache, last_hour)
			label = schema.label_key({"user": users["usual"]})
			assert frappe.db.get_value("Wolf Metric Sample", {"metric_name": "user_export_bytes", "label_key": label}, "value") == 400_000
			assert exfil.baseline_bytes(users["usual"]) == 400_000

			# a site with history: against the user's largest hour, or critical without one
			frappe.cache.set_value("wolf_exfil_learning", False, expires_in_sec=600)
			request(users["usual"], export, 1_600_000)  # 4x: usual enough
			assert not found(users["usual"])
			request(users["usual"], export, 400_000)  # 5x
			request(users["usual"], export, 6_000_000)  # 20x
			e = found(users["usual"])
			assert [r.severity for r in e] == ["warning", "critical"], e
			assert "20.0x their largest hour in 14 days" in e[1].title, e[1].title
			request(users["never"], export, 2_000_000)
			assert [r.severity for r in found(users["never"])] == ["critical"]
			seen["baseline"] = e[1].title
		finally:
			frappe.set_user("Administrator")
			frappe.cache.delete_keys("wolf_exfil")
			frappe.db.delete("Wolf Metric Sample", {"metric_name": "user_export_bytes"})
			frappe.db.set_single_value("Wolf Settings", {"exfiltration_floor_mb": 50})
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		return seen

	def api_key_ips():
		"""An API key used from an address outside the networks it was used from (api_key_new_ip)."""
		import base64
		from types import SimpleNamespace

		from dodock_wolf.api import api_keys

		since = now_datetime() - timedelta(seconds=1)
		frappe.cache.delete_keys(api_keys.CACHE_PREFIX)
		plain = "wolf-keyip@example.com"
		if not frappe.db.exists("User", plain):
			frappe.get_doc({"doctype": "User", "email": plain, "first_name": "KeyIP", "send_welcome_email": 0}).insert(ignore_permissions=True)

		def call(user, key, ip, status=200, scheme="token"):
			header = f"token {key}:secret" if scheme == "token" else "Basic " + base64.b64encode(f"{key}:secret".encode()).decode()
			frappe.set_user(user)
			previous_ip, frappe.local.request_ip = getattr(frappe.local, "request_ip", None), ip
			try:
				api_keys.after_request(response=SimpleNamespace(status_code=status),
				                       request=SimpleNamespace(path="/api/resource/ToDo", headers={"Authorization": header, "User-Agent": "smoke"}))  # fmt: skip
			finally:
				frappe.set_user("Administrator")
				frappe.local.request_ip = previous_ip  # later checks rely on it (rate limiter)

		def found():
			return frappe.get_all("Wolf Event", filters={"category": "api_key_new_ip", "creation": (">=", since)},
			                      fields=["title", "severity", "payload"], order_by="creation")  # fmt: skip

		def age(key, days):
			frappe.db.sql("update `tabWolf API Key IP` set first_seen = %s where api_key = %s", (now_datetime() - timedelta(days=days), key))
			frappe.cache.delete_keys(api_keys.CACHE_PREFIX)

		keys = ("smokekeyplain01", "smokekeyadmin01")
		try:
			call(plain, keys[0], "203.0.113.7")  # first address: the baseline
			call(plain, keys[0], "198.51.100.20", scheme="basic")  # within the key's first day: learnt
			call(plain, keys[0], "192.0.2.1", status=401)  # a refused request teaches nothing
			assert frappe.db.count("Wolf API Key IP", {"api_key": keys[0]}) == 2
			assert not found()
			age(keys[0], 3)
			call(plain, keys[0], "203.0.113.99")  # same /24 as a known address
			assert not found()
			call(plain, keys[0], "192.0.2.50")
			call(plain, keys[0], "192.0.2.50")  # once per key and address
			e = found()
			assert [r.severity for r in e] == ["warning"] and "192.0.2.50" in e[0].title, e
			payload = json.loads(e[0].payload)
			assert payload["known_count"] == 3 and payload["api_key"] == keys[0] and payload["user"] == plain, payload
			# a privileged user's key: critical
			call("Administrator", keys[1], "203.0.113.7")
			age(keys[1], 3)
			call("Administrator", keys[1], "2001:db8::1")
			e = found()
			assert [r.severity for r in e] == ["warning", "critical"], e
			# known addresses only touch last_seen, at most once a day
			call(plain, keys[0], "203.0.113.7")
			assert frappe.db.get_value("Wolf API Key IP", api_keys.row_name(keys[0], "203.0.113.7"), "last_seen") >= since
			before = frappe.db.count("Wolf API Key IP")
			frappe.db.sql("update `tabWolf API Key IP` set last_seen = %s where api_key = %s", (now_datetime() - timedelta(days=400), keys[1]))
			api_keys.purge()
			assert frappe.db.count("Wolf API Key IP") == before - 2
		finally:
			frappe.db.delete("Wolf API Key IP", {"api_key": ("in", keys)})
			frappe.cache.delete_keys(api_keys.CACHE_PREFIX)
		return f"{len(found())} events: " + "; ".join(r.title for r in found())

	def suricata_events():
		"""A Suricata alert as the agent ships it: ATT&CK from the rule, a block to propose, the preset."""
		from dodock_wolf.wolf import response

		name = events.insert_event(schema.normalize_event({
			"type": "security", "category": "network_ids_alert", "severity": "critical", "host": HOST, "source": "suricata",
			"site": SITE, "title": "Suricata: ET EXPLOIT smoke from 45.33.32.157",
			"fingerprint": schema.fingerprint(HOST, "suricata", 2999999, "45.33.32.157"),
			"payload": {"ip": "45.33.32.157", "sid": 2999999, "signature": "ET EXPLOIT smoke", "priority": 1, "count": 3,
			            "attack_techniques": ["T1190"], "flow_id": 123, "community_id": "1:abc="},
		}, tz, now_datetime()))  # fmt: skip
		ev = frappe.get_doc("Wolf Event", name)
		payload = json.loads(ev.payload)
		assert [t["id"] for t in payload["mitre_attack"]] == ["T1190"], payload  # from the rule's metadata
		assert payload["mitre_attack"][0]["name"], "known technique named"
		# (a documentation address such as 198.51.100.x would rightly not be proposed: not global)
		# api/response.py resolves the attacked host and the Wolf Agent on it
		proposals = response.suggest([{**ev.as_dict(), "payload": payload, "agent": "smoke-agent", "block_host": HOST,
		                                "block_agent": "smoke-agent"}])  # fmt: skip
		assert any(p["action"] == "block_ip" and p["target"] == "45.33.32.157" for p in proposals), proposals
		rule = frappe.get_doc("Wolf Alert Rule", "Network IDS alert (critical)")
		assert (rule.event_category, rule.min_severity, rule.severity) == ("network_ids_alert", "critical", "critical"), rule.as_dict()
		return f"{ev.name}: ATT&CK {payload['mitre_attack'][0]['id']}, block proposed, preset installed"

	def wazuh_events():
		"""A Wazuh alert as the agent ships it: host where it happened, ATT&CK from the rule, the preset."""
		name = events.insert_event(schema.normalize_event({
			"type": "security", "category": "hids_alert", "severity": "warning", "host": "web01", "source": "wazuh",
			"title": "Wazuh: Three failed attempts to run sudo on web01",
			"fingerprint": schema.fingerprint("web01", "wazuh", "5404", "web01"),
			"payload": {"rule_id": "5404", "level": 10, "user": "deploy", "attack_techniques": ["T1548.003"],
			            "wazuh_agent": {"id": "000", "name": "wazuh-manager"}, "count": 1},
		}, tz, now_datetime()))  # fmt: skip
		ev = frappe.get_doc("Wolf Event", name)
		payload = json.loads(ev.payload)
		assert ev.host == "web01" and [t["id"] for t in payload["mitre_attack"]] == ["T1548.003"], (ev.host, payload)
		rule = frappe.get_doc("Wolf Alert Rule", "Host intrusion alert (critical)")
		assert (rule.event_category, rule.min_severity) == ("hids_alert", "critical"), rule.as_dict()
		return f"{ev.name} on {ev.host}: ATT&CK {payload['mitre_attack'][0]['id']}, preset installed"

	def wazuh_integration():
		"""The Wazuh integration route: an `integration` agent posts raw alerts to api/wazuh.alert."""
		from frappe.utils.password import get_decrypted_password
		from werkzeug.test import EnvironBuilder

		from dodock_wolf import tasks
		from dodock_wolf.api import agent as agent_api
		from dodock_wolf.api import wazuh as wazuh_api

		def post(body, headers=None):
			frappe.local.request = EnvironBuilder(method="POST", json=body, headers=headers or {}).get_request()
			frappe.local.request_ip = "127.0.0.1"

		saved_request, saved_ip = getattr(frappe.local, "request", None), getattr(frappe.local, "request_ip", None)
		alert = {"timestamp": "2026-11-02T22:50:24.782+0000", "id": "1793666224.1",
		         "rule": {"level": 10, "description": "Three failed attempts to run sudo", "id": "5404",
		                  "mitre": {"id": ["T1548.003"]}, "groups": ["syslog", "sudo"]},
		         "agent": {"id": "000", "name": "wazuh-manager"}, "predecoder": {"hostname": "erp-web02"},
		         "data": {"srcuser": "deploy"}, "location": "172.18.0.8",
		         "full_log": "erp-web02 sudo:   deploy : 3 incorrect password attempts ; USER=root"}  # fmt: skip
		try:
			token = get_decrypted_password("Wolf Settings", "Wolf Settings", "registration_token")
			post({"registration_token": token, "hostname": "smoke-wazuh-manager", "kind": "integration"})
			creds = agent_api.register()
			headers = {"X-Wolf-Agent-Id": creds["agent_id"], "X-Wolf-Agent-Secret": creds["agent_secret"]}
			assert frappe.db.get_value("Wolf Agent", creds["agent_id"], "kind") == "integration"
			results = []
			for _ in range(3):
				post(alert, headers)
				results.append(wazuh_api.alert())
			names = {r["event"] for r in results}
			assert all(r["stored"] for r in results) and len(names) == 1, results  # repeats merge
			ev = frappe.get_doc("Wolf Event", names.pop())
			assert (ev.category, ev.host, ev.count, ev.agent) == ("hids_alert", "erp-web02", 3, creds["agent_id"]), ev.as_dict()
			assert [t["id"] for t in json.loads(ev.payload)["mitre_attack"]] == ["T1548.003"]
			post({**alert, "rule": {**alert["rule"], "id": "100903", "groups": ["dodock_wolf"]}}, headers)
			skipped = wazuh_api.alert()
			assert not skipped["stored"] and "dodock_wolf" in skipped["reason"], skipped  # no loop back into Wolf
			post(alert, {**headers, "X-Wolf-Agent-Secret": "wrong"})
			try:
				wazuh_api.alert()
				raise AssertionError("wrong secret accepted")
			except frappe.AuthenticationError:
				frappe.clear_messages()
			# an integration is quiet when there is nothing to report: never reported silent
			frappe.db.set_value("Wolf Agent", creds["agent_id"], "last_seen", now_datetime() - timedelta(hours=3))
			tasks.check_agents()
			assert not frappe.db.get_value("Wolf Agent", creds["agent_id"], "silence_reported")
		finally:
			frappe.local.request, frappe.local.request_ip = saved_request, saved_ip
		frappe.delete_doc("Wolf Agent", creds["agent_id"], ignore_permissions=True, force=True)
		return f"3 alerts → {ev.name} (count {ev.count}) on {ev.host}; loop guard and wrong secret refused; never silent"

	def entities_check():
		"""One IP and one host across Wolf, Suricata and Wazuh events (#72 step 3)."""
		from dodock_wolf.api import entities as entities_api
		from dodock_wolf.api import explore

		ip = "45.33.32.201"
		alias = frappe.get_doc({"doctype": "Wolf Entity Alias", "kind": "host", "alias": "WAZUH-ERP02", "canonical": "erp-web02"})
		alias.insert(ignore_permissions=True)
		entities_api.learn("host", "10.9.0.7", "erp-web02", "smoke")
		entities_api.learn("host", "WAZUH-ERP02", "someone-else", "smoke")  # a Manual alias is never overwritten
		assert frappe.db.get_value("Wolf Entity Alias", alias.name, "canonical") == "erp-web02"
		entities_api.learn_from_registration("bench-entities", "10.9.0.8", [{"name": "b", "site_domains": {"www.smoke.example.com": SITE}}])
		sources = [
			{"type": "security", "category": "web_attack_probe", "source": "nginx", "host": "erp-web02", "site": SITE,
			 "title": "entities smoke: wolf", "payload": {"ip": ip, "users": ["Smoke@Example.com"]}},
			{"type": "security", "category": "network_ids_alert", "source": "suricata", "host": "bench-entities",
			 "title": "entities smoke: suricata", "payload": {"ip": ip, "src_ip": ip, "dest_ip": "10.9.0.8",
			                                                  "http_hostname": "www.smoke.example.com"}},
			{"type": "security", "category": "hids_alert", "source": "wazuh", "host": "wazuh-erp02",
			 "title": "entities smoke: wazuh", "payload": {"ip": ip, "user": "deploy",
			                                               "wazuh_agent": {"id": "004", "name": "wazuh-erp02", "ip": "10.9.0.7"}}},
		]  # fmt: skip
		names = [events.insert_event(schema.normalize_event(raw, tz, now_datetime())) for raw in sources]
		found = json.loads(frappe.db.get_value("Wolf Event", names[1], "payload"))["entities"]
		assert found == {"ip": [ip], "host": ["bench-entities"], "site": [SITE]}, found  # dest_ip is the host, HTTP host the site
		def sources_of(result):  # the events of this check only (earlier checks used erp-web02 too)
			return sorted(e["source"] for e in result["events"] if e["name"] in names)

		by_ip = explore.list_events(range="1h", entity=f"ip:{ip}")
		assert sources_of(by_ip) == ["nginx", "suricata", "wazuh"], by_ip["events"]
		by_host = explore.list_events(range="1h", entity="host:ERP-WEB02")
		assert sources_of(by_host) == ["nginx", "wazuh"], by_host["events"]  # wazuh-erp02 is erp-web02
		assert sources_of(entities_api.find("site:" + SITE, range="1h")) == ["nginx", "suricata"]
		assert sources_of(entities_api.find("user:smoke@example.com", range="1h")) == ["nginx"]
		try:
			explore.list_events(range="1h", entity="ip:not-an-ip")
			raise AssertionError("bad entity accepted")
		except frappe.ValidationError:
			frappe.clear_messages()
		frappe.db.delete("Wolf Event", {"name": names[0]})
		entities_api.purge(now_datetime() + timedelta(minutes=1))
		assert not frappe.db.exists("Wolf Event Entity", {"event": names[0]}) and frappe.db.exists("Wolf Event Entity", {"event": names[1]})
		frappe.db.delete("Wolf Entity Alias", {"seen_from": ("in", ("smoke", "agent bench-entities", "agent bench-entities, bench b"))})
		alias.delete(ignore_permissions=True)
		return f"{sources_of(by_ip)} by IP, {sources_of(by_host)} by host under 3 names, site by domain, purge"

	def entity_correlation():
		"""Events of other scopes and sources join the incident naming the same IP (#72 step 5)."""
		from dodock_wolf.api import incident_view
		from dodock_wolf.wolf import access

		ip, site, tz = "45.33.32.202", "corr.localhost", events.system_tz()
		at = now_datetime()

		def ev(raw, minutes=0):
			e = schema.normalize_event({"type": "security", "severity": "warning", **raw}, tz, at + timedelta(minutes=minutes))
			return events.insert_event(e), e

		def attach(raw, minutes=0):
			return incidents.attach_to_open_incident(*ev(raw, minutes))

		def ids(title, src, **kw):
			return {"category": "network_ids_alert", "source": "suricata", "host": "corr-ids", "title": title,
			        "payload": {"ip": src, "src_ip": src, "dest_ip": "10.77.0.1"}, **kw}  # fmt: skip

		def incident(title, **scope):
			return frappe.get_doc({"doctype": "Wolf Incident", "title": title, "severity": "warning", "status": "Open",
			                       "started_at": at - timedelta(minutes=20), **scope}).insert(ignore_permissions=True)  # fmt: skip

		probe, _ = ev({"category": "web_attack_probe", "source": "nginx", "host": "corr-web", "site": site,
		               "title": "corr probe", "payload": {"ip": ip, "users": ["Jane@Corr.example"]}}, -20)  # fmt: skip
		inc = incident("corr incident", site=site)
		incidents.link_events(inc.name, [probe])
		first, first_event = ev(ids("corr ids", ip))
		assert incidents.attach_to_open_incident(first, first_event) == inc.name, "same IP on another host not grouped"
		# a repeat folded into a linked event stays where it is
		assert incidents.attach_to_open_incident(first, first_event) == inc.name
		assert attach({"category": "new_admin_ip", "source": "frappe", "host": "corr-other", "site": "corr-b.localhost",
		               "title": "corr admin", "payload": {"user": "jane@corr.example"}}) == inc.name, "same e-mail user not grouped"  # fmt: skip
		kept_out = {
			"another attacker hitting the same server": ids("corr other attacker", "45.33.32.203"),
			"a private address": ids("corr private", "10.20.0.9"),
			"a login name": {"category": "ssh_accepted", "source": "auth", "host": "corr-hids", "title": "corr root",
			                 "payload": {"user": "root"}},
			"a failed login naming the user": {"category": "frappe_failed_login", "source": "frappe", "host": "corr-other",
			                                   "site": "corr-c.localhost", "title": "corr failed",
			                                   "payload": {"user": "jane@corr.example", "ip": "198.51.100.40"}},
		}  # fmt: skip
		for why, raw in kept_out.items():
			got = attach(raw)
			assert got is None, f"{why} grouped into {got}"
		assert attach(ids("corr late", ip), 200) is None, "an IP seen 3 hours later grouped"

		# the IP decides, not the site: an open incident of the event's own site does not take it
		own = incident("corr own site", site="corr-d.localhost")
		assert attach(ids("corr own", ip, site="corr-d.localhost")) == inc.name, "grouped by site instead of by IP"
		assert attach(ids("corr site only", "45.33.32.177", site="corr-d.localhost")) is None, "attached by site alone"
		frappe.db.set_value("Wolf Incident", own.name, "status", "Resolved")
		# a rule's evidence is its own: its events come back from the incident that took them by IP
		taken, taken_event = ev(ids("corr taken", ip, host="corr-e"))
		assert incidents.attach_to_open_incident(taken, taken_event) == inc.name
		host_inc = incident("corr host", host="corr-e")
		incidents.link_events(host_inc.name, [taken, probe])
		assert frappe.db.get_value("Wolf Event", taken, "incident") == host_inc.name, "rule evidence left elsewhere"
		assert frappe.db.get_value("Wolf Event", probe, "incident") == inc.name, "in-scope evidence moved"
		assert frappe.db.get_value("Wolf Incident", inc.name, "event_count") == 4, "count not refreshed"

		frappe.db.set_single_value("Wolf Settings", "correlate_by_entity", 0)
		frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		try:
			off = attach(ids("corr off", ip))
		finally:
			frappe.db.set_single_value("Wolf Settings", "correlate_by_entity", 1)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		assert off is None, f"grouped by IP with the setting off: {off}"
		assert frappe.db.get_single_value("Wolf Settings", "correlate_by_entity") == 1, "not on by default"

		timeline = {r.title for r in incidents.get_timeline(inc.name)}
		assert {"corr probe", "corr ids", "corr admin"} <= timeline, timeline
		# a user of the incident's site does not see the events it took from other scopes
		user = "smoke-corr@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Corr", "send_welcome_email": 0,
			                "roles": [{"role": "Wolf User"}]}).insert(ignore_permissions=True)  # fmt: skip
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site", "value": site}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			desk = {r["title"] for r in ui.get_incident_timeline(inc.name)["events"]}
			spa = {r["summary"] for r in incident_view.get_timeline(inc.name)["rows"] if r["kind"] == "event"}
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()
		assert desk == spa == {"corr probe"}, (desk, spa)

		for name in (inc.name, host_inc.name):  # host_inc holds an event of the IP too
			frappe.db.set_value("Wolf Incident", name, "status", "Resolved")
		assert attach(ids("corr after", ip)) is None, "attached to a resolved incident"
		return (f"{inc.name}: probe + Suricata on another host + e-mail user; other attacker, private IP, login name, "
		        "failed login, late IP, setting off, resolved kept out; own site first; rule evidence returned; "
		        "scoped user sees its site only")  # fmt: skip

	def detector_modes():
		"""Wolf's own detectors next to Suricata and Wazuh: own, both (one finding), external (#72 step 4)."""
		from dodock_wolf.api import detectors as detectors_api
		from dodock_wolf.api import entities as entities_api
		from dodock_wolf.api import ingest as ingest_api
		from dodock_wolf.api import siem as siem_api

		tz, at = events.system_tz(), now_datetime()

		def mode(**values):
			for field, value in values.items():
				frappe.db.set_single_value("Wolf Settings", field, value)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")

		def ev(category, source, ip, minutes=0, technique="T1190", host="dm-web", payload=None, **kw):
			# as the agent sends them: techniques in attack_techniques, normalize turns them into mitre_attack
			data = {"ip": ip, **({"attack_techniques": [technique]} if technique else {}), **(payload or {})} if ip else payload or {}
			return schema.normalize_event({"type": "security", "severity": "warning", "category": category, "source": source,
			                               "host": host, "title": f"dm {category} {ip}", "payload": data, **kw}, tz,
			                              at + timedelta(minutes=minutes))  # fmt: skip

		def dup(name):
			return frappe.db.get_value("Wolf Event", name, "duplicate_of")

		agent = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "dm-agent", "kind": "agent"}).insert(ignore_permissions=True)
		try:
			mode(web_detection_mode="both", host_detection_mode="own")
			ids = events.insert_event(ev("network_ids_alert", "suricata", "45.33.32.240", -3))
			probe = events.insert_event(ev("web_attack_probe", "nginx", "45.33.32.240"))
			assert dup(probe) == ids, "the probe is not the same finding as the Suricata alert"
			assert not dup(ids)
			other_technique = events.insert_event(ev("web_attack_probe", "nginx", "45.33.32.240", technique="T1110"))
			other_ip = events.insert_event(ev("web_attack_probe", "nginx", "45.33.32.241"))
			late = events.insert_event(ev("web_attack_probe", "nginx", "45.33.32.240", 30))
			assert not any(map(dup, (other_technique, other_ip, late))), "linked across techniques, IPs or time"
			# a critical alert linked to a warning one still reaches a collector that takes critical only
			critical = events.insert_event(ev("network_ids_alert", "suricata", "45.33.32.241", 1, severity="critical"))
			assert dup(critical) == other_ip, "the critical alert is not linked"
			since = {"event_creation": str(at - timedelta(minutes=1))}
			_scanned, kept = siem_api._event_rows(since, ["security"], 0, now_datetime() + timedelta(minutes=1))
			assert ids in {r.name for r in kept} and probe not in {r.name for r in kept}, "the same finding sent twice"
			_scanned, kept = siem_api._event_rows(since, ["security"], 2, now_datetime() + timedelta(minutes=1))
			assert critical in {r.name for r in kept}, "a critical duplicate of a warning event lost"
			mode(web_detection_mode="own")
			again = events.insert_event(ev("web_attack_probe", "nginx", "45.33.32.240", 1))
			assert not dup(again), "linked in own mode"

			# external: auth.log signals give way to Wazuh alerts about the host, under its Wazuh name too,
			# when they watch logins; a file-integrity alert does not stand in for SSH detection
			mode(host_detection_mode="external")
			entities_api.learn("host", "dm-wazuh-name", "dm-host.example.com", "smoke")
			ssh = ev("ssh_failed_login", "sshd", "45.33.32.242", technique=None, host="dm-host.example.com")
			assert ingest_api.store_batch(agent.name, [], [ssh], correlate=False)["dropped"] == 0, "dropped while Wazuh is quiet"
			events.insert_event(ev("hids_alert", "wazuh", None, host="dm-wazuh-name",
			                       payload={"groups": ["ossec", "syscheck"], "attack_techniques": ["T1565.001"]}))  # fmt: skip
			assert ingest_api.store_batch(agent.name, [], [ssh], correlate=False)["dropped"] == 0, "a FIM alert stood in"
			events.insert_event(ev("hids_alert", "wazuh", "45.33.32.243", technique=None, host="dm-wazuh-name",
			                       payload={"groups": ["syslog", "sshd", "authentication_failed"]}))  # fmt: skip
			got = ingest_api.store_batch(agent.name, [], [ssh, ev("ssh_failed_login", "sshd", "45.33.32.242", host="dm-other")],
			                             correlate=False)  # fmt: skip
			assert (got["events"], got["dropped"]) == (1, 1), f"Wazuh covers dm-host only: {got}"
			assert frappe.db.get_value("Wolf Agent", agent.name, "own_events_dropped") == 1, "the drop is not counted"
		finally:
			mode(web_detection_mode="own", host_detection_mode="own")
			frappe.db.delete("Wolf Entity Alias", {"seen_from": "smoke", "alias": "dm-wazuh-name"})
			frappe.cache.delete_value(entities_api.CACHE_KEY)
		frappe.db.delete("Wolf Event", {"title": ("like", "dm %")})
		frappe.delete_doc("Wolf Agent", agent.name, ignore_permissions=True, force=True)
		assert detectors_api.original_severities([]) == {}
		return ("both: probe and Suricata alert one finding, sent to the SIEM once, a critical duplicate still sent; other "
		        "technique, IP, time and own mode apart; external: auth.log kept while Wazuh is quiet or only checks files, "
		        "dropped under the host's Wazuh name, counted on the agent")  # fmt: skip

	def three_sources_one_incident():
		"""Real agent output, end to end (#72 tests): the agent's parsers on the real Suricata and
		Wazuh fixtures (agent/tests/data) and on nginx and auth.log lines, all naming one attacker,
		through the ingest path. One agent reads nginx and Suricata on the bench host, as deployed.
		Everything arrives first, as in an attack; the shipped IDS preset then opens the incident,
		which takes the rest by IP (incidents.adopt_related).
		Once per detector mode: own (all kept), both (Wolf's events are the same finding as the
		external alert), external (Wolf's own web and SSH events give way)."""
		from datetime import timezone

		from dodock_wolf.api import entities as entities_api
		from dodock_wolf.api import ingest as ingest_api
		from dodock_wolf.wolf import rules as rules_mod

		agent_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
		if agent_dir not in sys.path:
			sys.path.insert(0, agent_dir)
		from wolf_agent.parsers import PARSERS

		data = os.path.join(agent_dir, "tests", "data")
		tz = events.system_tz()
		agent = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "three-agent", "kind": "agent"}).insert(ignore_permissions=True)
		rule = frappe.get_doc("Wolf Alert Rule", "Network IDS alert (critical)")
		fired_here = []  # every incident the preset opened, other checks' hosts included: resolved at the end

		def mode(web, host):
			frappe.db.set_single_value("Wolf Settings", "web_detection_mode", web)
			frappe.db.set_single_value("Wolf Settings", "host_detection_mode", host)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")

		def parse(name, lines, host, **kw):
			at = datetime.now(timezone.utc)
			p = PARSERS[name](host, **kw)
			for line in lines:
				p.feed(line)
			out = p.drain(at)[1]
			for e in out:  # the fixtures' own times are days old: rules look at the last minutes
				e["timestamp"] = at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
			return out

		def fixture(name, ip, hids_host):
			# the Wazuh agent's host is new each run: the external SSH drop must come from this run's alerts
			with open(os.path.join(data, name)) as f:
				return [line.replace("198.51.100.23", ip).replace("2001:db8:4::17", ip).replace("bench-02", hids_host)
				        for line in f.read().splitlines()]  # fmt: skip

		def store(raw):
			normalized = [schema.normalize_event(e, tz, now_datetime(), default_host=e.get("host")) for e in raw]
			return ingest_api.store_batch(agent.name, [], normalized, correlate=True)

		def scenario(run, ip):
			ids_host, hids_host = f"three-ids-{run}", f"three-hids-{run}"
			suricata = parse("suricata", fixture("suricata_eve_et_open.json", ip, hids_host), ids_host, log_file="eve.json", local={"192.0.2.10"},
			                 site_benches={"erp.example.com": "b3"})  # fmt: skip
			# as it happens: every detector reports within one push, the rule runs after (each minute)
			store(suricata)
			store(parse("wazuh", fixture("wazuh_alerts_lab.json", ip, hids_host), "three-wazuh", log_file="alerts.json"))
			t = datetime.now(timezone.utc)
			web = store(parse("nginx", [
				f'{ip} - - [{t:%d/%b/%Y:%H:%M:%S} +0000] "GET /api/method/frappe.client.get_list?doctype=User&filters='
				f'1%27%20UNION%20ALL%20SELECT%20NULL-- HTTP/1.1" 403 466 "-" "sqlmap/1.8.2#stable (https://sqlmap.org)"',
				f'{ip} - - [{t:%d/%b/%Y:%H:%M:%S} +0000] "GET /.env HTTP/1.1" 404 153 "-" "Mozilla/5.0"',
			], ids_host, log_file="/var/log/nginx/access.log", default_site="three.localhost", default_bench="b3"))  # fmt: skip
			auth = store(parse("auth", [f"{t:%b %e %H:%M:%S} {hids_host} sshd[{i}]: Failed password for root from {ip} port 5{i:04d} ssh2"
			                            for i in range(8)]  # fmt: skip
			                   + [f"{t:%b %e %H:%M:%S} {hids_host} sshd[99]: Accepted password for root from {ip} port 51999 ssh2"],
			                   hids_host, log_file="/var/log/auth.log"))
			# kept out: the same IP 3 hours ago, and an event another incident holds
			old = schema.normalize_event({"type": "security", "category": "web_attack_probe", "source": "nginx", "host": ids_host,
			                              "severity": "warning", "title": f"three old {run}", "payload": {"ip": ip}},
			                             tz, now_datetime() - timedelta(hours=3))  # fmt: skip
			old = events.insert_event(old, agent=agent.name)
			held = frappe.get_doc({"doctype": "Wolf Incident", "title": f"three held {run}", "severity": "warning", "status": "Open",
			                       "host": f"three-other-{run}", "started_at": now_datetime()}).insert(ignore_permissions=True)  # fmt: skip
			other = events.insert_event(schema.normalize_event({"type": "security", "category": "ssh_failed_login", "source": "sshd",
			                                                    "host": f"three-other-{run}", "severity": "warning",
			                                                    "title": f"three held {run}", "payload": {"ip": ip}},
			                                                   tz, now_datetime()), agent=agent.name)  # fmt: skip
			frappe.db.set_value("Wolf Event", other, "incident", held.name)
			fired = rules_mod.evaluate(rule)["fired"]
			fired_here.extend(fired + [held.name])
			inc = frappe.db.get_value("Wolf Incident", {"name": ("in", fired or [""]), "host": ids_host}, "name")
			assert inc, f"{run}: the IDS preset opened no incident for {ids_host}: {fired}"
			assert not frappe.db.get_value("Wolf Event", old, "incident"), "an event 3 hours old taken"
			assert frappe.db.get_value("Wolf Event", other, "incident") == held.name, "another incident's event taken"
			rows = frappe.get_all("Wolf Event", filters={"incident": inc}, fields=["name", "source", "category", "duplicate_of", "severity"])
			# ET's info rules about the same client (log4j hunting) stay out, as at ingest
			assert not [r for r in rows if r.severity == "info"], "info events taken"
			assert frappe.db.exists("Wolf Event", {"agent": agent.name, "severity": "info", "source": "suricata",
			                                      "payload": ("like", f'%"{ip}"%')}), "no info alert to keep out"  # fmt: skip
			count = frappe.db.get_value("Wolf Incident", inc, "event_count")
			assert count == len(rows), f"event count {count}, {len(rows)} linked"
			# the IDS alerts are the rule's evidence; the rest joined by IP and says so
			by_entity = dict(frappe.get_all("Wolf Event", filters={"incident": inc}, fields=["name", "incident_by_entity"], as_list=True))
			joined = [r for r in rows if r.category != "network_ids_alert"]
			assert joined and all(by_entity[r.name] for r in joined), [(r.category, by_entity[r.name]) for r in joined]
			return inc, rows, web, auth

		def sources(rows):
			return sorted({r.source for r in rows})

		try:
			mode("own", "own")
			inc, rows, web, auth = scenario("own", "45.33.32.214")
			assert sources(rows) == ["nginx", "sshd", "suricata", "wazuh"], (inc, sources(rows))
			assert not any(r.duplicate_of for r in rows), "linked in own mode"
			own = len(rows)

			mode("both", "both")
			inc, rows, web, auth = scenario("both", "45.33.32.215")
			assert sources(rows) == ["nginx", "sshd", "suricata", "wazuh"], (inc, sources(rows))
			mine = [r for r in rows if r.source in ("nginx", "sshd")]
			assert {r.source for r in mine} == {"nginx", "sshd"}, mine
			for r in mine:
				# the finding it joins: the other detector's alert about the same IP (any of them: the IDS
				# preset took only its critical ones onto the incident); web pairs with Suricata, SSH with Wazuh
				other = frappe.db.get_value("Wolf Event", r.duplicate_of, ["source", "payload"], as_dict=True) if r.duplicate_of else None
				expected = "suricata" if r.source == "nginx" else "wazuh"
				assert other and other.source == expected and json.loads(other.payload or "{}").get("ip") == "45.33.32.215", (
					r.name, r.category, other)
			assert not any(r.duplicate_of for r in rows if r.source in ("suricata", "wazuh")), "an external alert linked"

			mode("external", "external")
			inc, rows, web, auth = scenario("external", "45.33.32.216")
			assert sources(rows) == ["suricata", "wazuh"], (inc, sources(rows))
			assert (web["events"], web["dropped"]) == (0, 1), f"the web probe kept: {web}"
			assert auth["events"] == 0 and auth["dropped"] >= 2, f"SSH events kept while Wazuh watches bench-02: {auth}"
		finally:
			mode("own", "own")
			frappe.db.commit()  # store_batch committed the modes: a failed run must not leave them set
		# leave nothing for later checks: the incidents the preset opened (on other checks' hosts too),
		# these events (critical hids_alerts a later evaluation would take), the aliases learnt
		for name in set(fired_here):
			if frappe.db.get_value("Wolf Incident", name, "status") != "Resolved":
				incidents.resolve(name, "smoke: three sources")
		frappe.db.delete("Wolf Event", {"agent": agent.name})
		frappe.db.delete("Wolf Entity Alias", {"canonical": ("like", "three-hids-%")})
		frappe.cache.delete_value(entities_api.CACHE_KEY)
		frappe.delete_doc("Wolf Agent", agent.name, ignore_permissions=True, force=True)
		return (f"Suricata (ET Open), Wazuh (manager and agent), nginx and auth.log about one IP, one incident from the IDS "
		        f"preset ({own} events); both: Wolf's web and SSH events the same finding as Suricata's and Wazuh's; "
		        f"external: Wolf's {web['dropped']} web and {auth['dropped']} SSH events dropped")  # fmt: skip

	def timeline_related():
		"""An incident's timeline shows the changes and health of the scopes its events came from."""
		from dodock_wolf.api import incident_view
		from dodock_wolf.wolf import access

		ip, site, tz, at = "45.33.32.230", "story.localhost", events.system_tz(), now_datetime()

		def ev(title, minutes, raw):
			e = schema.normalize_event({"severity": "warning", "title": title, **raw}, tz, at + timedelta(minutes=minutes))
			return events.insert_event(e), e

		probe, _ = ev("story probe", -15, {"type": "security", "category": "web_attack_probe", "host": "story-web",
		                                   "site": site, "payload": {"ip": ip}})  # fmt: skip
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "story incident", "site": site, "severity": "warning",
		                      "status": "Open", "started_at": at - timedelta(minutes=15)}).insert(ignore_permissions=True)  # fmt: skip
		incidents.link_events(inc.name, [probe])
		ids = incidents.attach_to_open_incident(*ev("story ids", -10, {"type": "security", "category": "network_ids_alert",
		                                                               "host": "story-db", "payload": {"ip": ip}}))  # fmt: skip
		assert ids == inc.name, ids
		ev("story deploy", -12, {"type": "deployment", "severity": "info", "host": "story-db", "bench": "db-bench"})
		ev("story cron", -5, {"type": "cron_failure", "host": "story-db", "bench": "db-bench", "site": "db.localhost"})
		ev("story site error", -5, {"type": "error", "host": "story-db", "bench": "db-bench", "site": "db.localhost"})
		ev("story noise", -5, {"type": "security", "category": "web_attack_probe", "host": "story-db", "payload": {"ip": "45.33.32.231"}})
		ev("story elsewhere", -5, {"type": "cron_failure", "host": "story-other", "bench": "x"})
		ev("story old deploy", -200, {"type": "deployment", "severity": "info", "host": "story-db", "bench": "db-bench"})
		desk = {r.title for r in incidents.get_timeline(inc.name)}
		spa = {r["summary"] for r in incident_view.get_timeline(inc.name)["rows"] if r["kind"] in ("event", "deployment")}
		want = {"story probe", "story ids", "story deploy", "story cron"}
		assert desk == spa == want, (desk, spa)
		one_by_one, cursor = [], None
		while True:  # the same rows whatever the page size
			page = incident_view.get_timeline(inc.name, limit=1, cursor=cursor, families="evidence,context")
			one_by_one += [r["id"] for r in page["rows"]]
			cursor = page["paging"].get("next_cursor")
			if not cursor:
				break
		assert one_by_one == [r["id"] for r in incident_view.get_timeline(inc.name, families="evidence,context")["rows"]]
		# a user of the incident's site sees neither the other host's events nor its changes
		user = "smoke-story@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Story", "send_welcome_email": 0,
			                "roles": [{"role": "Wolf User"}]}).insert(ignore_permissions=True)  # fmt: skip
		frappe.db.delete("Wolf User Scope", {"user": user})
		frappe.get_doc({"doctype": "Wolf User Scope", "user": user, "scope_type": "site", "value": site}).insert()
		access.clear_cache()
		frappe.set_user(user)
		try:
			scoped = {r["summary"] for r in incident_view.get_timeline(inc.name)["rows"] if r["kind"] in ("event", "deployment")}
			scoped_desk = {r.title for r in ui.get_incident_timeline(inc.name)["events"]}
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Wolf User Scope", {"user": user})
			access.clear_cache()
		assert scoped == scoped_desk == {"story probe"}, (scoped, scoped_desk)
		frappe.db.delete("Wolf Event", {"title": ("like", "story %")})
		frappe.delete_doc("Wolf Incident", inc.name, force=True, ignore_permissions=True)
		return f"{inc.name}: story-db's deployment and failed cron beside the attack; its probes, its sites' errors, other hosts, older events left out; paged alike; a site user sees its site in Desk and the Wolf UI"

	def sequence_rules():
		"""A then B on the same IP, user or host, from the three presets (#72 step 5)."""
		from dodock_wolf.wolf.presets import PRESETS

		tz, at = events.system_tz(), now_datetime()
		names = {}

		def ev(key, minutes, raw):
			e = schema.normalize_event({"type": "security", "severity": "warning", "bench": "seqb", **raw}, tz,
			                           at + timedelta(minutes=minutes))  # fmt: skip
			names[key] = events.insert_event(e)

		web = {"host": "seq-web", "site": "seq.localhost"}
		# ip: a probe, then a privileged login from the same address 28 min later
		ev("probe", -30, {**web, "category": "web_attack_probe", "source": "nginx", "title": "seq probe",
		                  "payload": {"ip": "45.33.32.210"}})  # fmt: skip
		ev("login", -2, {**web, "category": "new_admin_ip", "source": "frappe", "title": "seq login",
		                 "payload": {"ip": "45.33.32.210", "user": "Boss@Seq.example"}})  # fmt: skip
		for m in range(31, 60):  # a burst of older probes from the same address: the newest first event is linked
			ev(f"burst {m}", -m, {**web, "category": "web_attack_probe", "title": "seq burst", "payload": {"ip": "45.33.32.210"}})
		ev("alone", -2, {**web, "category": "new_admin_ip", "title": "seq no probe", "payload": {"ip": "45.33.32.211"}})
		ev("old probe", -90, {**web, "category": "web_attack_probe", "title": "seq old", "payload": {"ip": "45.33.32.212"}})
		ev("late login", -1, {**web, "category": "new_admin_ip", "title": "seq late", "payload": {"ip": "45.33.32.212"}})
		ev("login first", -5, {**web, "category": "new_admin_ip", "title": "seq before", "payload": {"ip": "45.33.32.213"}})
		ev("probe after", -1, {**web, "category": "web_attack_probe", "title": "seq after", "payload": {"ip": "45.33.32.213"}})
		# user: that login, then an export by the same user on the same site (not on another site)
		ev("export", -1, {**web, "category": "data_exfiltration", "title": "seq export", "payload": {"user": "boss@seq.example"}})
		ev("key", -1, {**web, "category": "api_key_generated", "title": "seq key",
		               "payload": {"user": "someone@seq.example", "by": "boss@seq.example"}})  # fmt: skip
		ev("other site", -1, {"host": "seq-web", "site": "seq2.localhost", "category": "data_exfiltration",
		                      "title": "seq export elsewhere", "payload": {"user": "boss@seq.example"}})  # fmt: skip
		# host: a Suricata alert on the host, then a Server Script change on a site of that host
		ev("ids", -20, {"host": "seq-web", "bench": None, "severity": "critical", "category": "network_ids_alert", "source": "suricata", "title": "seq ids",
		                "payload": {"ip": "45.33.32.220"}})  # fmt: skip
		ev("script", -2, {**web, "category": "server_script_change", "title": "seq script", "payload": {"user": "boss@seq.example"}})
		ev("quiet ids", -20, {"host": "seq-quiet", "severity": "warning", "category": "network_ids_alert", "title": "seq info ids"})
		ev("quiet script", -2, {"host": "seq-quiet", "site": "seq3.localhost", "category": "server_script_change",
		                        "title": "seq script after info"})  # fmt: skip

		expected = {
			"Scan then login from the same IP": ("ip=45.33.32.210", {"probe", "login"}),
			# the login stays in the IP sequence's incident: an event has one incident (timeline below)
			"New-IP login then export or new key": ("user=boss@seq.example", {"export", "key"}),
			"IDS alert then risky change on the host": ("host=seq-web", {"ids", "script"}),
		}
		out = []
		for preset in (p for p in PRESETS if p["rule_name"] in expected):
			key, linked = expected[preset["rule_name"]]
			name = f"smoke seq {preset['sequence_entity']}"
			doc = frappe.get_doc("Wolf Alert Rule", name) if frappe.db.exists("Wolf Alert Rule", name) else frappe.new_doc("Wolf Alert Rule")
			doc.update({**preset, "rule_name": name, "enabled": 1, "is_preset": 0, "channels": [], "filter_bench": "seqb"})
			doc.save()
			res = rules.evaluate(doc)
			fired = frappe.get_all("Wolf Incident", filters={"alert_rule": name, "status": "Open"}, fields=["name", "group_key", "title", "site"])
			assert [i.group_key for i in fired] == [key], (name, res, fired)
			got = set(frappe.get_all("Wolf Event", filters={"incident": fired[0].name}, pluck="name"))
			evidence = {names[k] for k in linked}
			assert evidence <= got, (name, evidence - got)
			# beyond its evidence, the incident takes the earlier events of the same IP or e-mail user
			# (incidents.adopt_related): the burst of older probes, the login user's other events
			keys = {(k, v) for e in evidence for k, v in incidents.correlation_keys(e, frappe.get_doc("Wolf Event", e).as_dict())}
			for extra in got - evidence:
				theirs = set(frappe.db.sql("select kind, value from `tabWolf Event Entity` where event = %s", extra))
				assert theirs & keys, (name, "took an unrelated event", extra, theirs)
			# the incident starts at the first event: its timeline shows both, linked or not
			first, then = {"ip": ("probe", "login"), "user": ("login", "export"), "host": ("ids", "script")}[preset["sequence_entity"]]
			shown = {r.name for r in incidents.get_timeline(fired[0].name)}
			assert {names[first], names[then]} <= shown, (name, first, then, shown)
			assert fired[0].title == f"{name}: {key.replace('=', ' ')}", fired[0].title
			assert not rules.evaluate(doc)["fired"], "fired twice"
			# the host-level Suricata alert is another scope than the site's incident: not named
			named = {"ip": "web_attack_probe then", "user": "new_admin_ip then", "host": "an earlier event then"}
			summary = frappe.db.get_value("Wolf Incident", fired[0].name, "summary")
			assert summary.startswith(named[preset["sequence_entity"]]), summary
			assert [g["group"] for g in doc.preview()["groups"]] == [key.replace("=", " ")]
			incidents.resolve(fired[0].name, "smoke")
			out.append(f"{preset['sequence_entity']}: {fired[0].name}")
		try:
			bad = frappe.get_doc({**next(p for p in PRESETS if p["rule_name"] in expected), "doctype": "Wolf Alert Rule",
			                      "rule_name": "smoke seq bad", "then_categories": " "})  # fmt: skip
			bad.insert()
			raise AssertionError("a sequence without then categories was saved")
		except frappe.ValidationError:
			frappe.clear_messages()
		frappe.db.set_value("Wolf Alert Rule", {"rule_name": ("like", "smoke seq %")}, "enabled", 0)  # incidents link them
		return ", ".join(out) + "; probe burst, key by the user; no probe, 88 min apart, wrong order, other site, warning IDS kept out"

	def file_integrity():
		"""The agent's file integrity events and their presets (#72 step 7)."""
		from dodock_wolf.wolf.presets import PRESETS

		tz, at = events.system_tz(), now_datetime()

		def ev(category, severity, title, **payload):
			e = schema.normalize_event({"type": "security", "category": category, "severity": severity, "host": "fim-host",
			                            "bench": "fim-bench", "source": "integrity", "title": title,
			                            "payload": {"kind": "code", **payload}}, tz, at)  # fmt: skip
			return events.insert_event(e)

		def rule(name, preset_name):
			preset = next(p for p in PRESETS if p["rule_name"] == preset_name)
			doc = frappe.get_doc("Wolf Alert Rule", name) if frappe.db.exists("Wolf Alert Rule", name) else frappe.new_doc("Wolf Alert Rule")
			doc.update({**preset, "rule_name": name, "enabled": 1, "is_preset": 0, "channels": [], "filter_host": "fim-host"})
			doc.save()
			return doc

		deploy = ev("bench_code_changed", "info", "fim erpnext updated", deploy=True, attack_techniques=[])
		code_rule = rule("smoke fim code", "Bench code changed outside a deployment")
		assert not rules.evaluate(code_rule)["fired"], "a deployment fired the tamper rule"
		tamper = ev("bench_code_changed", "critical", "fim erpnext: 2 files changed outside a deployment", deploy=False,
		            attack_techniques=["T1505.003", "T1565.001"], added=["erpnext/www/shell.py"])  # fmt: skip
		(fired,) = rules.evaluate(code_rule)["fired"]
		linked = set(frappe.get_all("Wolf Event", filters={"incident": fired}, pluck="name"))
		assert tamper in linked and deploy not in linked, linked
		techniques = [t["id"] for t in json.loads(frappe.db.get_value("Wolf Event", tamper, "payload"))["mitre_attack"]]
		assert techniques == ["T1505.003", "T1565.001"], techniques
		config_rule = rule("smoke fim config", "Bench or server config changed")
		ev("bench_config_changed", "warning", "fim site_config.json changed: developer_mode", kind="site_config",
		   keys_added=["developer_mode"])  # fmt: skip
		assert rules.evaluate(config_rule)["fired"], "the config rule did not fire"
		for doc in (code_rule, config_rule):
			for name in frappe.get_all("Wolf Incident", filters={"alert_rule": doc.name, "status": "Open"}, pluck="name"):
				incidents.resolve(name, "smoke")
			frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
		return f"{fired}: code changed outside a deployment fires, a deployment does not; a config change fires its rule"

	def outbound_connections():
		"""The agent's new outbound destinations and their preset (#72 step 7)."""
		from dodock_wolf.wolf.presets import PRESETS

		tz, at = events.system_tz(), now_datetime()

		def ev(severity, ip, port):
			e = schema.normalize_event({"type": "security", "category": "bench_new_outbound", "severity": severity, "host": "ob-host",
			                            "bench": "ob-bench", "source": "outbound", "title": f"ob new outbound {ip}:{port}",
			                            "payload": {"remote_ip": ip, "remote_port": port, "attack_techniques": ["T1071", "T1041"]}},
			                           tz, at)  # fmt: skip
			return events.insert_event(e)

		preset = next(p for p in PRESETS if p["rule_name"] == "Bench connects somewhere new")
		name = "smoke outbound"
		doc = frappe.get_doc("Wolf Alert Rule", name) if frappe.db.exists("Wolf Alert Rule", name) else frappe.new_doc("Wolf Alert Rule")
		doc.update({**preset, "rule_name": name, "enabled": 1, "is_preset": 0, "channels": [], "filter_host": "ob-host"})
		doc.save()
		usual = ev("info", "185.199.111.5", 443)
		assert not rules.evaluate(doc)["fired"], "a usual port fired"
		odd = ev("warning", "185.199.110.66", 4444)
		(fired,) = rules.evaluate(doc)["fired"]
		linked = set(frappe.get_all("Wolf Event", filters={"incident": fired}, pluck="name"))
		assert odd in linked and usual not in linked, linked
		row = frappe.db.get_value("Wolf Event", odd, ["event_type", "category", "severity", "payload"], as_dict=True)
		payload = json.loads(row.payload)
		assert [t["id"] for t in payload["mitre_attack"]] == ["T1071", "T1041"] and payload["entities"]["ip"] == ["185.199.110.66"], payload
		# the destination is searchable, but it is not the remote party of an attack: no CrowdSec alert, no block
		from dodock_wolf.wolf import crowdsec, response

		assert not crowdsec.wanted({**row, "payload": payload}), "a partner sent to CrowdSec as an attacker"
		assert not response.suggest([{**row, "payload": payload, "agent": "x", "block_host": "ob-host", "block_agent": "x"}])
		incidents.resolve(fired, "smoke")
		frappe.db.set_value("Wolf Alert Rule", doc.name, "enabled", 0)
		return f"{fired}: an unusual port fires, a usual one does not; the destination is searchable, not blocked nor sent to CrowdSec"

	def wazuh_blocking():
		"""Approved blocks for the attacked host, by its Wolf Agent and/or Wazuh active response (#72 step 6)."""
		import base64
		from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
		from urllib.parse import parse_qs, urlparse

		from dodock_wolf.api import response as response_api

		seen = []
		agents = [{"id": "000", "name": "wazuh-manager", "ip": "127.0.0.1"}, {"id": "001", "name": "web-02", "ip": "10.8.0.2"},
		          {"id": "002", "name": "bench-blk", "ip": "10.8.0.3"}]  # fmt: skip

		class API(BaseHTTPRequestHandler):  # the answers a Wazuh 4.9.2 manager gave
			def log_message(self, *args):
				pass

			def reply(self, code, body):
				data = json.dumps(body).encode()
				self.send_response(code)
				self.send_header("Content-Type", "application/json")
				self.send_header("Content-Length", str(len(data)))
				self.end_headers()
				self.wfile.write(data)

			def authed(self):
				return self.headers.get("Authorization") == "Bearer smoke-jwt"

			def do_POST(self):
				ok = self.headers.get("Authorization") == "Basic " + base64.b64encode(b"wolf:smoke-pw").decode()
				return self.reply(200, {"data": {"token": "smoke-jwt"}, "error": 0}) if ok else self.reply(401, {"detail": "bad"})

			def do_GET(self):
				if not self.authed():
					return self.reply(401, {})
				return self.reply(200, {"data": {"affected_items": agents, "total_affected_items": 3}, "error": 0})

			def do_PUT(self):
				if not self.authed():
					return self.reply(401, {})
				body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
				agent = parse_qs(urlparse(self.path).query)["agents_list"][0]
				seen.append((agent, body))
				return self.reply(200, {"data": {"affected_items": [agent], "total_affected_items": 1, "failed_items": []},
				                        "message": "AR command was sent to all agents", "error": 0})  # fmt: skip

		server = ThreadingHTTPServer(("127.0.0.1", 0), API)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		settings = frappe.get_single("Wolf Settings")
		saved = {f: settings.get(f) for f in ("block_with", "wazuh_api_url", "wazuh_api_user", "wazuh_ar_command", "wazuh_verify_tls")}
		tz, at = events.system_tz(), now_datetime()
		blk = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "bench-blk", "kind": "agent"}).insert(ignore_permissions=True)
		integ = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "wazuh-mgr", "kind": "integration"}).insert(ignore_permissions=True)
		two = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "bench-two", "kind": "agent"}).insert(ignore_permissions=True)
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "blk incident", "severity": "critical", "status": "Open",
		                      "started_at": at}).insert(ignore_permissions=True)  # fmt: skip

		def ev(category, host, ip, agent):
			e = schema.normalize_event({"type": "security", "severity": "critical", "category": category, "host": host,
			                            "title": f"blk {category} {ip}", "payload": {"ip": ip}}, tz, at)  # fmt: skip
			name = events.insert_event(e, agent=agent)
			frappe.db.set_value("Wolf Event", name, "incident", inc.name)

		def proposals():
			return {(p["target"], p["host"]): p for p in response_api.get_response(inc.name)["proposals"] if p["action"] == "block_ip"}

		try:
			# a Wazuh alert about web-02 (sent by the integration), an SSH brute force seen by bench-blk's own agent
			ev("hids_alert", "web-02", "45.33.32.250", integ.name)
			ev("ssh_failed_login", "bench-blk", "45.33.32.251", blk.name)
			ev("hids_alert", "nowhere-host", "45.33.32.252", integ.name)
			ev("web_attack_probe", "web-02", "45.33.32.253", blk.name)  # an ordinary agent naming another host
			ev("ssh_failed_login", "bench-two", "45.33.32.254", two.name)  # a Wolf Agent, no Wazuh agent yet
			got = proposals()
			assert set(got) == {("45.33.32.251", "bench-blk"), ("45.33.32.253", "bench-blk"), ("45.33.32.254", "bench-two")}, \
				f"wolf_agent: only where a Wolf Agent runs, and an agent's own events on its own host: {got}"
			assert got[("45.33.32.251", "bench-blk")]["agent"] == blk.name

			settings.update({"block_with": "both", "wazuh_api_url": f"http://127.0.0.1:{server.server_address[1]}",
			                 "wazuh_api_user": "wolf", "wazuh_api_password": "smoke-pw", "wazuh_ar_command": "firewall-drop7200",
			                 "wazuh_verify_tls": 0})  # fmt: skip
			settings.save(ignore_permissions=True)
			got = proposals()
			assert {k: p["executors"] for k, p in got.items()} == {
				("45.33.32.250", "web-02"): ["wazuh"], ("45.33.32.251", "bench-blk"): ["wolf_agent", "wazuh"],
				("45.33.32.252", "nowhere-host"): ["wazuh"], ("45.33.32.253", "bench-blk"): ["wolf_agent", "wazuh"],
				("45.33.32.254", "bench-two"): ["wolf_agent", "wazuh"]}, got  # fmt: skip
			assert got[("45.33.32.250", "web-02")]["label"] == "Block 45.33.32.250 for 2 h on web-02 with Wazuh"
			assert got[("45.33.32.251", "bench-blk")]["label"] == \
				"Block 45.33.32.251 for 24 h on bench-blk with the Wolf Agent, and for 2 h with Wazuh"

			only = response_api.approve(inc.name, "block_ip", "45.33.32.250", host="web-02", duration_hours=48)
			assert (only["executor"], only["status"], only["wazuh_agent_id"], only["duration_hours"]) == ("wazuh", "Applied", "001", 2), only
			assert seen[-1] == ("001", {"command": "firewall-drop7200", "alert": {"data": {"srcip": "45.33.32.250"}}}), seen
			# from an older link or page: the Wolf Agent named, no host
			both = response_api.approve(inc.name, "block_ip", "45.33.32.251", agent=blk.name, duration_hours=6)
			assert (both["executor"], both["status"], both["duration_hours"]) == ("wolf_agent", "Approved", 6), both
			assert [(a["executor"], a["status"], a["wazuh_agent_id"]) for a in both["also"]] == [("wazuh", "Applied", "002")]
			assert [a["ip"] for a in response_api.pending_for_agent(blk.name)] == ["45.33.32.251"], "the agent's half"
			failed = response_api.approve(inc.name, "block_ip", "45.33.32.252", host="nowhere-host")
			assert failed["status"] == "Failed" and "no Wazuh agent is nowhere-host" in failed["result"], failed
			# both, with Wazuh failing: the Wolf Agent's half waits, Wazuh's alone is proposed again, then applied
			half = response_api.approve(inc.name, "block_ip", "45.33.32.254", host="bench-two", duration_hours=6)
			assert (half["status"], half["also"][0]["status"]) == ("Approved", "Failed"), half
			retry = proposals()[("45.33.32.254", "bench-two")]
			assert (retry["executors"], retry["agent"]) == (["wazuh"], None), retry
			agents.append({"id": "003", "name": "bench-two", "ip": "10.8.0.4"})
			again = response_api.approve(inc.name, "block_ip", "45.33.32.254", host="bench-two")
			assert (again["executor"], again["status"], again["wazuh_agent_id"], again["also"]) == ("wazuh", "Applied", "003", []), again
			# applied or waiting blocks are not proposed again; a failed one is, to retry once the alias is fixed
			assert set(proposals()) == {("45.33.32.252", "nowhere-host"), ("45.33.32.253", "bench-blk")}, proposals()
			# the stored password never follows the URL to another server; http:// only to this machine
			for url, why in ((f"https://wazuh.example.com:{server.server_address[1]}", "password again"),
			                 ("http://wazuh-manager:55000", "https://")):  # fmt: skip
				changed = frappe.get_single("Wolf Settings")
				changed.wazuh_api_url = url
				try:
					changed.save(ignore_permissions=True)
					raise AssertionError(f"{url} saved")
				except frappe.ValidationError as e:
					assert why in str(e), e
					frappe.clear_messages()
			journal = frappe.get_all("Wolf Journal Entry", filters={"ref_name": only["name"]}, pluck="content")
			assert any("wazuh" in (c or "") for c in journal), f"the Wazuh block is not journaled: {journal}"
		finally:
			server.shutdown()
			settings.update(saved)
			settings.save(ignore_permissions=True)
		frappe.db.delete("Wolf Response Action", {"incident": inc.name})
		frappe.db.delete("Wolf Event", {"incident": inc.name})
		frappe.delete_doc("Wolf Incident", inc.name, force=True, ignore_permissions=True)
		for name in (blk.name, integ.name, two.name):
			frappe.delete_doc("Wolf Agent", name, force=True, ignore_permissions=True)
		return ("Wazuh alert from the integration blocked on web-02 by Wazuh (2 h, its command's timeout); bench-blk by "
		        "its Wolf Agent and Wazuh; a failed Wazuh half retried; an agent cannot name another host; an unknown "
		        "host fails with why; journaled; the password does not follow a new URL; Wolf Agent only by default")

	def crowdsec_check():
		"""CrowdSec LAPI (a local stand-in): decisions tag events, detections and approved blocks go out."""
		from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
		from types import SimpleNamespace

		from dodock_wolf.api import crowdsec as cs_api

		seen = {"alerts": [], "streams": [], "agents": set()}

		class LAPI(BaseHTTPRequestHandler):
			def log_message(self, *args):
				pass

			def reply(self, code, body):
				data = json.dumps(body).encode()
				self.send_response(code)
				self.send_header("Content-Type", "application/json")
				self.send_header("Content-Length", str(len(data)))
				self.end_headers()
				self.wfile.write(data)

			def do_POST(self):
				body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
				seen["agents"].add(self.headers.get("User-Agent"))
				if self.path == "/v1/watchers/login":
					ok = body == {"machine_id": "wolf-smoke", "password": "smoke-pw"} and "/" in self.headers.get("User-Agent", "")
					return self.reply(200, {"code": 200, "token": "tok"}) if ok else self.reply(401, {"message": "bad login"})
				if self.path == "/v1/alerts" and self.headers.get("Authorization") == "Bearer tok":
					seen["alerts"] += body
					return self.reply(201, [str(len(seen["alerts"]))])
				return self.reply(403, {})

			def do_GET(self):
				if self.headers.get("X-Api-Key") != "smoke-key":
					return self.reply(403, {"message": "access forbidden"})
				seen["streams"].append(self.path)
				first = self.path.endswith("startup=true")
				return self.reply(200, {"new": [{"scope": "Ip", "value": "45.33.32.156", "type": "ban", "origin": "CAPI",
				                                 "scenario": "crowdsecurity/http-probing", "duration": "3h59m58s"}] if first else [],
				                        "deleted": None})  # fmt: skip

		server = ThreadingHTTPServer(("127.0.0.1", 0), LAPI)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		settings = frappe.get_single("Wolf Settings")
		settings.update({"crowdsec_enabled": 1, "crowdsec_url": f"http://127.0.0.1:{server.server_address[1]}",
		                 "crowdsec_bouncer_key": "smoke-key", "crowdsec_machine_id": "wolf-smoke", "crowdsec_password": "smoke-pw",
		                 "crowdsec_send_detections": 1, "crowdsec_min_severity": "warning", "crowdsec_apply_blocks": 1})  # fmt: skip
		settings.save(ignore_permissions=True)
		frappe.db.set_global(cs_api.CURSOR_KEY, None)
		if os.path.exists(cs_api.store_path()):
			os.remove(cs_api.store_path())
		lag = cs_api.LAG_SECONDS
		try:
			first = cs_api.sync_crowdsec()
			assert first["error"] is None and first["decisions"] == 1 and first["alerts_sent"] == 0, first  # the past is not replayed
			assert seen["streams"] == ["/v1/decisions/stream?startup=true"], seen["streams"]

			def insert(ip, severity, title):
				name = events.insert_event(schema.normalize_event({"type": "security", "category": "web_attack_probe", "severity": severity,
				                                                   "host": HOST, "title": title, "payload": {"ip": ip}}, tz, now_datetime()))  # fmt: skip
				return frappe.db.get_value("Wolf Event", name, ["severity", "payload"], as_dict=True)

			banned = insert("45.33.32.156", "warning", "crowdsec smoke: banned")
			assert banned.severity == "critical" and json.loads(banned.payload)["crowdsec"]["origin"] == "CAPI", banned
			clean = insert("203.0.113.70", "warning", "crowdsec smoke: clean")
			assert clean.severity == "warning" and "crowdsec" not in json.loads(clean.payload), clean
			insert("203.0.113.71", "info", "crowdsec smoke: below the minimum")
			cs_api.LAG_SECONDS = 0
			second = cs_api.sync_crowdsec()
			assert second["error"] is None and second["alerts_sent"] == 2, second
			assert seen["streams"][-1] == "/v1/decisions/stream", "changes only, after the first full read"
			sent = {a["source"]["ip"]: a for a in seen["alerts"]}
			assert set(sent) == {"45.33.32.156", "203.0.113.70"} and not any(a["remediation"] for a in sent.values()), sent
			assert sent["203.0.113.70"]["scenario"] == "dodock-wolf/web_attack_probe" and "decisions" not in sent["203.0.113.70"]
			assert cs_api.sync_crowdsec()["alerts_sent"] == 0, "the cursor moved"

			note = cs_api.apply_block(SimpleNamespace(name="WRA-SMOKE", target="198.51.100.77", duration_hours=6,
			                                          approved_by="Administrator", incident="WINC-SMOKE", approved_at=now_datetime()))  # fmt: skip
			assert note and "6 h ban" in note, note
			block = seen["alerts"][-1]
			assert block["decisions"] == [{"type": "ban", "duration": "6h", "scope": "Ip", "value": "198.51.100.77",
			                               "origin": "dodock-wolf", "scenario": "dodock-wolf/approved_block"}], block  # fmt: skip
			assert all("/" in a for a in seen["agents"]), seen["agents"]  # the LAPI refuses other User-Agents

			settings.reload()
			settings.crowdsec_password = "wrong"
			settings.save(ignore_permissions=True)
			cs_api.LAG_SECONDS = 0
			insert("203.0.113.72", "critical", "crowdsec smoke: while refused")
			failed = cs_api.sync_crowdsec()
			assert failed["error"] and "401" in failed["error"], failed
			assert cs_api.get_status()["error"] == failed["error"]
		finally:
			cs_api.LAG_SECONDS = lag
			server.shutdown()
			server.server_close()
			frappe.db.set_single_value("Wolf Settings", "crowdsec_enabled", 0)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			if os.path.exists(cs_api.store_path()):
				os.remove(cs_api.store_path())
		return f"{len(seen['alerts'])} alerts sent, banned IP tagged and raised, approved block sent as a 6 h ban"

	def posture_score():
		from dodock_wolf.api import security

		host = events.local_scope()["host"]
		now = now_datetime()
		samples = [
			schema.normalize_metric({"metric_name": "exposed_services", "value": 1, "host": host}, tz, now),
			schema.normalize_metric({"metric_name": "site_config_risks", "value": 0, "host": host, "site": SITE,
			                         "bench": "smoke-bench"}, tz, now),  # fmt: skip
			# the agent's versions for that bench: 16.20.0 is before the fixture advisory's fix
			schema.normalize_metric({"metric_name": "app_version", "value": 16020000, "host": host, "bench": "smoke-bench",
			                         "labels": {"app": "frappe"}}, tz, now),  # fmt: skip
			schema.normalize_metric({"metric_name": "backup_age_hours", "value": 2, "host": host, "site": SITE}, tz, now),
		]
		events.insert_metrics(samples)
		# GitHub Security Advisories, from a fake source: CI must not depend on api.github.com
		from dodock_wolf.api import advisories as advisory_store
		from dodock_wolf.wolf import advisories

		fixture = [{"ghsa_id": "GHSA-smok-e000-0001", "severity": "critical", "summary": "smoke SSTI", "state": "published",
		            "published_at": "2026-10-15T00:00:00Z", "html_url": "https://github.com/advisories/x",
		            "vulnerabilities": [{"vulnerable_version_range": "<16.21.0", "patched_versions": "16.21.0"},
		                                {"vulnerable_version_range": "<15.111.0", "patched_versions": "15.111.0"}]}]  # fmt: skip
		fetched, original_fetch = [], advisories.fetch

		def fake_fetch(repo):
			fetched.append(repo)
			if repo == "frappe/erpnext" and len(fetched) > 2:
				raise OSError("GitHub unreachable")
			return advisories.compact(fixture if repo == "frappe/frappe" else [])

		advisories.fetch = fake_fetch
		if os.path.exists(advisory_store.store_path()):
			os.remove(advisory_store.store_path())
		assert advisory_store.enabled(), "on by default"
		result = security.get_posture(SITE)
		status = {c["id"]: c["status"] for c in result["checks"]}
		assert result["local"] and status["two_factor"] in ("pass", "fail"), status  # read on the site itself
		assert status["exposure"] == "fail" and status["backup"] == "pass", status
		assert status["tls"] == "unknown", status  # no sample: never counted as passed
		assert status["advisories"] == "unknown", result["checks"]  # not fetched yet
		assert 0 <= result["score"] < 100 and result["coverage"] < 100, result
		before = frappe.db.count("Wolf Metric Sample", {"metric_name": "security_score", "site": SITE})
		try:
			security.record_security_scores()  # fetches the advisories first: there is no copy
			assert fetched == ["frappe/frappe", "frappe/erpnext"], fetched
			security.record_security_scores()
			assert len(fetched) == 2, "fetched once a day"
			check = next(c for c in security.get_posture(SITE)["checks"] if c["id"] == "advisories")
			assert check["status"] == "fail", check
			assert "frappe 16.20.0: 1 advisory (1 critical), fixed in 16.21.0 (GHSA-smok-e000-0001)" in check["evidence"], check
			# a failing repository keeps its last copy
			status_after = advisory_store.refresh_advisories()
			assert status_after["erpnext"]["ok"] is False and status_after["frappe"]["ok"], status_after
			assert advisory_store.sources()["erpnext"]["advisories"] == [], advisory_store.sources()
			advisory_store.get_status()
			frappe.db.set_single_value("Wolf Settings", "check_security_advisories", 0)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			check = next(c for c in security.get_posture(SITE)["checks"] if c["id"] == "advisories")
			assert check["evidence"] == "the advisory check is off in Wolf Settings", check
		finally:
			advisories.fetch = original_fetch
			frappe.db.set_single_value("Wolf Settings", "check_security_advisories", 1)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			if os.path.exists(advisory_store.store_path()):
				os.remove(advisory_store.store_path())
		assert frappe.db.count("Wolf Metric Sample", {"metric_name": "security_score", "site": SITE}) == before + 2
		assert SITE in security.list_sites()

		# another site: its System Settings come from the agent, read from that site's database
		remote = "remote.smoke.localhost"
		settings = {"enable_two_factor_auth": 1, "enable_password_policy": 1, "minimum_password_score": 2,
		            "allow_consecutive_login_attempts": 0, "allow_guests_to_upload_files": 0, "system_manager_2fa": 1}  # fmt: skip
		events.insert_metrics([schema.normalize_metric({"metric_name": "site_setting", "value": v, "host": host, "bench": "smoke-bench",
		                                                "site": remote, "labels": {"setting": k}}, tz, now)
		                       for k, v in settings.items()])  # fmt: skip
		assert remote in security.list_sites()
		remote_posture = security.get_posture(remote)
		checks = {c["id"]: c for c in remote_posture["checks"]}
		assert not remote_posture["local"]
		assert checks["two_factor"]["status"] == "pass", checks["two_factor"]
		assert checks["password_policy"]["status"] == "fail" and checks["password_policy"]["evidence"] == "minimum score 2", checks["password_policy"]
		assert checks["login_lockout"]["status"] == "fail" and checks["guest_uploads"]["status"] == "pass", checks
		# the Wolf site reads its own settings, never the agent's copy
		events.insert_metrics([schema.normalize_metric({"metric_name": "site_setting", "value": 1, "host": host, "site": SITE,
		                                                "labels": {"setting": "allow_guests_to_upload_files"}}, tz, now)])  # fmt: skip
		local_uploads = next(c for c in security.get_posture(SITE)["checks"] if c["id"] == "guest_uploads")
		assert local_uploads["evidence"] == "guests may not upload", local_uploads
		frappe.db.delete("Wolf Metric Sample", {"metric_name": "site_setting"})
		assert next(c for c in security.get_posture(remote)["checks"] if c["id"] == "two_factor")["status"] == "unknown"

		# HSTS from the agent's samples, per domain; SPF / DMARC from DNS for the outgoing mail domains
		from dodock_wolf.wolf import dns_txt

		for domain, days in (("erp.smoke.example.org", 365), ("shop.smoke.example.org", 0)):
			events.insert_metrics([schema.normalize_metric({"metric_name": "hsts_max_age_days", "value": days, "host": host,
			                                                "site": SITE, "labels": {"domain": domain}}, tz, now)])  # fmt: skip
		account = frappe.get_doc({"doctype": "Email Account", "email_account_name": "Wolf smoke outgoing",
		                          "email_id": "alerts@mail.smoke-wolf.dev", "enable_outgoing": 1, "service": ""})  # fmt: skip
		account.db_insert()  # no SMTP check: only its address matters here
		zone = {"mail.smoke-wolf.dev": ["v=spf1 include:_spf.smoke-wolf.dev -all"],
		        "_dmarc.smoke-wolf.dev": ["v=DMARC1; p=reject; sp=none"]}  # fmt: skip
		asked = []
		original = dns_txt.lookup

		def fake_lookup(name, **kw):
			asked.append(name)
			return zone.get(name, [])

		dns_txt.lookup = fake_lookup
		frappe.cache.delete_keys("wolf_mail_auth|")
		try:
			assert security.mail_domains() == ["mail.smoke-wolf.dev"], security.mail_domains()
			checks = {c["id"]: c for c in security.get_posture(SITE)["checks"]}
			assert checks["hsts"]["status"] == "fail" and checks["hsts"]["evidence"] == "shop.smoke.example.org: no header", checks["hsts"]
			assert checks["spf"]["status"] == "pass", checks["spf"]
			# no record on the subdomain: the organisational domain's sp=none applies, as receivers do
			assert checks["dmarc"]["status"] == "fail" and "p=none" in checks["dmarc"]["evidence"], checks["dmarc"]
			assert asked == ["mail.smoke-wolf.dev", "_dmarc.mail.smoke-wolf.dev", "_dmarc.smoke-wolf.dev"], asked
			security.get_posture(SITE)
			assert len(asked) == 3, asked  # cached: DNS asked once per name and hour
		finally:
			dns_txt.lookup = original
			frappe.cache.delete_keys("wolf_mail_auth|")
			frappe.db.delete("Email Account", {"name": account.name})
		return f"score {result['score']} (coverage {result['coverage']}%), {status}; hsts, spf, dmarc, advisories, another site's settings read"

	def regulatory_deadlines():
		from dodock_wolf.api import compliance as compliance_api
		from dodock_wolf.api import incident_view

		aware = now_datetime() - timedelta(hours=70)
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke NIS2", "severity": "critical",
		                      "site": "nis2.localhost", "nis2_significant": 1, "nis2_aware_at": aware,
		                      "gdpr_breach": 1})  # fmt: skip
		inc.insert(ignore_permissions=True)
		assert inc.gdpr_aware_at, "ticking the GDPR flag starts its clock"
		first = compliance_api.check_deadlines()
		stages = sorted(json.loads(frappe.db.get_value("Wolf Event", n, "payload"))["obligation"] for n in first)
		assert stages == ["nis2_early_warning", "nis2_notification"], stages  # 24 h passed, 72 h within 6 h
		assert all(frappe.db.get_value("Wolf Event", n, "incident") == inc.name for n in first)
		assert compliance_api.check_deadlines() == [], "one reminder per obligation and stage"
		comments = frappe.db.count("Comment", {"reference_doctype": "Wolf Incident", "reference_name": inc.name,
		                                       "comment_type": "Comment", "creation": (">=", inc.creation)})  # fmt: skip
		assert comments == 2, comments
		view = incident_view.get_incident(inc.name)["regulatory"]
		assert view["nis2"] and view["gdpr"] and len(view["deadlines"]) == 4, view
		report = compliance_api.get_report(inc.name)["markdown"]
		assert "| Incident notification (72 h) |" in report and "OVERDUE" in report, report

		# DORA: aware 22 h ago, classified as major 3 h ago: the initial notification is due within the hour
		dora = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke DORA", "severity": "critical", "site": "dora.localhost",
		                       "dora_major": 1, "dora_aware_at": now_datetime() - timedelta(hours=22),
		                       "dora_classified_at": now_datetime() - timedelta(hours=3)})  # fmt: skip
		dora.insert(ignore_permissions=True)
		reminded = compliance_api.check_deadlines()
		stages = [json.loads(frappe.db.get_value("Wolf Event", n, "payload")) for n in reminded]
		assert [(p["obligation"], p["regime"], p["stage"]) for p in stages] == [("dora_initial", "DORA", "due")], stages
		view = incident_view.get_incident(dora.name)["regulatory"]
		assert view["dora"] and [d["id"] for d in view["deadlines"]] == ["dora_initial", "dora_intermediate", "dora_final"], view
		dora.reload()
		dora.dora_initial_at = now_datetime()
		dora.save(ignore_permissions=True)
		assert not compliance_api.check_deadlines(), "sent: no more reminders"
		assert "DORA major ICT-related incident" in compliance_api.get_report(dora.name)["markdown"]
		# NIS2 intermediate report on request, with the authority's deadline
		inc.reload()
		inc.nis2_intermediate_requested_at = now_datetime()
		inc.nis2_intermediate_due_at = now_datetime() + timedelta(hours=2)
		inc.save(ignore_permissions=True)
		reminded = compliance_api.check_deadlines()
		assert [json.loads(frappe.db.get_value("Wolf Event", n, "payload"))["obligation"] for n in reminded] == ["nis2_intermediate"], reminded
		return f"{len(first)} reminders on {inc.name}, report {len(report)} chars; DORA initial notification and NIS2 intermediate report reminded"

	def threat_intel():
		from types import SimpleNamespace

		from dodock_wolf.api import threat

		path = frappe.get_site_path("private", "files", "wolf_smoke_list.txt")
		with open(path, "w") as f:
			f.write("# smoke\n203.0.113.0/24\n")
		values = {"ip_reputation_enabled": 1, "ip_reputation_sources": "smoke private/files/wolf_smoke_list.txt",
		          "honeytoken_users": "decoy@example.com", "honeytoken_api_keys": "decoykey123",
		          "honeytoken_paths": "/app/backup-admin"}  # fmt: skip
		for k, v in values.items():
			frappe.db.set_single_value("Wolf Settings", k, v)
		frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		saved_request = getattr(frappe.local, "request", None)
		try:
			status = threat.refresh_reputation()
			assert status["lists"]["smoke"] == {"entries": 1, "ok": True}, status
			name = events.insert_event(schema.normalize_event(
				{"type": "security", "category": "ssh_failed_login", "severity": "warning", "host": HOST,
				 "payload": {"ip": "203.0.113.9", "count": 3}}, tz, now_datetime()))  # fmt: skip
			ev = frappe.db.get_value("Wolf Event", name, ["severity", "payload"], as_dict=True)
			assert ev.severity == "critical", ev
			assert json.loads(ev.payload)["reputation"] == {"listed": True, "lists": ["smoke"]}, ev.payload

			log = frappe.get_doc({"doctype": "Activity Log", "operation": "Login", "status": "Failed",
			                      "user": "decoy@example.com", "ip_address": "198.51.100.20", "subject": "x"})  # fmt: skip
			log.flags.ignore_links = True
			log.insert(ignore_permissions=True)
			kinds = []
			for kind, request in (
				("api_key", SimpleNamespace(path="/api/method/frappe.auth.get_logged_user",
				                            headers={"Authorization": "token decoykey123:whatever"})),
				("path", SimpleNamespace(path="/app/backup-admin/", headers={})),
			):  # fmt: skip
				frappe.local.request = request
				threat.before_request()
				kinds.append(kind)
			rows = frappe.get_all("Wolf Event", filters={"category": "honeytoken_triggered"}, fields=["severity", "payload"])
			seen = sorted(json.loads(r.payload)["kind"] for r in rows)
			assert seen == ["api_key", "path", "user"], seen
			assert all(r.severity == "critical" for r in rows)
		finally:
			frappe.local.request = saved_request
			for k in values:
				frappe.db.set_single_value("Wolf Settings", k, 0 if k == "ip_reputation_enabled" else None)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			os.remove(path)
		return f"reputation tagged {name} critical; honeytokens {seen}"

	def response_actions():
		from dodock_wolf.api import ingest as ingest_api
		from dodock_wolf.api import response as response_api

		agent = frappe.get_doc({"doctype": "Wolf Agent", "hostname": "smoke-responder", "status": "Active",
		                        "kind": "agent"}).insert(ignore_permissions=True).name  # fmt: skip
		user = frappe.get_doc({"doctype": "User", "email": "wolf-intruder@example.com", "first_name": "Intruder",
		                       "send_welcome_email": 0}).insert(ignore_permissions=True).name  # fmt: skip
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke response", "severity": "critical",
		                      "host": "smoke-responder"}).insert(ignore_permissions=True)  # fmt: skip
		for data, by in (
			({"type": "security", "category": "ssh_failed_login", "severity": "critical", "host": "smoke-responder",
			  "payload": {"ip": "45.33.32.156", "count": 30}}, agent),
			({"type": "security", "category": "web_attack_probe", "host": "smoke-responder",
			  "payload": {"ip": "10.0.0.9"}}, agent),
			({"type": "security", "category": "api_key_generated", "site": SITE,
			  "payload": {"user": user}}, None),
		):  # fmt: skip
			name = events.insert_event(schema.normalize_event(data, tz, now_datetime()), agent=by)
			frappe.db.set_value("Wolf Event", name, "incident", inc.name)
		proposals = {(p["action"], p["target"]) for p in response_api.get_response(inc.name)["proposals"]}
		assert ("block_ip", "45.33.32.156") in proposals and ("block_ip", "10.0.0.9") not in proposals, proposals
		assert ("disable_user", user) in proposals, proposals

		block = response_api.approve(inc.name, "block_ip", "45.33.32.156", agent=agent, duration_hours=2)
		assert block["status"] == "Approved" and block["host"] == "smoke-responder", block
		res = ingest_api.accept(agent, {"hostname": "smoke-responder", "metrics": [], "events": []})
		assert [a["ip"] for a in res["actions"]] == ["45.33.32.156"] and res["actions"][0]["seconds"] > 7000, res
		res = ingest_api.accept(agent, {"hostname": "smoke-responder", "metrics": [], "events": [],
		                                "action_results": [{"id": block["name"], "ok": True, "detail": "blocked"}]})  # fmt: skip
		assert res["actions"] == [], res["actions"]  # applied: not handed out again
		assert frappe.db.get_value("Wolf Response Action", block["name"], "status") == "Applied"
		assert ("block_ip", "45.33.32.156") not in {(p["action"], p["target"]) for p in response_api.get_response(inc.name)["proposals"]}

		disabled = response_api.approve(inc.name, "disable_user", user)
		assert disabled["status"] == "Applied" and not frappe.db.get_value("User", user, "enabled"), disabled
		for action, target in (("disable_user", "Administrator"), ("block_ip", "10.0.0.9")):
			try:
				response_api.approve(inc.name, action, target, agent=agent)
				raise AssertionError(f"{action} {target} was accepted")
			except frappe.ValidationError:
				frappe.clear_messages()
		comments = frappe.db.count("Comment", {"reference_doctype": "Wolf Incident", "reference_name": inc.name,
		                                       "comment_type": "Comment"})  # fmt: skip
		assert comments >= 3, comments  # approved, applied on the host, user disabled
		expired = response_api.expire_actions(now_datetime() + timedelta(hours=3))
		assert block["name"] in expired, expired
		return f"{block['name']} blocked then expired, {disabled['name']} {disabled['result']}, refusals ok"

	def satellite_response():
		"""A user of a satellite: proposed and approved on the central site, applied by the satellite
		through its real push loop (satellite.flush), with requests routed to this site's ingest."""
		from unittest import mock

		from dodock_wolf import satellite
		from dodock_wolf.api import ingest as ingest_api
		from dodock_wolf.api import response as response_api
		from dodock_wolf.wolf import forwarding

		sat_site = "sat-response.localhost"
		sat = frappe.get_doc({"doctype": "Wolf Agent", "hostname": sat_site, "status": "Active", "kind": "satellite"}).insert(ignore_permissions=True).name
		user = frappe.get_doc({"doctype": "User", "email": "wolf-sat-intruder@example.com", "first_name": "Sat",
		                       "send_welcome_email": 0}).insert(ignore_permissions=True).name  # fmt: skip
		admin = frappe.get_doc({"doctype": "User", "email": "wolf-sat-admin@example.com", "first_name": "SatAdmin",
		                        "send_welcome_email": 0, "roles": [{"role": "System Manager"}]}).insert(ignore_permissions=True).name  # fmt: skip
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke satellite response", "severity": "critical",
		                      "site": sat_site}).insert(ignore_permissions=True)  # fmt: skip
		# what the satellite says of each user it forwards (here both sites are this one)
		for who, known, protected in ((user, True, False), (admin, True, True), ("nobody-here@example.com", False, False)):
			ev = satellite._with_user_hints({"type": "security", "payload": {"user": who}})
			assert (ev["payload"]["user_known"], ev["payload"]["user_protected"]) == (known, protected), (who, ev)
			data = {"type": "security", "category": "api_key_new_ip", "site": "claimed.example.com", "payload": ev["payload"]}
			name = events.insert_event(schema.normalize_event(data, tz, now_datetime()), agent=sat)
			frappe.db.set_value("Wolf Event", name, "incident", inc.name)
		proposals = {(p["action"], p["target"]): p for p in response_api.get_response(inc.name)["proposals"]}
		p = proposals.get(("disable_user", user))
		assert p and p["agent"] == sat and sat_site in p["label"], proposals  # named with its registration, not the event's claim
		assert not any(t in (admin, "nobody-here@example.com") for _a, t in proposals), proposals  # out of reach there

		approved = response_api.approve(inc.name, "disable_user", user, agent=sat)
		assert approved["status"] == "Approved" and approved["agent"] == sat, approved
		assert frappe.db.get_value("User", user, "enabled"), "applied on the central site"

		settings_before = frappe.db.get_value("Wolf Settings", None, ["mode", "central_url", "verify_tls", "satellite_id",
		                                                               "accept_response_actions"], as_dict=True)  # fmt: skip
		try:
			# crafted or refused: never acted on, each said once
			frappe.db.set_single_value("Wolf Settings", {"accept_response_actions": 1, "central_url": "http://central.example", "verify_tls": 1})
			crafted = ["x", {"id": 3}, {"id": "WRA-X1", "action": "block_ip", "ip": "1.2.3.4"},
			           {"id": "WRA-X2", "action": "disable_user", "user": " ADMINISTRATOR "},
			           {"id": "WRA-X3", "action": "disable_user", "user": admin}]  # fmt: skip
			assert [r["id"] for r in satellite.apply_actions(crafted)] == ["WRA-X2", "WRA-X3"]
			assert all(not r["ok"] and "HTTPS" in r["detail"] for r in satellite.apply_actions(
				[{"id": "WRA-X4", "action": "disable_user", "user": user}]))  # plain HTTP: no action on its word
			frappe.db.set_single_value("Wolf Settings", "central_url", "https://central.example")
			refused = satellite.apply_actions([{"id": "WRA-X5", "action": "disable_user", "user": admin}])
			assert not refused[0]["ok"] and "System Manager" in refused[0]["detail"] and frappe.db.get_value("User", admin, "enabled")

			# the real loop: this site as a satellite of itself, its pushes routed to the central ingest
			secret = frappe.generate_hash(length=32)
			frappe.db.set_single_value("Wolf Settings", {"mode": "satellite", "satellite_id": sat, "forward_retry_at": None})
			frappe.utils.password.set_encrypted_password("Wolf Settings", "Wolf Settings", secret, "satellite_secret")
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			bodies = []

			def central(url, json=None, **kwargs):  # noqa: A002 (requests' own keyword)
				assert url.endswith(forwarding.PUSH_METHOD) and kwargs["headers"]["X-Wolf-Agent-Id"] == sat
				bodies.append(json)
				return mock.Mock(status_code=200, json=lambda: {"message": ingest_api.accept(sat, json)}, text="")

			with mock.patch.object(satellite.requests, "post", side_effect=central):
				satellite.flush(force=True)
			assert not frappe.db.get_value("User", user, "enabled"), "not applied by the satellite"
			assert any(b.get("action_results") for b in bodies), bodies  # reported in a follow-up push
			assert frappe.db.get_value("Wolf Response Action", approved["name"], "status") == "Applied"
			# handed again (a lost report): answered from memory, never redone
			frappe.db.set_value("User", user, "enabled", 1)
			again = satellite.apply_actions([{"id": approved["name"], "action": "disable_user", "user": user}])
			assert again[0]["ok"] and frappe.db.get_value("User", user, "enabled"), again
		finally:
			frappe.db.set_single_value("Wolf Settings", {k: v for k, v in settings_before.items()})
			frappe.db.set_single_value("Wolf Settings", "forward_retry_at", None)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			frappe.db.set_value("User", admin, "enabled", 0)  # leave no spare System Manager behind
			frappe.db.set_value("Wolf Agent", sat, "status", "Disabled")

		# one the satellite never takes expires after a day
		left = response_api.approve(inc.name, "revoke_api_keys", user, agent=sat)
		assert left["name"] in response_api.expire_actions(now_datetime() + timedelta(hours=25))
		assert frappe.db.get_value("Wolf Response Action", left["name"], "status") == "Expired"
		return f"{approved['name']} applied through the satellite's push loop, refusals and repeats ok, {left['name']} expired untaken"

	def response_links():
		"""Signed links to proposed response actions: in the alert, confirmed only by a logged-in manager."""
		from types import SimpleNamespace
		from urllib.parse import parse_qs, urlsplit

		from dodock_wolf.api import actions as actions_api
		from dodock_wolf.wolf import notify

		user = frappe.get_doc({"doctype": "User", "email": "wolf-link-target@example.com", "first_name": "Target",
		                       "send_welcome_email": 0}).insert(ignore_permissions=True).name  # fmt: skip
		clerk = frappe.get_doc({"doctype": "User", "email": "wolf-link-clerk@example.com", "first_name": "Clerk",
		                        "send_welcome_email": 0, "roles": [{"role": "Wolf User"}]}).insert(ignore_permissions=True).name  # fmt: skip
		inc = frappe.get_doc({"doctype": "Wolf Incident", "title": "smoke response links", "severity": "critical",
		                      "status": "Open", "site": SITE}).insert(ignore_permissions=True)  # fmt: skip
		name = events.insert_event(schema.normalize_event(
			{"type": "security", "category": "api_key_generated", "site": SITE, "payload": {"user": user}}, tz, now_datetime()))  # fmt: skip
		frappe.db.set_value("Wolf Event", name, "incident", inc.name)
		frappe.local.wolf_response_proposals = None

		subject, text, html = notify.render(inc, "fired", actor="oncall@example.com")
		responses = notify.response_links(inc, "fired", actor="oncall@example.com")
		disable = next(r for r in responses if r["label"] == f"Disable user {user}")
		assert disable["url"] in text and "Wolf Manager" in html, text
		params = {k: v[0] for k, v in parse_qs(urlsplit(disable["url"]).query).items()}
		assert params["actor"] == "oncall@example.com" and "agent" not in params, params
		assert notify.message(inc, "resolved")["responses"] == [], "no links on a resolved alert"

		def open_link(as_user, method, **override):
			frappe.set_user(as_user)
			frappe.local.session.data.csrf_token = "smoke-csrf"  # a request has one; a script cannot make one
			frappe.local.response = frappe._dict()
			frappe.local.request = SimpleNamespace(method=method, full_path="/api/method/dodock_wolf.api.actions.response_action?x=1")
			try:
				actions_api.response_action(**{**params, **override})
			finally:
				frappe.set_user("Administrator")
				frappe.local.request = None
			return frappe.local.response.get("http_status_code") or 200, frappe.local.message_title, frappe.local.message

		seen = {}
		try:
			status, _, page = open_link("Administrator", "POST", target="other@example.com")
			assert status == 403 and "not valid" in page, page  # a signed field changed
			status, _, page = open_link("Guest", "POST")
			assert status == 200 and "Log in to confirm" in page and not frappe.db.exists("Wolf Response Action",
			       {"incident": inc.name}), page  # fmt: skip
			status, _, page = open_link(clerk, "POST")
			assert status == 403 and "Only a Wolf Manager" in page, page
			status, _, page = open_link("Administrator", "GET")
			assert "<form method=\"post\"" in page and frappe.db.get_value("User", user, "enabled"), page  # GET acts on nothing
			status, _, page = open_link("Administrator", "POST")
			row = frappe.get_all("Wolf Response Action", filters={"incident": inc.name}, fields=["name", "status", "approved_by", "reason"])
			assert status == 200 and len(row) == 1 and row[0].status == "Applied", (page, row)
			assert row[0].approved_by == "Administrator" and "oncall@example.com" in row[0].reason, row
			assert not frappe.db.get_value("User", user, "enabled")
			status, _, page = open_link("Administrator", "POST")
			assert "Nothing to do" in page and frappe.db.count("Wolf Response Action", {"incident": inc.name}) == 1, page
			seen["confirmed"] = f"{row[0].name} by Administrator from a link sent to oncall@example.com"
		finally:
			frappe.local.response = frappe._dict()
			frappe.db.set_value("User", user, "enabled", 1)
		return seen

	def journal_chain():
		from dodock_wolf.api import journal as journal_api

		ev = events.insert_event(schema.normalize_event(
			{"type": "security", "category": "ssh_failed_login", "host": HOST, "payload": {"ip": "45.33.32.1"}},
			tz, now_datetime()))  # fmt: skip
		assert frappe.db.exists("Wolf Journal Entry", {"ref_name": ev, "kind": "security_event", "seq": 0})
		settings = frappe.get_doc("Wolf Settings")
		settings.honeytoken_paths = "/app/secret-decoy"
		settings.save(ignore_permissions=True)
		pending = frappe.db.count("Wolf Journal Entry", {"seq": 0})
		while journal_api.chain_journal():
			pass
		result = journal_api.verify_journal()
		assert result["ok"] and result["pending"] == 0 and result["checked"] >= pending, result
		anchor = journal_api.get_status()["anchor"]
		assert journal_api.verify_journal(anchor)["ok"]

		entry = frappe.get_all("Wolf Journal Entry", filters={"kind": "settings"}, fields=["content"], order_by="seq desc", limit=1)[0]
		assert "honeytoken_paths" in entry.content and "secret-decoy" not in entry.content, entry.content  # names only

		row = frappe.db.sql("""select name, seq, content from `tabWolf Journal Entry` where seq > 0
			order by seq asc limit 1 offset 1""", as_dict=True)[0]  # fmt: skip
		frappe.db.sql("update `tabWolf Journal Entry` set content = %s where name = %s", ("{}", row.name))
		broken = journal_api.verify_journal()
		assert not broken["ok"] and broken["problem"]["seq"] == row.seq, broken
		frappe.db.sql("update `tabWolf Journal Entry` set content = %s where name = %s", (row.content, row.name))
		assert journal_api.verify_journal(anchor)["ok"]

		doc = frappe.get_doc("Wolf Journal Entry", row.name)
		doc.summary = "rewritten"
		try:
			doc.save(ignore_permissions=True)
			raise AssertionError("a journal entry was edited through the ORM")
		except frappe.PermissionError:
			frappe.clear_messages()
		settings.reload()
		settings.honeytoken_paths = None
		settings.save(ignore_permissions=True)
		return f"{result['checked']} entries chained and verified, edit detected at seq {row.seq}, anchor {anchor[:20]}…"

	def siem_export():
		import socketserver

		from dodock_wolf.api import journal as journal_api
		from dodock_wolf.api import siem as siem_api
		from dodock_wolf.wolf import siem as siem_fmt

		received = []

		class Collector(socketserver.BaseRequestHandler):
			def handle(self):
				data = b""
				while chunk := self.request.recv(65536):
					data += chunk
				received.extend(siem_fmt.unframe(data))

		server = socketserver.TCPServer(("127.0.0.1", 0), Collector)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		port = server.server_address[1]
		values = {"siem_enabled": 1, "siem_host": "127.0.0.1", "siem_port": port, "siem_transport": "tcp",
		          "siem_format": "ocsf", "siem_min_severity": "warning", "siem_event_types": "security", "siem_journal": 1}  # fmt: skip
		for k, v in values.items():
			frappe.db.set_single_value("Wolf Settings", k, v)
		frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		frappe.db.set_global(siem_api.CURSOR_KEY, None)
		try:
			ev = events.insert_event(schema.normalize_event(
				{"type": "security", "category": "web_attack_probe", "severity": "critical", "host": HOST,
				 "title": "SIEM smoke probe", "payload": {"ip": "45.33.32.156"}}, tz, now_datetime()))  # fmt: skip
			quiet = events.insert_event(schema.normalize_event(
				{"type": "security", "category": "web_attack_probe", "severity": "info", "host": HOST,
				 "title": "SIEM smoke below the minimum"}, tz, now_datetime()))  # fmt: skip
			while journal_api.chain_journal():
				pass
			import time

			def settle(count):
				deadline = time.monotonic() + 10
				while len(received) < count and time.monotonic() < deadline:  # the collector reads in its thread
					time.sleep(0.05)

			sent = siem_api.export_siem()  # default lag: events created just now wait for the next run
			settle(sent)
			# (the journal entries may name it: only a finding for it would be wrong)
			assert not any(f'"uid": "{ev}"' in m for m in received), "an event younger than the lag was exported"
			sent += siem_api.export_siem(lag_seconds=0)
			settle(sent)
			server.shutdown()
			bodies = [m.split(" - ", 2)[2] for m in received]
			findings = [json.loads(b) for b in bodies if b.startswith("{") and "class_uid" in b]
			mine = [f for f in findings if f["finding_info"]["uid"] == ev]
			assert mine and mine[0]["class_uid"] == 2004 and mine[0]["src_endpoint"]["ip"] == "45.33.32.156", findings[-1:]
			assert not [f for f in findings if f["finding_info"]["uid"] == quiet], "below the minimum severity"
			assert any('"wolf_journal"' in b for b in bodies), "journal entries are exported"
			assert sent == len(received), (sent, len(received))
			cursor = siem_api.get_status()
			assert cursor["last_error"] is None and cursor["journal_seq"], cursor

			frappe.db.set_single_value("Wolf Settings", "siem_port", 1)  # nothing listens there
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
			events.insert_event(schema.normalize_event(
				{"type": "security", "category": "ssh_failed_login", "severity": "warning", "host": HOST,
				 "title": "SIEM smoke while down"}, tz, now_datetime()))  # fmt: skip
			assert siem_api.export_siem(lag_seconds=0) == 0
			down = siem_api.get_status()
			# (intermittent before: say what the export read, to tell a stale settings cache from the rest)
			seen = {k: siem_api._settings().get(k) for k in ("siem_enabled", "siem_host", "siem_port")}
			stored = {k: frappe.db.get_single_value("Wolf Settings", k) for k in ("siem_enabled", "siem_port")}
			assert down["last_error"] and down["event_name"] == cursor["event_name"], (down, cursor, seen, stored)  # nothing skipped

			# Wazuh's recipe: bare OCSF JSON, one per line over TCP (the event kept while down goes now)
			lines = []

			class LineCollector(socketserver.BaseRequestHandler):
				def handle(self):
					data = b""
					while chunk := self.request.recv(65536):
						data += chunk
					lines.extend(data.decode("utf-8").splitlines())

			line_server = socketserver.TCPServer(("127.0.0.1", 0), LineCollector)
			threading.Thread(target=line_server.serve_forever, daemon=True).start()
			try:
				for k, v in {"siem_port": line_server.server_address[1], "siem_framing": "newline", "siem_header": "none",
				             "siem_journal": 0}.items():  # fmt: skip
					frappe.db.set_single_value("Wolf Settings", k, v)
				frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
				count = siem_api.export_siem(lag_seconds=0)
				deadline = time.monotonic() + 10
				while len(lines) < count and time.monotonic() < deadline:
					time.sleep(0.05)
				assert count >= 1 and len(lines) == count, (count, lines)
				titles = [json.loads(line)["finding_info"]["title"] for line in lines]  # each line is bare JSON
				assert "SIEM smoke while down" in titles, titles
				assert siem_api.get_status()["last_error"] is None
			finally:
				line_server.shutdown()
				line_server.server_close()
				for k, v in {"siem_framing": "octet-counting", "siem_header": "rfc5424"}.items():
					frappe.db.set_single_value("Wolf Settings", k, v)
		finally:
			server.server_close()
			frappe.db.set_single_value("Wolf Settings", "siem_enabled", 0)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		return f"{sent} messages (OCSF findings and journal entries); collector down: cursor kept, error recorded; bare JSON lines sent after"

	def journal_retention():
		"""Purge after a signed record; verification checks the journal starts where it stopped."""
		from frappe.utils import add_days

		from dodock_wolf.api import journal as journal_api
		from dodock_wolf.api import siem as siem_api

		DT = "Wolf Journal Entry"
		for i in range(4):  # a few more entries to purge
			events.insert_event(schema.normalize_event(
				{"type": "security", "category": "ssh_failed_login", "host": HOST, "title": f"retention smoke {i}"},
				tz, now_datetime()))  # fmt: skip
		while journal_api.chain_journal():
			pass

		def set_days(days):
			frappe.db.set_single_value("Wolf Settings", "journal_retention_days", days)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")

		def seqs():
			return frappe.db.sql(f"select min(seq), max(seq) from `tab{DT}` where seq > 0")[0]

		far = add_days(now_datetime(), 400)
		set_days(0)
		assert journal_api.purge_journal(now=far) == 0  # 0 keeps everything
		try:
			# the SIEM export has sent up to oldest + 1: nothing after it goes
			oldest, newest = seqs()
			frappe.db.set_single_value("Wolf Settings", {"siem_enabled": 1, "siem_journal": 1})
			frappe.db.set_global(siem_api.CURSOR_KEY, json.dumps({"journal_seq": oldest + 1}))
			set_days(30)
			assert journal_api.purge_journal(now=far) == 2
			assert seqs()[0] == oldest + 2
			r = journal_api.verify_journal()
			assert r["ok"] and r["purged_through"] == oldest + 1, r
			frappe.db.set_single_value("Wolf Settings", {"siem_enabled": 0, "siem_journal": 0})
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")

			# a cut inside the journal: entries before the 3rd kept one are older than the retention
			kept = frappe.db.sql(f"select seq, `at` from `tab{DT}` where seq > 0 order by seq asc limit 3", as_dict=True)
			third = kept[2]
			removed = journal_api.purge_journal(now=add_days(third.at, 30))
			first, newest = seqs()
			assert removed >= 2 and first <= third.seq, (removed, first, third.seq)
			r = journal_api.verify_journal()
			assert r["ok"] and r["first_seq"] == first and r["purged_through"] == first - 1, r
			status = journal_api.get_status()
			assert status["purged_through"] == first - 1 and status["retention_days"] == 30, status
			anchor = status["anchor"]
			assert journal_api.verify_journal(anchor)["ok"]
			purge = frappe.get_all(DT, filters={"kind": "journal_purge"}, fields=["summary", "seq"], order_by="seq desc", limit=1)[0]
			assert purge.seq == newest, purge  # the record chained last, signed before the delete

			# everything old: the newest entry stays, the purge record chains after it
			journal_api.purge_journal(now=far)
			first, newest = seqs()
			assert first == newest - 1, (first, newest)
			assert journal_api.verify_journal()["ok"]

			# an attacker deleting the oldest kept entry: caught
			row = frappe.db.sql(f"select * from `tab{DT}` where seq = %s", (first,), as_dict=True)[0]
			frappe.db.delete(DT, {"name": row.name})
			broken = journal_api.verify_journal()
			assert not broken["ok"] and "where the last purge stopped" in broken["problem"]["why"], broken
			frappe.get_doc({"doctype": DT, **row}).db_insert()
			assert journal_api.verify_journal()["ok"]
		finally:
			set_days(0)
			frappe.db.set_single_value("Wolf Settings", {"siem_enabled": 0, "siem_journal": 0})
			frappe.db.set_global(siem_api.CURSOR_KEY, None)
			frappe.clear_document_cache("Wolf Settings", "Wolf Settings")
		return f"purged up to the SIEM cursor, then to the cut, then all but the newest; journal from {first}, deletion caught"

	def rules_yaml():
		# alert rules as YAML (api/rules_io.py): a round trip, an applied change, a typo applying nothing
		from dodock_wolf.api import rules_io as rules_yaml_api

		doc = rules_yaml_api.load(rules_yaml_api.dump(rules_yaml_api.export_document()))
		plan = rules_yaml_api.import_document(doc)
		assert plan["valid"] and plan["counts"]["unchanged"] == len(doc["rules"]), plan["counts"]
		original = frappe.db.get_value("Wolf Alert Rule", "smoke disk", "threshold")
		next(r for r in doc["rules"] if r["rule_name"] == "smoke disk")["threshold"] = 77
		doc["rules"].append({"rule_name": "smoke yaml", "enabled": 0, "metric_name": "cpu_usage", "threshold": 50,
		                     "channels": [{"channel_type": "ntfy", "ntfy_server": "https://ntfy.example.com", "ntfy_topic": "x"}]})  # fmt: skip
		try:
			result = rules_yaml_api.import_document(doc, apply=True)
			assert result["applied"] and (result["counts"]["create"], result["counts"]["update"]) == (1, 1), result["counts"]
			assert float(frappe.db.get_value("Wolf Alert Rule", "smoke disk", "threshold")) == 77
			assert frappe.get_doc("Wolf Alert Rule", "smoke yaml").channels[0].enabled == 0  # no ntfy_token in a file
			bad = {"version": 1, "rules": [{"rule_name": "smoke disk", "treshold": 1}]}
			assert not rules_yaml_api.import_document(bad, apply=True)["applied"]
			severity = {"version": 1, "rules": [{"rule_name": "smoke disk", "severity": "high"}]}  # not an option
			assert not rules_yaml_api.import_document(severity, apply=True)["applied"]
		finally:
			if frappe.db.exists("Wolf Alert Rule", "smoke yaml"):
				frappe.delete_doc("Wolf Alert Rule", "smoke yaml", force=True)
			frappe.db.set_value("Wolf Alert Rule", "smoke disk", "threshold", original)
		return result["counts"]

	for name, fn in [("ingest", ingest), ("evaluate", evaluate), ("correlate", correlate), ("timeline", timeline),
	                 ("deployment link", deployment_link),
	                 ("reopen after resolve", reopen_after_resolve), ("skew", skew),
	                 ("overview+charts", overview), ("presets+signal rules", presets_and_signal_rules),
	                 ("email queue", email_queue_signals), ("backup failure+geoip", backup_failure_and_geoip),
	                 ("scoped user", scoped_user), ("agent secrets", agent_secrets),
	                 ("channels", channels), ("purge", purge), ("auto-resolve", resolve),
	                 ("assign+comment+activity", workflow), ("merge+split", merge_split), ("postmortem", postmortem),
	                 ("metrics report", metrics),
	                 ("rollup", rollup), ("legacy names", legacy_names), ("resolution", resolution), ("ingest modes", ingest_modes),
	                 ("purge metrics", purge_metrics), ("ui counts+inventory", ui_counts),
	                 ("incident view", incident_view), ("dashboards", dashboards), ("read cache", read_cache_check),
	                 ("explorers", explorers), ("metrics explorer", metrics_explorer),
	                 ("live updates", live_updates),
	                 ("app security", app_security), ("permission drift", permission_drift),
	                 ("exfiltration", exfiltration_check),
	                 ("api key addresses", api_key_ips),
	                 ("crowdsec", crowdsec_check),
	                 ("suricata events", suricata_events),
	                 ("wazuh events", wazuh_events),
	                 ("wazuh integration", wazuh_integration),
	                 ("entities", entities_check),
	                 ("entity correlation", entity_correlation),
	                 ("sequence rules", sequence_rules),
	                 ("timeline related scopes", timeline_related),
	                 ("detector modes", detector_modes),
	                 ("three sources, one incident", three_sources_one_incident),
	                 ("wazuh blocking", wazuh_blocking),
	                 ("file integrity", file_integrity),
	                 ("outbound connections", outbound_connections),
	                 ("posture score", posture_score),
	                 ("regulatory deadlines", regulatory_deadlines), ("threat intel", threat_intel),
	                 ("response actions", response_actions), ("satellite response", satellite_response), ("response links", response_links), ("journal", journal_chain),
	                 ("siem export", siem_export), ("journal retention", journal_retention), ("rules YAML", rules_yaml)]:
		check(name, fn)

	for name in ("smoke disk", "smoke 502", "smoke last", "smoke cron"):
		frappe.db.set_value("Wolf Alert Rule", name, "enabled", 0)
	frappe.db.commit()
	print("all checks passed")


if __name__ == "__main__":
	main()
