"""A simulated server: its sites, the incident storyline, history, then live traffic.

Subclasses (press.PressDemo, bench.BenchDemo) lay out the files the agent reads on their
platform and say how a deployment and a bench-level failure look there. Everything else, from
the traffic to the SSH brute force, is the same on every platform.
"""

import logging
import random
import time
from datetime import datetime, timedelta, timezone

from ..util import utc_iso
from . import core
from .core import MINUTE, Site

log = logging.getLogger(__name__)

STORY_MINUTES = 25  # the storyline runs from 0' to 24'
DAILY_STORY = (10, 30)  # local time of the storyline on each day of history
NIGHTLY_CRON = (2, 10)  # and of the nightly job that fails
CRON_METHODS = [
	"erpnext.accounts.doctype.process_deferred_accounting.process_deferred_accounting.process_deferred_accounting",
	"erpnext.stock.reorder_item.reorder_item",
	"erpnext.setup.doctype.email_digest.email_digest.send",
	"hrms.hr.utils.allocate_earned_leaves",
]


class DemoServer:
	"""`benches`: {bench: [(site, peak requests/minute, custom domains)]}."""

	kind = None
	nginx_line = staticmethod(core.nginx_main)

	def __init__(self, root, host, benches, spool_dir=None, rng=None):
		self.root = root
		self.host = host
		self.benches = benches
		self.spool_dir = spool_dir
		self.rng = rng or random.Random()
		self.state_path = f"{root}/demo-state.json"
		self.sites = [Site(name, bench, rate, domains) for bench, sites in benches.items() for name, rate, domains in sites]
		self.logs = core.Logs()
		self.disk = 61.0

	# --- what a platform provides ---------------------------------------------------------

	def layout(self):
		"""Create the files the agent reads, empty (idempotent)."""
		raise NotImplementedError

	def tracked_paths(self):
		"""Every file the agent tails, as it names them."""
		raise NotImplementedError

	def agent_overrides(self):
		"""Agent config keys that point it at this layout."""
		raise NotImplementedError

	def ready(self):
		"""Anything besides the tailed files the agent must have read before history is written."""
		return True

	def deploy(self, at, site, failed=False):
		"""A deployment (update + migrate) of `site` starting at `at`."""
		raise NotImplementedError

	def bench_failure(self, at, bench):
		"""A bench-level operation that fails (a patch, an update)."""
		raise NotImplementedError

	# --- the storyline --------------------------------------------------------------------

	def storyline(self, t0, n):
		"""(actions, outages) of one incident cycle starting at `t0`; `n` rotates sites.

		0'  a deployment of one site, whose backend then answers 502 for 4 minutes
		6'  a request traceback on another site
		8'  a scheduled job fails
		11' a background worker is killed (OOM)
		14' an SSH brute force on the server; every third cycle it succeeds
		19' a web attack scan of a site
		24' every other cycle, a bench operation fails
		"""
		sites = self.sites
		target = sites[(n * 3) % len(sites)]
		other = sites[(n * 3 + 1) % len(sites)]
		third = sites[(n * 3 + 2) % len(sites)]
		attacker = core.ATTACKERS[n % len(core.ATTACKERS)]
		at = lambda minutes: t0 + timedelta(minutes=minutes)  # noqa: E731
		actions = [
			(at(0), lambda: self.deploy(at(0), target, failed=n % 4 == 3)),
			(at(6), lambda: self.web_traceback(at(6), other)),
			(at(8), lambda: self.cron_failure(at(8), third, CRON_METHODS[n % len(CRON_METHODS)])),
			(at(11), lambda: self.worker_crash(at(11), target.bench)),
			(at(14), lambda: self.ssh_brute_force(at(14), attacker, succeed=n % 3 == 2)),
			(at(19), lambda: self.write_nginx(core.web_scan(self.rng, other, at(19), 4, 140, attacker, self.nginx_line))),
		]
		if n % 2:
			actions.append((at(24), lambda: self.bench_failure(at(24), target.bench)))
		outages = [(target.name, at(0) + timedelta(seconds=20), at(4), 0.8)]
		return actions, outages

	def nightly(self, t0, n):
		site = self.sites[(n * 5) % len(self.sites)]
		return [(t0, lambda: self.cron_failure(t0, site, CRON_METHODS[0]))], []

	def bench_path(self, bench, *parts):
		raise NotImplementedError

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
				lines += core.requests(self.rng, site, minute, upto, outage=down, line=self.nginx_line)
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
		log.info("demo %s server %s laid out in %s; waiting for the agent to track it", self.kind, self.host, self.root)
		core.wait_for_agent(self.spool_dir, self.tracked_paths(), self.ready, timeout=timeout)
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
