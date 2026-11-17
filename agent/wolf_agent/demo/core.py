"""Building blocks shared by the demos: log line formats, traffic, file writers, the agent's state."""

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

from .. import __version__
from ..shipper import MAX_METRICS, Spool
from ..util import metric, utc_iso

MINUTE = timedelta(minutes=1)

# Clients come from 100.64.0.0/10 (shared address space): not routable on the Internet, yet not
# "private" to Python's ipaddress, so the agent treats them as the public clients they stand for.
# Documentation ranges (192.0.2.0/24...) are private to it and would be skipped behind the proxy.
USERS_NET = "100.64.{}.{}"
ATTACKERS = ["100.100.7.13", "100.101.66.4", "100.102.3.250", "100.103.140.9"]

USER_AGENTS = [
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
	"Frappe Mobile/3.2 (Android 14)",
	"python-requests/2.32.3",
]
SCANNER_AGENTS = ["Mozilla/5.0 zgrab/0.x", "Nuclei - Open-source project (github.com/projectdiscovery/nuclei)"]

# (method, path, weight); /api/method/erpnext.stock... is the route that fails now and then
ROUTES = [
	("GET", "/app/home", 8),
	("GET", "/api/method/frappe.desk.form.load.getdoc", 10),
	("POST", "/api/method/frappe.desk.reportview.get", 8),
	("GET", "/assets/frappe/dist/js/desk.bundle.js", 6),
	("GET", "/api/method/frappe.realtime.get_user_info", 5),
	("POST", "/api/method/run_doc_method", 4),
	("GET", "/api/method/erpnext.stock.utils.get_stock_balance", 3),
	("GET", "/login", 2),
	("POST", "/api/method/login", 1),
]
FLAKY_ROUTE = "/api/method/erpnext.stock.utils.get_stock_balance"
# what scanners ask every public site for (secrets, CMS panels, traversal)
PROBES = [
	"/.env", "/wp-login.php", "/.git/config", "/phpmyadmin/index.php", "/.aws/credentials",
	"/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php", "/xmlrpc.php", "/../../../../etc/passwd",
	"/wp-admin/setup-config.php", "/.DS_Store", "/config.php.bak", "/server-status",
]  # fmt: skip


def local(at):
	"""Naive local time, as Python logging, syslog and peewee write it."""
	return at.astimezone().replace(tzinfo=None)


def floor_minute(at):
	return at.replace(second=0, microsecond=0)


# --- log line formats -------------------------------------------------------------------------


def nginx_main(at, host, client, method, path, status, user_agent, proxy="10.0.0.2", size=None, took=0.05):
	"""Press's nginx `main` format (docs/press.md): the client is in X-Forwarded-For, the site in $host."""
	stamp = at.astimezone().strftime("%d/%b/%Y:%H:%M:%S %z")
	size = 157 if status == 502 else (size if size is not None else 1800)
	return (
		f'{proxy} - - [{stamp}] "{method} {path} HTTP/1.1" {status} {size} "-" "{user_agent}" '
		f'"{client}" "{host}" {took:.3f}'
	)


def pylog(at, level, logger, message):
	"""Python logging's default Frappe format: `2026-10-29 02:00:13,123 ERROR frappe message`."""
	t = local(at)
	return f"{t:%Y-%m-%d %H:%M:%S},{t.microsecond // 1000:03d} {level} {logger} {message}"


def syslog(at, host, ident, pid, message):
	"""auth.log: `Nov  7 02:00:01 host sshd[1001]: message`."""
	t = local(at)
	return f"{t:%b} {t.day:2d} {t:%H:%M:%S} {host} {ident}[{pid}]: {message}"


def traceback_lines(at, message, frames, exc):
	"""A Frappe request traceback as frappe.web.log has it, for the traceback parser."""
	lines = [pylog(at, "ERROR", "frappe", message), "Traceback (most recent call last):"]
	for path, line, func, code in frames:
		lines += [f'  File "{path}", line {line}, in {func}', f"    {code}"]
	return [*lines, exc]


# --- traffic ----------------------------------------------------------------------------------


class Site:
	def __init__(self, name, bench, rate, domains=()):
		self.name = name
		self.bench = bench
		self.rate = rate  # requests per minute at the busiest hour
		self.domains = list(domains)
		self.clients = []


def diurnal(at):
	"""Share of the peak rate: 0.25 at night, 1.0 mid-afternoon (server local time)."""
	t = at.astimezone()
	hour = t.hour + t.minute / 60
	return 0.25 + 0.75 * max(0.0, math.sin(math.pi * (hour - 6) / 16))


def _count(rng, expected):
	whole = int(expected)
	return whole + (1 if rng.random() < expected - whole else 0)


def _pick_route(rng):
	total = sum(w for *_, w in ROUTES)
	x = rng.uniform(0, total)
	for method, path, weight in ROUTES:
		x -= weight
		if x <= 0:
			return method, path
	return ROUTES[-1][:2]


def _client(rng, site):
	if not site.clients:
		seed = sum(map(ord, site.name))
		site.clients = [USERS_NET.format(64 + (seed + i) % 60, (seed * 7 + i * 13) % 250 + 2) for i in range(25)]
	return rng.choice(site.clients)


def requests(rng, site, start, end, outage=None):
	"""nginx lines for `site` in [start, end). `outage` is the share of requests answered 502
	(the backend is down); clients retry then, so traffic does not drop below 6 a minute."""
	minutes = (end - start).total_seconds() / 60
	rate = site.rate * diurnal(start)
	if outage:
		rate = max(rate, 6.0)
	lines = []
	for _ in range(_count(rng, rate * minutes)):
		at = start + timedelta(seconds=rng.uniform(0, minutes * 60))
		method, path = _pick_route(rng)
		if outage and rng.random() < outage:
			status = 502
		elif path.startswith("/assets/"):
			status = 304 if rng.random() < 0.7 else 200
		elif path == FLAKY_ROUTE and rng.random() < 0.004:
			status = 500
		elif rng.random() < 0.01:
			status = 404
		else:
			status = 200
		host = rng.choice(site.domains) if site.domains and rng.random() < 0.3 else site.name
		took = rng.uniform(0.02, 0.4) if status != 502 else 0.001
		lines.append((at, nginx_main(at, host, _client(rng, site), method, path, status, rng.choice(USER_AGENTS), took=took)))
	return lines


def web_scan(rng, site, start, minutes, count, attacker):
	"""`count` probes from one scanner over `minutes`: what the Web attack scan preset catches."""
	ua = rng.choice(SCANNER_AGENTS)
	out = []
	for i in range(count):
		at = start + timedelta(seconds=minutes * 60 * i / count)
		path = PROBES[i % len(PROBES)]
		status = 404 if rng.random() < 0.9 else 403
		out.append((at, nginx_main(at, site.name, attacker, "GET", path, status, ua, size=146, took=0.002)))
	return out


# --- files ------------------------------------------------------------------------------------


def touch(path):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "a"):
		pass


class Logs:
	"""Append-only writers, one handle per file, flushed together so the agent reads whole lines."""

	def __init__(self):
		self.handles = {}

	def write(self, path, lines):
		if not lines:
			return
		fh = self.handles.get(path)
		if fh is None:
			fh = self.handles[path] = open(path, "a", encoding="utf-8")
		fh.write("".join(line + "\n" for line in lines))

	def flush(self):
		for fh in self.handles.values():
			fh.flush()

	def close(self):
		for fh in self.handles.values():
			fh.close()
		self.handles = {}


def read_json(path, default=None):
	try:
		with open(path) as f:
			return json.load(f)
	except (OSError, ValueError):
		return default


def write_json(path, data):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	tmp = path + ".tmp"
	with open(tmp, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)
		f.write("\n")
	os.replace(tmp, path)


# --- the running agent ------------------------------------------------------------------------


def wait_for_agent(spool_dir, paths, ready=lambda: True, timeout=300, sleep=time.sleep, clock=time.monotonic):
	"""Block until the agent tracks every path in `paths` (its tail state has them) and `ready()`.

	Files the agent opens while they are empty are read from their start, so history appended
	afterwards goes through its parsers. Appended before, it would be skipped as old content.
	"""
	state_path = os.path.join(spool_dir, "tail-state.json")
	deadline = clock() + timeout
	while True:
		tracked = read_json(state_path, {}) or {}
		missing = [p for p in paths if p not in tracked]
		if not missing and ready():
			return
		if clock() > deadline:
			what = f"{len(missing)} file(s), e.g. {missing[0]}" if missing else "its Press job history"
			raise TimeoutError(f"the agent (state in {spool_dir}) does not track {what} after {timeout}s")
		sleep(2)


# --- host metrics history ---------------------------------------------------------------------


def host_metrics(rng, host, at, busy=0.0, disk=62.0):
	"""What HostMetrics samples from /proc, for one minute in the past. `busy` (0..1) adds load."""
	day = diurnal(at)
	cpu = min(99.0, 6 + 22 * day + 55 * busy + rng.gauss(0, 3))
	load1 = max(0.05, 0.3 + 2.2 * day + 5 * busy + rng.gauss(0, 0.2))
	ts = utc_iso(at)
	values = {
		"cpu_usage": round(max(0.5, cpu), 2),
		"memory_used_percent": round(58 + 9 * day + 12 * busy + rng.gauss(0, 1), 2),
		"swap_used_percent": round(3 + rng.gauss(0, 0.3), 2),
		"load_1m": round(load1, 2),
		"load_5m": round(load1 * 0.85, 2),
		"load_15m": round(load1 * 0.7, 2),
		"load_per_core": round(load1 / 4, 3),
	}
	out = [metric(name, value, ts, host) for name, value in values.items()]
	out.append(metric("disk_used_percent", round(disk, 2), ts, host, labels={"mount": "/"}))
	return out


def spool_host_history(spool_dir, host, samples):
	"""Hand past host metrics to the agent's outbox: its shipper sends them with its next push,
	signed like everything else. Batches stay under the size the shipper sends at once."""
	spool = Spool(os.path.join(spool_dir, "outbox"))
	batch = []
	for sample in samples:
		batch.append(sample)
		if len(batch) >= MAX_METRICS:
			spool.put(_body(host, batch))
			batch = []
	if batch:
		spool.put(_body(host, batch))


def _body(host, metrics):
	return {
		"sent_at": utc_iso(datetime.now(timezone.utc)),
		"agent_version": __version__,
		"hostname": host,
		"metrics": metrics,
		"events": [],
	}
