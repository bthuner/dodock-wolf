"""A Press (Frappe Cloud) app server, simulated on disk for the real agent to read.

The layout is what docs/press.md describes: the Press agent's `config.json` and `jobs.sqlite3`,
`benches/<bench>/` with `config.json` (`docker_image`), `sites/<site>/site_config.json` and
`logs/`, one nginx access log in Press's `main` format, and the host's auth.log. Sites and
benches are names only: no Frappe runs behind them. Deployments are Press agent jobs.
"""

import json
import os
import sqlite3
from contextlib import closing
from datetime import timedelta

from ..collector import BENCH_LOGS, SITE_LOGS
from . import core
from .server import DemoServer

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
JOBS_SCHEMA = """
create table if not exists jobmodel (id integer primary key autoincrement, name varchar(255) not null,
	status varchar(255) not null, agent_job_id varchar(255), data text, enqueue datetime not null,
	start datetime, end datetime, duration time);
create table if not exists stepmodel (id integer primary key autoincrement, name varchar(255) not null,
	job_id integer not null references jobmodel (id), status varchar(255) not null, data text,
	start datetime not null, end datetime, duration time);
"""


class PressDemo(DemoServer):
	kind = "press"
	nginx_line = staticmethod(core.nginx_main)

	def __init__(self, root=DEFAULT_ROOT, host=HOST, spool_dir=None, rng=None, benches=BENCHES):
		super().__init__(os.path.abspath(root), host, benches, spool_dir=spool_dir, rng=rng)
		self.agent_dir = os.path.join(self.root, "agent")
		self.benches_dir = os.path.join(self.root, "benches")
		self.nginx_log = os.path.join(self.root, "nginx", "access.log")
		self.auth_log = os.path.join(self.root, "log", "auth.log")
		self.jobs_path = os.path.join(self.agent_dir, "jobs.sqlite3")

	def bench_path(self, bench, *parts):
		return os.path.join(self.benches_dir, bench, *parts)

	def tracked_paths(self):
		paths = [self.nginx_log, self.auth_log]
		for bench in self.benches:
			paths += [self.bench_path(bench, "logs", name) for name in BENCH_LOGS]
		for site in self.sites:
			paths += [self.bench_path(site.bench, "sites", site.name, "logs", name) for name in SITE_LOGS]
		return paths

	def layout(self):
		core.write_json(
			os.path.join(self.agent_dir, "config.json"),
			{"benches_directory": self.benches_dir, "nginx_directory": os.path.join(self.agent_dir, "nginx"),
			 "name": self.host, "redis_port": 25025, "web_port": 25052},
		)  # fmt: skip
		for n, bench in enumerate(self.benches):
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
		"""Press mode on this root; checks with nothing real behind them off."""
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
			**core.CHECKS_OFF,
		}

	def ready(self):
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

	def deploy(self, at, site, failed=False):
		"""A Press `Update Site Migrate` job."""
		status = "Failure" if failed else "Success"
		docker = f"docker exec -w /home/frappe/frappe-bench {site.bench} bench --site {site.name}"
		steps = [
			("Enable Maintenance Mode", "Success", f"{docker} set-maintenance-mode on"),
			("Backup Site", "Success", f"{docker} backup --with-files"),
			("Migrate Site", status, f"{docker} migrate"),
			("Disable Maintenance Mode", "Skipped" if failed else "Success", f"{docker} set-maintenance-mode off"),
		]
		failure = None
		if failed:
			failure = {"traceback": core.MIGRATE_TRACEBACK, "output": "Updating DocTypes for erpnext : [=====     ] 52%"}
		self.add_job("Update Site Migrate", status, "update_site_migrate_job",
		             [site.name, site.bench, site.bench, True, False, False], at, 95, steps, failure)  # fmt: skip


	def bench_failure(self, at, bench):
		"""A Press `Patch App` job that fails."""
		docker = f"docker exec -w /home/frappe/frappe-bench {bench}"
		steps = [("Git Apply", "Failure", f"{docker} git -C apps/erpnext apply /tmp/fix-stock-ledger.patch")]
		failure = {"traceback": core.PATCH_FAILURE, "output": ""}
		self.add_job("Patch App", "Failure", "patch_app", [], at, 12, steps, failure)
