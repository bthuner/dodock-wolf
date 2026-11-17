"""A host running plain benches (`bench init`, Dokos images), simulated on disk.

Each bench is `benches/<bench>/` with `apps/frappe/` (what discovery looks for),
`sites/<site>/site_config.json`, `sites/common_site_config.json` and `logs/`. The host has one
nginx access log in a vhost_combined-like format (`$host` first) and an auth.log. Sites are
names only: no Frappe runs behind them.

Plain benches leave no trace of a deployment the agent could read, so deployments are marked
through the agent's deployment endpoint, as `wolf-agent mark-deployment` does, with their time.
"""

import logging
import os

from ..collector import BENCH_LOGS, SITE_LOGS
from . import core
from .server import DemoServer

log = logging.getLogger(__name__)

# bench -> [(site, peak requests/minute, custom domains)]
MULTI = {
	"erp-bench": [
		("erp.northwind.test", 12, ["erp.northwind.example"]),
		("compta.northwind.test", 5, []),
		("stock.contoso.test", 7, []),
		("rh.contoso.test", 3, []),
	],
	"portal-bench": [
		("portal.northwind.test", 9, []),
		("shop.contoso.test", 6, ["shop.contoso.example"]),
	],
}
SINGLE = {"frappe-bench": [("erp.single.test", 10, [])]}
# kind -> (benches, default host name, default root)
KINDS = {
	"multi": (MULTI, "dokos-multi-1", "/home/frappe/demo-multi"),
	"single": (SINGLE, "dokos-single-1", "/home/frappe/demo-single"),
}


class BenchDemo(DemoServer):
	nginx_line = staticmethod(core.nginx_vhost)

	def __init__(self, kind="multi", root=None, host=None, spool_dir=None, rng=None, mark_deployment=None, benches=None):
		"""`mark_deployment(bench, site, note, at)` records a deployment, normally through the agent's
		deployment endpoint; without it, deployments only show in bench.log."""
		model, default_host, default_root = KINDS[kind]
		super().__init__(os.path.abspath(root or default_root), host or default_host, benches or model,
		                 spool_dir=spool_dir, rng=rng)  # fmt: skip
		self.kind = kind
		self.mark_deployment = mark_deployment
		self.benches_dir = os.path.join(self.root, "benches")
		self.nginx_log = os.path.join(self.root, "nginx", "access.log")
		self.auth_log = os.path.join(self.root, "log", "auth.log")

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
		for bench in self.benches:
			os.makedirs(self.bench_path(bench, "apps", "frappe"), exist_ok=True)
			# no redis_queue: there is no queue Redis behind these benches to probe
			core.write_json(self.bench_path(bench, "sites", "common_site_config.json"), {"db_host": "127.0.0.1"})
		for site in self.sites:
			core.write_json(
				self.bench_path(site.bench, "sites", site.name, "site_config.json"),
				{"db_name": "_" + site.name.split(".")[0], "db_type": "mariadb"},
			)
		for path in self.tracked_paths():
			core.touch(path)

	def agent_overrides(self):
		"""The benches, as discovery would describe them, plus the custom domains nginx serves."""
		benches = []
		for bench, sites in self.benches.items():
			benches.append({
				"name": bench,
				"path": self.bench_path(bench),
				"sites": [name for name, _, _ in sites],
				"logs_dir": self.bench_path(bench, "logs"),
				"nginx_access_log": self.nginx_log,
				"redis_queue": None,
				"site_domains": {domain: name for name, _, domains in sites for domain in domains},
				"bench_toml": False,
			})  # fmt: skip
		return {"platform": "generic", "benches": benches, "auth_log": self.auth_log, **core.CHECKS_OFF}

	def deploy(self, at, site, failed=False):
		"""`bench update` then `bench migrate` of the site, logged in bench.log and marked."""
		bench_log = self.bench_path(site.bench, "logs", "bench.log")
		lines = [
			core.pylog(at, "INFO", "bench", "bench update --pull --patch --build --requirements"),
			core.pylog(at, "INFO", "bench", f"Migrating {site.name}"),
		]
		if failed:
			lines += core.traceback_lines(
				at, f"Migration of {site.name} failed",
				[("apps/frappe/frappe/migrate.py", 182, "run", "self.run_schema_updates()"),
				 ("apps/frappe/frappe/model/sync.py", 44, "sync_for", "frappe.db.updatedb(doctype)")],
				"pymysql.err.OperationalError: (1054, \"Unknown column 'wolf_demo' in 'tabGL Entry'\")",
			)  # fmt: skip
		self.logs.write(bench_log, lines)
		self._mark(site.bench, site.name, "bench update + migrate (demo)" + (", migrate failed" if failed else ""), at)

	def bench_failure(self, at, bench):
		"""A patch that does not apply during `bench update`."""
		self.logs.write(
			self.bench_path(bench, "logs", "bench.log"),
			core.traceback_lines(
				at, "bench update failed",
				[("bench/utils/__init__.py", 82, "exec_cmd", "raise CommandFailedError(cmd)")],
				"subprocess.CalledProcessError: Command 'git -C apps/erpnext apply /tmp/fix-stock-ledger.patch' returned non-zero exit status 1.",
			),
		)

	def _mark(self, bench, site, note, at):
		if not self.mark_deployment:
			return
		try:
			self.mark_deployment(bench, site, note, at)
		except Exception as e:
			log.warning("could not mark the deployment of %s at %s: %s", site, core.utc_iso(at), e)
