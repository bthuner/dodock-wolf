"""A Press (Frappe Cloud) app server, simulated on disk for the real agent to read.

The layout is what docs/press.md describes: the Press agent's `config.json` and `jobs.sqlite3`,
`benches/<bench>/` with `config.json` (`docker_image`), `sites/<site>/site_config.json` and
`logs/`, one nginx access log in Press's `main` format, and the host's auth.log. Sites and
benches are names only: no Frappe runs behind them.

`run()` lays it out empty, waits until the agent (platform press, pointed here by
`agent_overrides()`) tracks every file and has read the empty job history, appends `days` of
history, then writes live traffic with the storyline below every `cycle` minutes.
"""

import json
import logging
import os
import random
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone

from ..collector import BENCH_LOGS, SITE_LOGS
from ..util import utc_iso
from . import core
from .core import MINUTE, Site

log = logging.getLogger(__name__)

HOST = "f1-demo-press"
DEFAULT_ROOT = "/home/frappe/demo-press"
# bench -> [(site, peak requests/minute, custom domains)]
BENCHES = {
	"bench-0012-000431-f1-demo": [
		("acme.press.test", 14, ["erp.acme.example"]),
		("globex.press.test", 6, []),
		("initech.press.test", 3, []),
	],
	"bench-0012-000447-f1-demo": [
		("umbrella.press.test", 9, ["erp.umbrella.example"]),
		("hooli.press.test", 4, []),
		("stark.press.test", 2, []),
	],
	"bench-0015-000012-f1-demo": [
		("wayne.press.test", 5, []),
		("tyrell.press.test", 2, []),
	],
}
STORY_MINUTES = 25  # the storyline below runs from 0' to 24'
DAILY_STORY = (10, 30)  # local time of the storyline on each day of history
NIGHTLY_CRON = (2, 10)  # and of the nightly job that fails
JOBS_SCHEMA = """
create table if not exists jobmodel (id integer primary key autoincrement, name varchar(255) not null,
	status varchar(255) not null, agent_job_id varchar(255), data text, enqueue datetime not null,
	start datetime, end datetime, duration time);
create table if not exists stepmodel (id integer primary key autoincrement, name varchar(255) not null,
	job_id integer not null references jobmodel (id), status varchar(255) not null, data text,
	start datetime not null, end datetime, duration time);
"""
CRON_METHODS = [
	"erpnext.accounts.doctype.process_deferred_accounting.process_deferred_accounting.process_deferred_accounting",
	"erpnext.stock.reorder_item.reorder_item",
	"erpnext.setup.doctype.email_digest.email_digest.send",
	"hrms.hr.utils.allocate_earned_leaves",
]


class PressDemo:
	def __init__(self, root=DEFAULT_ROOT, host=HOST, spool_dir=None, rng=None):
		self.root = os.path.abspath(root)
		self.host = host
		self.spool_dir = spool_dir
		self.rng = rng or random.Random()
		self.agent_dir = os.path.join(self.root, "agent")
		self.benches_dir = os.path.join(self.root, "benches")
		self.nginx_log = os.path.join(self.root, "nginx", "access.log")
		self.auth_log = os.path.join(self.root, "log", "auth.log")
		self.state_path = os.path.join(self.root, "demo-state.json")
		self.jobs_path = os.path.join(self.agent_dir, "jobs.sqlite3")
		self.sites = [
			Site(name, bench, rate, domains) for bench, sites in BENCHES.items() for name, rate, domains in sites
		]
		self.logs = core.Logs()
		self.disk = 61.0

	# --- layout ---------------------------------------------------------------------------

	def bench_path(self, bench, *parts):
		return os.path.join(self.benches_dir, bench, *parts)

	def tracked_paths(self):
		"""Every file the agent tails here, as it names them."""
		paths = [self.nginx_log, self.auth_log]
		for bench in BENCHES:
			paths += [self.bench_path(bench, "logs", name) for name in BENCH_LOGS]
		for site in self.sites:
			paths += [self.bench_path(site.bench, "sites", site.name, "logs", name) for name in SITE_LOGS]
		return paths

	def layout(self):
		"""Create the server layout with empty logs and an empty job history (idempotent)."""
		core.write_json(
			os.path.join(self.agent_dir, "config.json"),
			{"benches_directory": self.benches_dir, "nginx_directory": os.path.join(self.agent_dir, "nginx"),
			 "name": self.host, "redis_port": 25025, "web_port": 25052},
		)  # fmt: skip
		for n, bench in enumerate(BENCHES):
			# no rq_port: there is no queue Redis behind these benches to probe
			core.write_json(
				self.bench_path(bench, "config.json"),
				{"docker_image": f"registry.press.test/{bench.rsplit('-', 2)[0]}:deploy-{431 + n}",
				 "web_port": 18000 + n, "socketio_port": 19000 + n, "name": bench},
			)  # fmt: skip
			core.write_json(self.bench_path(bench, "sites", "common_site_config.json"), {"db_host": "db.press.test"})
		for site in self.sites:
			config = {"db_name": "_" + site.name.split(".")[0], "db_type": "mariadb"}
			if site.domains:
				config["domains"] = site.domains
			core.write_json(self.bench_path(site.bench, "sites", site.name, "site_config.json"), config)
		for path in self.tracked_paths():
			core.touch(path)
		with closing(sqlite3.connect(self.jobs_path)) as conn, conn:
			conn.executescript(JOBS_SCHEMA)

	def agent_overrides(self):
		"""Agent config for this server: Press mode on this root, checks with nothing real behind them off."""
		return {
			"platform": "press",
			"benches": [],
			"press": {
				"agent_dir": self.agent_dir,
				"nginx_access_log": self.nginx_log,
				"rediscover_interval": 15,
				"deployments": True,
			},
			"auth_log": self.auth_log,
			**{name: False for name in (
				"tls", "mariadb", "site_settings", "versions", "backups", "processes", "exposure",
				"integrity", "suricata", "wazuh",
			)},  # fmt: skip
		}

	def jobs_ready(self):
		"""The agent has read the (empty) job history once: jobs added from now on are reported."""
		state = core.read_json(os.path.join(self.spool_dir, "press-jobs.json"), {}) or {}
		return state.get("floor") is not None

	# --- Press jobs -----------------------------------------------------------------------

	def add_job(self, name, status, function, args, start, seconds, steps, failure=None):
		"""One Press agent job with its steps, in the peewee tables the agent reads."""
		end = start + timedelta(seconds=seconds)
		data = {"function": function, "args": args, "kwargs": {}}
		if failure:
			data.update(failure)
		with closing(sqlite3.connect(self.jobs_path)) as conn, conn:
			cur = conn.execute(
				"insert into jobmodel (name, status, agent_job_id, data, enqueue, start, end) values (?,?,?,?,?,?,?)",
				(name, status, f"{self.rng.randrange(10**6, 10**7)}", json.dumps(data),
				 str(core.local(start - timedelta(seconds=4))), str(core.local(start)), str(core.local(end))),
			)  # fmt: skip
			step_at = start
			for step_name, step_status, command in steps:
				conn.execute(
					"insert into stepmodel (name, job_id, status, data, start, end) values (?,?,?,?,?,?)",
					(step_name, cur.lastrowid, step_status, json.dumps({"command": command, "output": ""}),
					 str(core.local(step_at)), str(core.local(step_at + timedelta(seconds=seconds / len(steps))))),
				)  # fmt: skip
				step_at += timedelta(seconds=seconds / len(steps))

	def migrate_job(self, at, site, status="Success"):
		docker = f"docker exec -w /home/frappe/frappe-bench {site.bench} bench --site {site.name}"
		steps = [
			("Enable Maintenance Mode", "Success", f"{docker} set-maintenance-mode on"),
			("Backup Site", "Success", f"{docker} backup --with-files"),
			("Migrate Site", status, f"{docker} migrate"),
			("Disable Maintenance Mode", "Success" if status == "Success" else "Skipped", f"{docker} set-maintenance-mode off"),
		]
		failure = None
		if status == "Failure":
			failure = {
				"traceback": "Traceback (most recent call last):\n  File \"apps/frappe/frappe/migrate.py\", line 182, in run\n"
				"    self.run_schema_updates()\npymysql.err.OperationalError: (1054, \"Unknown column 'wolf_demo' in 'tabGL Entry'\")",
				"output": "Updating DocTypes for erpnext : [=====     ] 52%",
			}
		self.add_job("Update Site Migrate", status, "update_site_migrate_job",
		             [site.name, site.bench, site.bench, True, False, False], at, 95, steps, failure)  # fmt: skip

	def patch_job(self, at, bench):
		docker = f"docker exec -w /home/frappe/frappe-bench {bench}"
		steps = [("Git Apply", "Failure", f"{docker} git -C apps/erpnext apply /tmp/fix-stock-ledger.patch")]
		failure = {"traceback": "error: patch failed: erpnext/stock/stock_ledger.py:412\nerror: erpnext/stock/stock_ledger.py: patch does not apply",
		           "output": ""}  # fmt: skip
		self.add_job("Patch App", "Failure", "patch_app", [], at, 12, steps, failure)

	# --- the storyline --------------------------------------------------------------------

	def storyline(self, t0, n):
		"""(actions, outages) of one incident cycle starting at `t0`; `n` rotates benches and sites.

		0'  a Press migrate on one site, whose backend then answers 502 for 4 minutes
		6'  a request traceback on another site
		8'  a scheduled job fails
		11' a background worker is killed (OOM)
		14' an SSH brute force on the server; every third cycle it succeeds
		19' a web attack scan of a site
		24' every other cycle, a Patch App job fails
		"""
		sites = self.sites
		target = sites[(n * 3) % len(sites)]
		other = sites[(n * 3 + 1) % len(sites)]
		third = sites[(n * 3 + 2) % len(sites)]
		attacker = core.ATTACKERS[n % len(core.ATTACKERS)]
		at = lambda minutes: t0 + timedelta(minutes=minutes)  # noqa: E731
		actions = [
			(at(0), lambda: self.migrate_job(at(0), target, "Failure" if n % 4 == 3 else "Success")),
			(at(6), lambda: self.web_traceback(at(6), other)),
			(at(8), lambda: self.cron_failure(at(8), third, CRON_METHODS[n % len(CRON_METHODS)])),
			(at(11), lambda: self.worker_crash(at(11), target.bench)),
			(at(14), lambda: self.ssh_brute_force(at(14), attacker, succeed=n % 3 == 2)),
			(at(19), lambda: self.write_nginx(core.web_scan(self.rng, other, at(19), 4, 140, attacker))),
		]
		if n % 2:
			actions.append((at(24), lambda: self.patch_job(at(24), target.bench)))
		outages = [(target.name, at(0) + timedelta(seconds=20), at(4), 0.8)]
		return actions, outages

	def nightly(self, t0, n):
		site = self.sites[(n * 5) % len(self.sites)]
		return [(t0, lambda: self.cron_failure(t0, site, CRON_METHODS[0]))], []

	def web_traceback(self, at, site):
		lines = core.traceback_lines(
			at, "Request failed",
			[("apps/frappe/frappe/app.py", 114, "application", "response = frappe.api.handle(request)"),
			 ("apps/erpnext/erpnext/stock/utils.py", 42, "get_stock_balance", 'raise frappe.ValidationError("Warehouse missing")')],
			"frappe.exceptions.ValidationError: Warehouse Stores - AC is missing for company Acme",
		)  # fmt: skip
		self.logs.write(self.bench_path(site.bench, "sites", site.name, "logs", "frappe.web.log"), lines)

	def cron_failure(self, at, site, method):
		self.logs.write(
			self.bench_path(site.bench, "logs", "scheduler.log"),
			[core.pylog(at, "INFO", "scheduler", f"Scheduled Job Failed: {method} for {site.name}")],
		)

	def worker_crash(self, at, bench):
		job = f"{self.rng.randrange(16**8):08x}-{self.rng.randrange(16**4):04x}"
		self.logs.write(
			self.bench_path(bench, "logs", "worker.error.log"),
			[core.pylog(at, "ERROR", "rq.worker", f"[Job {job}]: exception raised while executing (frappe.utils.background_jobs.execute_job)"),
			 core.pylog(at + timedelta(seconds=40), "WARNING", "rq.worker",
			            "Moving job to FailedJobRegistry (Work-horse terminated unexpectedly; waitpid returned 9 (signal 9); )")],
		)  # fmt: skip

	def ssh_brute_force(self, at, attacker, succeed=False, attempts=40):
		users = ["root", "admin", "ubuntu", "frappe", "postgres", "test", "oracle", "git"]
		lines = []
		for i in range(attempts):
			t = at + timedelta(seconds=4 * i)
			pid = 30000 + self.rng.randrange(5000)
			user = users[i % len(users)]
			port = self.rng.randrange(30000, 65000)
			if user in ("root", "frappe"):
				lines.append(core.syslog(t, self.host, "sshd", pid, f"Failed password for {user} from {attacker} port {port} ssh2"))
			else:
				lines.append(core.syslog(t, self.host, "sshd", pid, f"Invalid user {user} from {attacker} port {port}"))
				lines.append(core.syslog(t, self.host, "sshd", pid,
				                         f"Failed password for invalid user {user} from {attacker} port {port} ssh2"))  # fmt: skip
		if succeed:
			t = at + timedelta(seconds=4 * attempts + 20)
			lines.append(core.syslog(t, self.host, "sshd", 39001, f"Accepted password for frappe from {attacker} port 52144 ssh2"))
		self.logs.write(self.auth_log, lines)

	def write_nginx(self, timed_lines):
		self.logs.write(self.nginx_log, [line for _, line in sorted(timed_lines, key=lambda x: x[0])])

	# --- time -----------------------------------------------------------------------------

	def stories(self, start, end, live_since, cycle):
		"""Storylines that touch [start, end): daily ones before `live_since`, then one per cycle."""
		found = []
		day = core.local(start - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
		while day.astimezone() < end and day.astimezone() < live_since:
			n = day.toordinal()
			for (h, m), fn in ((DAILY_STORY, self.storyline), (NIGHTLY_CRON, self.nightly)):
				t0 = day.replace(hour=h, minute=m).astimezone().astimezone(timezone.utc)
				if t0 < live_since:
					found.append(fn(t0, n))
			day += timedelta(days=1)
		first = live_since + MINUTE
		if end > first:
			# a storyline lasts STORY_MINUTES: start early enough to catch one still running at `start`
			back = -(-STORY_MINUTES // cycle)
			k = max(0, int((start - first).total_seconds() // (cycle * 60)) - back)
			while first + timedelta(minutes=cycle * k) < end:
				found.append(self.storyline(first + timedelta(minutes=cycle * k), k))
				k += 1
		return found

	def simulate(self, start, end, live_since, cycle, history=False):
		"""Write everything that happens in [start, end). With `history`, host metrics too."""
		actions, outages = [], []
		for a, o in self.stories(start, end, live_since, cycle):
			actions += [(t, fn) for t, fn in a if start <= t < end]
			outages += o
		actions.sort(key=lambda x: x[0])
		samples = []
		minute = start
		while minute < end:
			upto = min(core.floor_minute(minute) + MINUTE, end)
			lines = []
			busy = 0.0
			for site in self.sites:
				down = next((p for s, a, b, p in outages if s == site.name and a < upto and b > minute), None)
				if down:
					busy = 0.6
				lines += core.requests(self.rng, site, minute, upto, outage=down)
			while actions and actions[0][0] < upto:
				actions.pop(0)[1]()
			self.write_nginx(lines)
			if history:
				self.disk += 0.0002
				samples += core.host_metrics(self.rng, self.host, minute, busy=busy, disk=self.disk)
			minute = upto
		self.logs.flush()
		if samples:
			core.spool_host_history(self.spool_dir, self.host, samples)

	def run(self, days=7, live=True, cycle=30, timeout=300, stop=None, tick=5):
		self.layout()
		log.info("demo Press server laid out in %s; waiting for the agent to track it", self.root)
		core.wait_for_agent(self.spool_dir, self.tracked_paths(), self.jobs_ready, timeout=timeout)
		now = datetime.now(timezone.utc)
		state = core.read_json(self.state_path, {}) or {}
		until = _parse(state.get("until")) or now - timedelta(days=days)
		live_since = _parse(state.get("live_since")) or now
		if until < now - timedelta(minutes=1):
			log.info("writing history from %s to %s", utc_iso(until), utc_iso(now))
			chunk = until
			while chunk < now:  # a day at a time: the agent starts reading while the rest is written
				upto = min(chunk + timedelta(days=1), now)
				self.simulate(chunk, upto, live_since, cycle, history=True)
				chunk = upto
				self._save(chunk, live_since)
				log.info("history written up to %s", utc_iso(chunk))
			until = now
		if not live:
			self.logs.close()
			return
		log.info("live: traffic every %ss, an incident cycle every %s min", tick, cycle)
		try:
			while not (stop and stop.is_set()):
				time.sleep(tick)
				now = datetime.now(timezone.utc)
				self.simulate(until, now, live_since, cycle)
				until = now
				self._save(until, live_since)
		finally:
			self.logs.close()

	def _save(self, until, live_since):
		core.write_json(self.state_path, {"until": utc_iso(until), "live_since": utc_iso(live_since)})


def _parse(value):
	if not value:
		return None
	return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
