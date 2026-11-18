"""Press server support, against a fake Press layout built from frappe/agent's sources.

Layout and schema mirror frappe/agent (see docs/press.md): agent config.json from
`agent setup config` (agent/cli.py), bench dirs from Server.bench_init
(agent/server.py), bench config keys from press Bench.update_bench_config
(press/press/doctype/bench/bench.py), job tables from peewee JobModel/StepModel
(agent/job.py), nginx `main` log format from agent/templates/nginx/nginx.conf.jinja2.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wolf_agent import discovery, press  # noqa: E402
from wolf_agent.collector import Collector  # noqa: E402
from wolf_agent.parsers.nginx import NginxParser  # noqa: E402

NOW = datetime(2026, 10, 29, 2, 10, 0, tzinfo=timezone.utc)


def local(dt):
	"""What peewee stores: naive datetime.now() text in server local time."""
	return dt.astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")


def write_json(path, data):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as f:
		json.dump(data, f)


class FakePress:
	def __init__(self, root):
		self.root = root
		self.agent_dir = os.path.join(root, "home", "frappe", "agent")
		self.benches_dir = os.path.join(root, "home", "frappe", "benches")
		os.makedirs(self.benches_dir)
		write_json(
			os.path.join(self.agent_dir, "config.json"),
			{
				"benches_directory": self.benches_dir,
				"name": "f1-mumbai.frappe.cloud",
				"nginx_directory": os.path.join(self.agent_dir, "nginx"),
				"redis_port": 25025,
				"user": "frappe",
				"workers": 2,
				"web_port": 25052,
			},
		)
		self.access_log = os.path.join(root, "var", "log", "nginx", "access.log")
		os.makedirs(os.path.dirname(self.access_log))
		open(self.access_log, "w").close()
		self.db = os.path.join(self.agent_dir, "jobs.sqlite3")
		conn = sqlite3.connect(self.db)
		conn.execute("pragma journal_mode=wal")
		conn.executescript(
			"""
			create table jobmodel (id integer primary key autoincrement, name varchar(255) not null,
				status varchar(255) not null, agent_job_id varchar(255), data text, enqueue datetime not null,
				start datetime, end datetime, duration time);
			create table stepmodel (id integer primary key autoincrement, name varchar(255) not null,
				job_id integer not null references jobmodel (id), status varchar(255) not null, data text,
				start datetime not null, end datetime, duration time);
			"""
		)
		conn.commit()
		self.conn = conn  # kept open, like the running Press agent (keeps -wal/-shm around)

	def add_bench(self, name, sites=(), rq_port=11001, domains=None):
		path = os.path.join(self.benches_dir, name)
		for d in ("logs", "sites", "config"):
			os.makedirs(os.path.join(path, d), exist_ok=True)
		write_json(
			os.path.join(path, "config.json"),
			{"docker_image": f"registry.frappe.cloud/{name}:1", "web_port": 18001, "socketio_port": 19001,
			 "rq_port": rq_port, "rq_cache_port": 13001, "single_container": True},
		)
		write_json(os.path.join(path, "sites", "common_site_config.json"), {"redis_queue": "redis://localhost:11000", "monitor": True})
		for site in sites:
			cfg = {"db_name": "x"}
			if domains and site in domains:
				cfg["domains"] = domains[site]
			write_json(os.path.join(path, "sites", site, "site_config.json"), cfg)
		return path

	def move_site(self, site, source, target):
		os.rename(os.path.join(self.benches_dir, source, "sites", site), os.path.join(self.benches_dir, target, "sites", site))

	def add_job(self, name, status, data, start=None, end=None, agent_job_id=None, enqueue=None):
		cur = self.conn.execute(
			"insert into jobmodel (name, status, agent_job_id, data, enqueue, start, end) values (?,?,?,?,?,?,?)",
			(name, status, agent_job_id, json.dumps(data), local(enqueue or start or NOW),
			 local(start) if start else None, local(end) if end else None),
		)
		self.conn.commit()
		return cur.lastrowid

	def set_job(self, jid, **fields):
		for key, value in fields.items():
			if isinstance(value, datetime):
				value = local(value)
			elif isinstance(value, (dict, list)):
				value = json.dumps(value)
			self.conn.execute(f"update jobmodel set {key} = ? where id = ?", (value, jid))
		self.conn.commit()

	def add_step(self, jid, name, status, data, start=NOW):
		self.conn.execute(
			"insert into stepmodel (name, job_id, status, data, start) values (?,?,?,?,?)",
			(name, jid, status, json.dumps(data), local(start)),
		)
		self.conn.commit()

	def close(self):
		self.conn.close()


class PressCase(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.press = FakePress(self.tmp.name)
		self.spool = os.path.join(self.tmp.name, "spool")

	def tearDown(self):
		self.press.close()
		self.tmp.cleanup()


class TestPressDiscovery(PressCase):
	def test_detect_and_describe(self):
		self.assertTrue(press.detect(self.press.agent_dir))
		self.assertFalse(press.detect(os.path.join(self.tmp.name, "nope")))
		path = self.press.add_bench(
			"bench-0001-000002-f1-mumbai", sites=("a.frappe.cloud", "b.frappe.cloud"), rq_port=11007,
			domains={"a.frappe.cloud": ["erp.example.com", "a.frappe.cloud"]},
		)
		os.makedirs(os.path.join(path, "sites", "archived"))  # Server.move_site leftovers: not a site
		os.makedirs(os.path.join(self.press.benches_dir, "junk"))  # no config.json: not a bench
		benches = press.discover_press_benches(self.press.agent_dir, nginx_access_log=self.press.access_log)
		self.assertEqual(len(benches), 1)
		b = benches[0]
		self.assertEqual(b["name"], "bench-0001-000002-f1-mumbai")
		self.assertEqual(b["sites"], ["a.frappe.cloud", "b.frappe.cloud"])
		self.assertEqual(b["logs_dir"], os.path.join(path, "logs"))
		self.assertEqual(b["redis_queue"], "redis://127.0.0.1:11007")  # rq_port, not the in-container 11000
		self.assertEqual(b["nginx_access_log"], self.press.access_log)
		self.assertEqual(b["site_domains"], {"erp.example.com": "a.frappe.cloud"})
		self.assertEqual(b["platform"], "press")

	def test_discover_benches_auto_detects_press(self):
		self.press.add_bench("bench-a", sites=("a.frappe.cloud",))
		found = discovery.discover_benches(
			platform=None, search_globs=(), nginx_default=None, press_agent_dir=self.press.agent_dir
		)
		self.assertEqual([b["name"] for b in found], ["bench-a"])
		generic = discovery.discover_benches(
			platform="generic", search_globs=(), nginx_default=None, press_agent_dir=self.press.agent_dir
		)
		self.assertEqual(generic, [])
		self.assertEqual(discovery.resolve_platform(None, os.path.join(self.tmp.name, "nope")), "generic")

	def test_explicit_press_bench_path(self):
		path = self.press.add_bench("bench-b", sites=("b.frappe.cloud",))
		found = discovery.discover_benches([path], nginx_default=None)
		self.assertEqual(found[0]["sites"], ["b.frappe.cloud"])
		self.assertEqual(found[0]["platform"], "press")

	def test_nginx_main_format_and_custom_domain(self):
		parser = NginxParser(
			"f1", site_benches={"a.frappe.cloud": "bench-a", "b.frappe.cloud": "bench-a"},
			site_aliases={"erp.example.com": "a.frappe.cloud"}, log_file=self.press.access_log,
		)
		# log_format main: ... "$http_referer" "$http_user_agent" "$http_x_forwarded_for" "$host" $request_time
		parser.feed('10.0.0.5 - - [29/Oct/2026:02:00:13 +0000] "GET /app HTTP/2.0" 502 166 "-" "Mozilla/5.0" "203.0.113.9" "erp.example.com" 0.002')
		parser.feed('10.0.0.5 - - [29/Oct/2026:02:00:14 +0000] "GET /api/method/ping HTTP/2.0" 200 20 "-" "curl" "-" "b.frappe.cloud" 0.010')
		metrics, events = parser.drain(NOW)
		by = {(m["site"], m["metric_name"]): m["value"] for m in metrics}
		self.assertEqual(by[("a.frappe.cloud", "http_502")], 1)
		self.assertEqual(by[("b.frappe.cloud", "http_requests")], 1)
		self.assertEqual(events[0]["site"], "a.frappe.cloud")
		self.assertEqual(events[0]["bench"], "bench-a")


# what the Press agent renders in a bench folder (mode 0644), as on the dev/press server
COMPOSE = """version: "3.8"
services:
  web:
    image: localhost:5000/wolf-press-bench:latest
    ports:
      - "18007:8000"
  redis-cache:
    image: redis:6.0
"""
NGINX = """upstream bench-0001-000002-f1-mumbai-web-server {
	server 127.0.0.1:18007 fail_timeout=0;
}

upstream bench-0001-000002-f1-mumbai-socketio-server {
	server 127.0.0.1:19007 fail_timeout=0;
}

map $host $site_name_bench_0001_000002_f1_mumbai {

	erp.example.com a.frappe.cloud;
	a.frappe.cloud a.frappe.cloud;
	default $host;
}
"""


@unittest.skipIf(os.geteuid() == 0, "root reads mode 000 files")
class TestPressAsWolfAgent(PressCase):
	"""The daemon runs as wolf-agent, in the frappe group: the Press agent's config.json, each bench's
	config.json and every site_config.json are 0600 (checked on dev/press), so it reads around them."""

	def setUp(self):
		super().setUp()
		self.locked = []

	def tearDown(self):
		for path in self.locked:  # before the folder goes
			if os.path.exists(path):
				os.chmod(path, 0o600)
		super().tearDown()

	def lock(self, path):
		os.chmod(path, 0)
		self.locked.append(path)

	def bench(self):
		path = self.press.add_bench("bench-0001-000002-f1-mumbai", sites=("a.frappe.cloud",), rq_port=11007,
		                            domains={"a.frappe.cloud": ["erp.example.com"]})  # fmt: skip
		for name, text in (("docker-compose.yml", COMPOSE), ("nginx.conf", NGINX)):
			with open(os.path.join(path, name), "w") as f:
				f.write(text)
		self.lock(os.path.join(path, "config.json"))
		self.lock(os.path.join(path, "sites", "a.frappe.cloud", "site_config.json"))
		return path

	def test_detects_press_without_reading_its_config(self):
		self.lock(os.path.join(self.press.agent_dir, "config.json"))
		self.assertIsNone(press.read_agent_config(self.press.agent_dir))
		self.assertTrue(press.detect(self.press.agent_dir))
		self.assertEqual(discovery.resolve_platform(None, self.press.agent_dir), "press")
		os.unlink(self.press.db)  # a config.json alone is not enough
		self.assertFalse(press.detect(self.press.agent_dir))

	def test_rediscovers_from_readable_files(self):
		self.lock(os.path.join(self.press.agent_dir, "config.json"))
		path = self.bench()
		# the benches folder is what registration read as root
		found = press.discover_press_benches(self.press.agent_dir, nginx_access_log=self.press.access_log,
		                                     benches_dir=self.press.benches_dir)  # fmt: skip
		self.assertEqual(len(found), 1)
		b = found[0]
		self.assertEqual((b["name"], b["path"], b["sites"]), ("bench-0001-000002-f1-mumbai", path, ["a.frappe.cloud"]))
		self.assertEqual(b["docker_image"], "localhost:5000/wolf-press-bench:latest")
		self.assertEqual(b["redis_queue"], "redis://127.0.0.1:11007")  # web 18007: offset 7
		self.assertEqual(b["site_domains"], {"erp.example.com": "a.frappe.cloud"})

	def test_a_readable_config_wins(self):
		path = self.press.add_bench("bench-r", sites=("r.frappe.cloud",), rq_port=None)
		with open(os.path.join(path, "nginx.conf"), "w") as f:
			f.write(NGINX)
		b = press.describe_press_bench(path)
		self.assertIsNone(b["redis_queue"])  # an older bench without rq_port: its Redis is not published
		self.assertEqual(b["docker_image"], "registry.frappe.cloud/bench-r:1")

	def test_the_daemon_watches_jobs(self):
		self.lock(os.path.join(self.press.agent_dir, "config.json"))
		self.bench()
		cfg = {"hostname": "f1", "benches": [], "press": {"agent_dir": self.press.agent_dir,
		       "benches_directory": self.press.benches_dir}, "logs": {}}  # fmt: skip
		c = Collector(cfg, state_path=os.path.join(self.spool, "tail-state.json"))
		self.addCleanup(c.close)
		self.assertIsNotNone(c.press_jobs)
		self.assertEqual([b["name"] for b in c.benches], ["bench-0001-000002-f1-mumbai"])

	def test_registration_on_an_app_server_behind_a_proxy_and_on_the_proxy(self):
		from wolf_agent import cli

		path = os.path.join(self.press.agent_dir, "config.json")
		with open(path) as f:
			agent_cfg = json.load(f)
		write_json(path, {**agent_cfg, "proxy_ip": "10.0.0.3"})  # agent setup config --proxy-ip
		cfg = {"press": {"agent_dir": self.press.agent_dir}}
		cli._remember_press(cfg)
		self.assertEqual(cfg["press"]["proxy_ip"], "10.0.0.3")
		self.assertEqual(cfg["press"]["server_name"], "f1-mumbai.frappe.cloud")
		self.assertNotIn("extra_logs", cfg)
		write_json(path, agent_cfg)  # the proxy removed in Press: refresh forgets it
		cli._remember_press(cfg)
		self.assertNotIn("proxy_ip", cfg["press"])
		# a proxy server: Press's proxy role creates nginx/proxy.conf; no bench, its access log is read
		os.makedirs(os.path.join(self.press.agent_dir, "nginx"), exist_ok=True)
		open(os.path.join(self.press.agent_dir, "nginx", "proxy.conf"), "w").close()
		cfg = {"press": {"agent_dir": self.press.agent_dir, "nginx_access_log": "/var/log/nginx/access.log"}}
		cli._remember_press(cfg)
		cli._remember_press(cfg)  # registering again adds it once
		self.assertEqual(cfg["extra_logs"], [{"path": "/var/log/nginx/access.log", "parser": "nginx", "site_from_host": True}])
		cfg["extra_logs"] = [{"path": "/var/log/nginx/access.log", "parser": "nginx"}]  # registered before
		cli._remember_press(cfg)
		self.assertTrue(cfg["extra_logs"][0]["site_from_host"])

	def test_a_proxy_log_names_its_sites(self):
		# a Press proxy serves every site of its app servers: the site is $host, a custom domain
		# maps to its site through the proxy's nginx/hosts/<host>/map.json
		for host, target in (("erp.example.com", "a.frappe.cloud"), ("a.frappe.cloud", "a.frappe.cloud")):
			write_json(os.path.join(self.press.agent_dir, "nginx", "hosts", host, "map.json"), {host: target})
		write_json(os.path.join(self.press.agent_dir, "nginx", "hosts", "*.n1", "map.json"), {"*.n1": "x"})
		aliases = press.proxy_hosts(self.press.agent_dir)
		self.assertEqual(aliases, {"erp.example.com": "a.frappe.cloud"})
		parser = NginxParser("n1.example.net", site_from_host=True, site_aliases=aliases, ignore_hosts=("n1.example.net",))
		for host in ("erp.example.com", "b.frappe.cloud", "n1.example.net", "-"):
			parser.feed(f'45.33.32.156 - - [29/Oct/2026:02:00:13 +0000] "GET /x HTTP/2.0" 200 1 "-" "curl" "45.33.32.156" "{host}" 0.002')
		sites = sorted({m["site"] or "" for m in parser.drain(NOW)[0] if m["metric_name"] == "http_requests"})
		self.assertEqual(sites, ["", "a.frappe.cloud", "b.frappe.cloud"])  # the proxy's own name and "-": no site
		# X-Forwarded-For is the client's to choose: never the site, whatever it holds
		for xff in ("evil.example.com", "1.2.3.4, 5.6.7.8", "x.y"):
			parser.feed(f'45.33.32.156 - - [29/Oct/2026:02:00:14 +0000] "GET /.env HTTP/2.0" 404 1 "-" "curl" "{xff}" "a.frappe.cloud" 0.002')
		sites = {m["site"] for m in parser.drain(NOW)[0] if m["metric_name"] == "http_requests"}
		self.assertEqual(sites, {"a.frappe.cloud"})

	def test_refresh_saves_what_root_reads_without_registering(self):
		import argparse
		import contextlib
		import io

		from wolf_agent import cli

		path = os.path.join(self.press.agent_dir, "config.json")
		with open(path) as f:
			write_json(path, {**json.load(f), "proxy_ip": "10.0.0.3"})
		conf = os.path.join(self.tmp.name, "wolf-agent.json")
		write_json(conf, {"url": "https://wolf.example", "agent_id": "WAG-1", "agent_secret": "s", "hostname": "f1",
		                  "press": {"agent_dir": self.press.agent_dir}})  # fmt: skip
		with contextlib.redirect_stdout(io.StringIO()) as out:
			cli.cmd_refresh(argparse.Namespace(config=conf))
			cli.cmd_refresh(argparse.Namespace(config=conf))
		self.assertEqual(out.getvalue().count("updated"), 1)
		with open(conf) as f:
			saved = json.load(f)
		self.assertEqual((saved["platform"], saved["press"]["proxy_ip"], saved["agent_id"]), ("press", "10.0.0.3", "WAG-1"))

	def test_what_registration_read_is_kept(self):
		# an older bench: its config (read by root at registration) has no rq_port, so its Redis is not
		# published; the daemon, unable to read it, must not probe 11000 + its offset instead
		path = self.bench()
		os.chmod(os.path.join(path, "config.json"), 0o600)
		with open(os.path.join(path, "config.json"), "w") as f:
			json.dump({"docker_image": "registry.frappe.cloud/old:2", "web_port": 18007}, f)
		registered = press.discover_press_benches(self.press.agent_dir, nginx_access_log=None)
		self.assertEqual((registered[0]["redis_queue"], registered[0]["config_read"]), (None, True))
		os.chmod(os.path.join(path, "config.json"), 0)
		found = press.discover_press_benches(self.press.agent_dir, nginx_access_log=None)
		self.assertEqual(found[0]["redis_queue"], "redis://127.0.0.1:11007")  # derived, alone
		kept = press.keep_registered(found, registered)
		self.assertEqual((kept[0]["redis_queue"], kept[0]["docker_image"]), (None, "registry.frappe.cloud/old:2"))
		# and on the next rediscovery, from the kept values
		again = press.keep_registered(press.discover_press_benches(self.press.agent_dir, nginx_access_log=None), kept)
		self.assertIsNone(again[0]["redis_queue"])
		# a bench new since registration keeps what it was found with
		fresh = press.discover_press_benches(self.press.agent_dir, nginx_access_log=None)
		self.assertEqual(press.keep_registered(fresh, [])[0]["redis_queue"], "redis://127.0.0.1:11007")

	def test_registration_remembers_press(self):
		from wolf_agent import cli

		cfg = {"press": {"agent_dir": self.press.agent_dir}}
		self.assertEqual(cli._remember_press(cfg), "f1-mumbai.frappe.cloud")  # registration: root reads the config
		self.assertEqual(cfg["platform"], "press")
		self.assertEqual(cfg["press"]["benches_directory"], self.press.benches_dir)
		self.assertNotIn("proxy_ip", cfg["press"])
		self.assertNotIn("extra_logs", cfg)
		cfg = {"platform": "generic", "press": {"agent_dir": self.press.agent_dir}}
		self.assertIsNone(cli._remember_press(cfg))  # --platform generic stays
		self.assertEqual(cfg["platform"], "generic")


class TestPressJobs(PressCase):
	def watcher(self, known=None):
		benches = known or (lambda: {n for n in os.listdir(self.press.benches_dir)})
		return press.PressJobWatcher(
			"f1", agent_dir=self.press.agent_dir, state_path=os.path.join(self.spool, "press-jobs.json"), known_benches=benches,
			benches_dir=self.press.benches_dir,
		)

	def test_finished_jobs_land_on_the_bench_their_last_step_ran_in(self):
		# what dev/press recorded: both jobs ended between two polls, their data `null`
		old = self.press.add_bench("bench-0001-000001-f1", sites=("w.frappe.cloud",))
		new = os.path.join(self.press.benches_dir, "bench-0001-000002-f1")
		w = self.watcher(known=lambda: {"bench-0001-000001-f1"})  # the new bench is not rediscovered yet
		self.assertEqual(w.poll(NOW), [])  # baseline
		jid = self.press.add_job("New Bench", "Success", None, start=NOW - timedelta(seconds=20), end=NOW)
		self.press.add_step(jid, "Initialize Bench", "Success", {"command": "docker run --rm --net none -v ...", "directory": new})
		self.press.add_step(jid, "Bench Setup NGINX", "Success", {"command": "sudo systemctl reload nginx", "directory": self.press.agent_dir})
		jid = self.press.add_job("Update Site Migrate", "Success", None, start=NOW - timedelta(seconds=10), end=NOW)
		self.press.add_step(jid, "Enable Maintenance Mode", "Success", {
			"command": "docker exec  -w /home/frappe/frappe-bench  bench-0001-000001-f1 bench --site w.frappe.cloud set-maintenance-mode on",
			"directory": old})  # fmt: skip
		self.press.add_step(jid, "Move Site", "Success", None)
		self.press.add_step(jid, "Reload NGINX", "Success", {"command": "sudo systemctl reload nginx", "directory": self.press.agent_dir})
		self.press.add_step(jid, "Migrate Site", "Success", {
			"command": "docker exec  -w /home/frappe/frappe-bench  bench-0001-000002-f1 bench --site w.frappe.cloud migrate",
			"directory": new})  # fmt: skip
		events = w.poll(NOW)
		got = [(e["payload"]["press_job"], e["bench"], e["site"]) for e in events]
		self.assertEqual(got, [("New Bench", "bench-0001-000002-f1", None),
		                       ("Update Site Migrate", "bench-0001-000002-f1", "w.frappe.cloud")])  # fmt: skip

	def test_first_run_skips_history_then_dedupes(self):
		self.press.add_bench("bench-old", sites=("a.frappe.cloud",))
		self.press.add_bench("bench-new")
		old = NOW - timedelta(days=2)
		self.press.add_job("Update Site Migrate", "Success", None, start=old, end=old)
		self.press.add_job("Backup Site", "Success", None, start=old, end=old)
		running = self.press.add_job(
			"Update Site Migrate", "Running",
			{"function": "update_site_migrate_job", "args": ["a.frappe.cloud", "bench-old", "bench-new", True, False, False], "kwargs": {}},
			start=NOW - timedelta(minutes=3), agent_job_id="b2c3d4e5",
		)
		events = self.watcher().poll(NOW)
		self.assertEqual(len(events), 1)
		ev = events[0]
		self.assertEqual((ev["type"], ev["category"], ev["site"], ev["bench"]), ("deployment", "press", "a.frappe.cloud", "bench-new"))
		self.assertEqual(ev["payload"]["agent_job_id"], "b2c3d4e5")
		self.assertEqual(ev["payload"]["local_job_id"], running)
		self.assertEqual(ev["timestamp"], "2026-10-29T02:07:00Z")

		# restart: nothing new; then the job fails → one failure event, once
		self.assertEqual(self.watcher().poll(NOW), [])
		self.press.set_job(running, status="Failure", end=NOW, data={"traceback": "Traceback ...\nOperationalError: (1054)"})
		self.press.add_step(running, "Migrate Site", "Failure", {"command": "docker exec bench-new bench --site a.frappe.cloud migrate"})
		events = self.watcher().poll(NOW)
		self.assertEqual([(e["type"], e["category"]) for e in events], [("error", "press_job_failed")])
		self.assertEqual(events[0]["payload"]["failed_steps"], ["Migrate Site"])
		self.assertIn("OperationalError", events[0]["payload"]["traceback"])
		self.assertEqual(self.watcher().poll(NOW), [])

	def test_short_job_finished_between_polls_scoped_from_steps(self):
		bench = self.press.add_bench("bench-0001-000003-f1", sites=("c.frappe.cloud",))
		w = self.watcher()
		self.assertEqual(w.poll(NOW), [])  # baseline
		# Site.migrate_job carries no bench/site in its args, and its data is
		# overwritten with the result when it ends: the steps name them.
		jid = self.press.add_job("Migrate Site", "Success", None, start=NOW - timedelta(seconds=40), end=NOW)
		self.press.add_step(jid, "Migrate Site", "Success", {
			"command": "docker exec -w /home/frappe/frappe-bench  bench-0001-000003-f1 bench --site c.frappe.cloud migrate",
			"directory": bench, "status": "Success",
		})
		events = w.poll(NOW)
		self.assertEqual(len(events), 1)
		self.assertEqual((events[0]["bench"], events[0]["site"]), ("bench-0001-000003-f1", "c.frappe.cloud"))
		self.assertEqual(w.poll(NOW), [])

	def test_unscoped_running_job_waits_then_ships_host_level(self):
		w = self.watcher()
		w.poll(NOW)
		self.press.add_job("Bench Restart", "Running", {"function": "restart_job", "args": [], "kwargs": {}}, start=NOW - timedelta(seconds=30))
		self.assertEqual(w.poll(NOW), [])  # bench not known yet
		events = w.poll(NOW + timedelta(minutes=3))
		self.assertEqual(len(events), 1)
		self.assertIsNone(events[0]["bench"])
		self.assertEqual(events[0]["host"], "f1")

	def test_stale_running_job_does_not_pin_the_floor(self):
		w = self.watcher()
		w.poll(NOW)
		self.press.add_job("Update Bench In Place", "Running", {"function": "update_inplace", "args": [["x.frappe.cloud"], "img", []], "kwargs": {}},
			enqueue=NOW - timedelta(days=3))
		later = self.press.add_job("New Bench", "Success", None, start=NOW, end=NOW)
		events = w.poll(NOW)
		self.assertEqual([e["payload"]["local_job_id"] for e in events], [later])
		self.assertEqual(w.state["floor"], later)

	def test_unreadable_db_returns_none(self):
		w = press.PressJobWatcher("f1", agent_dir=os.path.join(self.tmp.name, "missing"))
		self.assertIsNone(w.poll(NOW))


class TestPressFilesystemFallback(PressCase):
	def test_new_bench_and_site_move(self):
		state = os.path.join(self.spool, "press-benches.json")
		self.press.add_bench("bench-1", sites=("a.frappe.cloud",))
		w = press.PressBenchWatcher("f1", state_path=state)
		discover = lambda: press.discover_press_benches(self.press.agent_dir, nginx_access_log=None)  # noqa: E731
		self.assertEqual(w.poll(discover(), NOW), [])  # first snapshot
		self.press.add_bench("bench-2")
		self.press.move_site("a.frappe.cloud", "bench-1", "bench-2")
		events = press.PressBenchWatcher("f1", state_path=state).poll(discover(), NOW)
		self.assertEqual([e["title"] for e in events], ["Press: new bench bench-2", "Press: a.frappe.cloud moved to bench-2"])
		self.assertTrue(all(e["type"] == "deployment" for e in events))
		self.assertEqual(events[1]["payload"]["from_bench"], "bench-1")


class TestPressCollector(PressCase):
	def test_rediscovers_new_bench_and_ships_deployments(self):
		self.press.add_bench("bench-1", sites=("a.frappe.cloud",))
		ticks = [0.0]
		cfg = {
			"hostname": "f1", "collect_host_metrics": False, "auth_log": False, "benches": [], "platform": "press",
			"tls": False, "mariadb": False, "processes": False,
			"press": {"agent_dir": self.press.agent_dir, "nginx_access_log": self.press.access_log, "rediscover_interval": 60},
		}
		state_path = os.path.join(self.spool, "tail-state.json")
		c = Collector(cfg, state_path=state_path, clock=lambda: ticks[0])
		self.assertEqual([b["name"] for b in c.benches], ["bench-1"])
		c.collect(NOW)  # baseline for jobs

		# a deploy: new bench, site moved, its logs written before we notice
		path = self.press.add_bench("bench-2")
		self.press.move_site("a.frappe.cloud", "bench-1", "bench-2")
		with open(os.path.join(path, "logs", "web.error.log"), "w") as f:
			f.write(
				"2026-10-29 02:05:00,000 ERROR frappe Request failed\nTraceback (most recent call last):\n"
				'  File "apps/frappe/frappe/app.py", line 114, in application\n'
				"pymysql.err.ProgrammingError: (1146, \"Table 'tabWolf' doesn't exist\")\n"
				"2026-10-29 02:05:01,000 INFO frappe next\n"
			)
		self.press.add_job("Update Site Migrate", "Running",
			{"function": "update_site_migrate_job", "args": ["a.frappe.cloud", "bench-1", "bench-2", True, False, False], "kwargs": {}},
			start=NOW)
		ticks[0] = 61.0
		metrics, events = c.collect(NOW)
		self.assertEqual(sorted(b["name"] for b in c.benches), ["bench-1", "bench-2"])
		# bench-2's logs were read from the start: the traceback written before rediscovery is there
		self.assertIn(("error", "bench-2"), [(e["type"], e["bench"]) for e in events])
		deploys = [e for e in events if e["type"] == "deployment"]
		self.assertEqual([(e["bench"], e["site"]) for e in deploys], [("bench-2", "a.frappe.cloud")])
		site_benches = {m["site"]: m["bench"] for m in metrics if m["metric_name"] == "http_requests"}
		self.assertEqual(site_benches.get("a.frappe.cloud"), "bench-2")
		c.close()


if __name__ == "__main__":
	unittest.main()
