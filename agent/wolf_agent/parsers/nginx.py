"""nginx access log parser: per-site request/5xx/502 counters plus aggregated 5xx events.

Counts and aggregates are kept per minute of the log line's own time, not of the time the
agent reads it: a backlog read after a restart, a rotation or a spool replay lands in the
minutes it happened, not as one spike at read time.
"""

import ipaddress
import os
import re
from datetime import datetime, timedelta

from ..util import event, fingerprint, log_minute, metric, utc_iso
from . import web_attacks

# combined / common, optionally prefixed by `$host` (vhost_combined style) and
# followed by extra quoted fields such as `"$http_x_forwarded_for"` or `"$host"`.
_LINE_RE = re.compile(
	r"^(?:(?P<vhost>\S+)\s+)?(?P<addr>\S+) \S+ (?P<user>\S+) \[(?P<time>[^\]]+)\] "
	r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\S+)'
	r'(?: "(?P<referer>[^"]*)" "(?P<agent>[^"]*)")?(?P<rest>.*)$'
)
# Frappe Pilot's `pilot_access` format (pilot/managers/nginx/templates/server.conf.template):
# '$pilot_client_addr [$time_local] "$request_method $uri" $status "$host" $request_time'
_PILOT_RE = re.compile(
	r'^(?P<addr>\S+) \[(?P<time>[^\]]+)\] "(?P<request>[^"]*)" (?P<status>\d{3}) "(?P<host>[^"]*)"(?P<rest>.*)$'
)
_QUOTED_RE = re.compile(r'"([^"]*)"')
CRITICAL_STATUSES = {502, 503, 504}
MAX_SAMPLES = 3
# distinct (site, client) probe groups kept per interval: a distributed scan cannot grow memory
MAX_PROBE_GROUPS = 500
MAX_RATE_CLIENTS = 5000  # (site, client) pairs whose Frappe rate counters are kept


def parse_line(line):
	"""Parse one access log line into a dict, or None if it isn't one."""
	m = _LINE_RE.match(line.strip())
	if not m:
		m = _PILOT_RE.match(line.strip())
		if not m:
			return None
	parts = m.group("request").split()
	if len(parts) >= 2:
		method, target = parts[0], parts[1]
	else:
		method, target = "-", m.group("request") or "-"
	try:
		ts = utc_iso(datetime.strptime(m.group("time"), "%d/%b/%Y:%H:%M:%S %z"))
	except ValueError:
		ts = None
	vhost = m.groupdict().get("vhost") or m.groupdict().get("host")
	if vhost:
		vhost = vhost.split(":", 1)[0]
	return {
		"vhost": vhost,
		"remote_addr": m.group("addr"),
		"timestamp": ts,
		"method": method,
		"route": target.split("?", 1)[0],
		"target": target[: web_attacks.MAX_TARGET],
		"status": int(m.group("status")),
		"user_agent": m.groupdict().get("agent"),
		"extra": _QUOTED_RE.findall(m.group("rest") or ""),
	}


def _ip(value):
	try:
		return ipaddress.ip_address((value or "").strip())
	except ValueError:
		return None


def client_address(parsed):
	"""The client of a request: `$remote_addr`, or, when `$remote_addr` is a loopback/private
	proxy, the right-most public address of the X-Forwarded-For list logged after it.

	Each proxy appends the address it received the request from, so the right-most entries
	come from your proxies and the left-most from the client, who can write anything there.
	Walking from the right and skipping private hops gives the first address no client could
	forge. A public `$remote_addr` is never replaced."""
	remote = parsed["remote_addr"]
	addr = _ip(remote)
	if addr is None or not (addr.is_loopback or addr.is_private):
		return remote
	for value in parsed["extra"]:
		hops = [_ip(h) for h in value.split(",")]
		if not hops or any(h is None for h in hops):
			continue  # not an address list (a referer, a host name)
		for hop in reversed(hops):
			if not (hop.is_loopback or hop.is_unspecified or hop.is_private or hop.is_link_local):
				return str(hop)
		return remote  # only private hops: an internal client
	return remote


class NginxParser:
	"""Counts requests per site and aggregates 5xx responses per (site, status, route).

	`site_benches` maps known site names to their bench; the site of a line is
	taken from `$host` when logged (custom domains resolved through
	`site_aliases`, domain → site), else from a per-site log file name, else
	`default_site` (a bench serving a single site).
	"""

	def __init__(self, host, site_benches=None, default_site=None, default_bench=None, log_file=None, site_aliases=None, **_):
		self.host = host
		self.site_benches = dict(site_benches or {})
		self.site_aliases = dict(site_aliases or {})
		self.default_site = default_site
		self.default_bench = default_bench
		self.log_file = log_file
		self.file_site = self._site_from_path(log_file)
		self.rates = {}  # (site, client) -> {minute: {rate rule: [requests, paths]}}, kept across drains
		self._reset()

	def _reset(self):
		self.counts = {}  # (minute, site) -> [requests, 5xx, 502, newest line timestamp]
		self.errors = {}  # (minute, site, status, method, route) -> aggregate
		self.probes = {}  # (minute, site, client, exposed) -> aggregate

	def _site_from_path(self, path):
		if not path:
			return None
		name = os.path.basename(path)
		for site in sorted(self.site_benches, key=len, reverse=True):
			if site in name:
				return site
		return None

	def resolve_site(self, parsed):
		candidates = [parsed["vhost"], *parsed["extra"]]
		for c in candidates:
			if c and c in self.site_benches:
				return c
		for c in candidates:
			if c and self.site_aliases.get(c) in self.site_benches:
				return self.site_aliases[c]
		if self.file_site:
			return self.file_site
		if self.default_site:
			return self.default_site
		# unknown vhost: still report it so a missing site mapping is visible
		return parsed["vhost"] if parsed["vhost"] and parsed["vhost"] not in ("-", "_") else None

	def bench_for(self, site):
		return self.site_benches.get(site, self.default_bench)

	def feed(self, line):
		parsed = parse_line(line)
		if not parsed:
			return
		site = self.resolve_site(parsed)
		minute = log_minute(parsed["timestamp"])
		counts = self.counts.setdefault((minute, site), [0, 0, 0, None])
		counts[0] += 1
		if parsed["timestamp"] and (counts[3] is None or parsed["timestamp"] > counts[3]):
			counts[3] = parsed["timestamp"]
		status = parsed["status"]
		self._probe(minute, site, parsed, line)
		if status < 500:
			return
		counts[1] += 1
		if status == 502:
			counts[2] += 1
		key = (minute, site, status, parsed["method"], parsed["route"])
		err = self.errors.get(key)
		if not err:
			err = self.errors[key] = {"count": 0, "timestamp": parsed["timestamp"], "samples": []}
		err["count"] += 1
		if len(err["samples"]) < MAX_SAMPLES:
			err["samples"].append(line.strip()[:1000])

	def _rate(self, minute, site, client, rules, target):
		"""{rate rule: requests} for the rate rules this client crossed over the last
		RATE_WINDOW minutes, counting this request. Lone requests never make a probe group."""
		buckets = self.rates.pop((site, client), {})
		self.rates[(site, client)] = buckets  # most recent last: the oldest client is dropped first
		path = (target or "").split("?", 1)[0]
		bucket = buckets.setdefault(minute, {})
		for rule in rules:
			count = bucket.setdefault(rule, [0, set()])
			count[0] += 1
			if len(count[1]) < 50:
				count[1].add(path)
		window = _window(minute)
		for old in [m for m in buckets if m not in window and (m or "") < (minute or "")]:
			del buckets[old]
		while len(self.rates) > MAX_RATE_CLIENTS:
			del self.rates[next(iter(self.rates))]
		crossed = {}
		for rule in rules:
			requests = sum(buckets[m][rule][0] for m in window if m in buckets and rule in buckets[m])
			paths = set().union(*(buckets[m][rule][1] for m in window if m in buckets and rule in buckets[m]))
			need, distinct = web_attacks.RATE_RULES[rule]
			if requests >= need and len(paths) >= distinct:
				crossed[rule] = requests
		return crossed

	def _probe(self, minute, site, parsed, line):
		rules = web_attacks.classify(parsed["method"], parsed["target"], parsed["status"], parsed["user_agent"])
		if not rules:
			return
		client = client_address(parsed)
		rate = [r for r in rules if r in web_attacks.RATE_RULES]
		crossed = self._rate(minute, site, client, rate, parsed["target"]) if rate else {}
		key = (minute, site, client, web_attacks.exposed(rules, parsed["status"], parsed["target"]))
		g = self.probes.get(key)
		if len(rate) == len(rules) and not crossed and g is None:
			return  # a password reset, one forbidden call: not a probe until the client keeps at it
		if g is None:
			if len(self.probes) >= MAX_PROBE_GROUPS:
				return
			g = self.probes[key] = {
				"count": 0, "timestamp": parsed["timestamp"], "rules": {}, "statuses": {},
				"targets": [], "user_agents": [], "samples": [],
			}  # fmt: skip
			if crossed:  # the requests of the window that led here
				for rule, requests in crossed.items():
					g["rules"][rule] = requests - 1
				g["count"] = max(crossed.values()) - 1
		g["count"] += 1
		for rule in rules:
			g["rules"][rule] = g["rules"].get(rule, 0) + 1
		status = str(parsed["status"])
		g["statuses"][status] = g["statuses"].get(status, 0) + 1
		if parsed["target"] not in g["targets"] and len(g["targets"]) < 10:
			g["targets"].append(parsed["target"])
		ua = (parsed["user_agent"] or "")[:200]
		if ua and ua not in g["user_agents"] and len(g["user_agents"]) < 3:
			g["user_agents"].append(ua)
		if len(g["samples"]) < MAX_SAMPLES:
			g["samples"].append(line.strip()[:1000])

	def _probe_events(self, ts):
		events = []
		for (_, site, client, is_exposed), g in self.probes.items():
			rules = sorted(g["rules"], key=lambda r: (-g["rules"][r], r))
			if is_exposed:
				category = "web_sensitive_file_exposed"
				severity = "critical"
				title = f"Sensitive file served to {client}: {g['targets'][0]}"
			else:
				category = "web_attack_probe"
				severity = "critical" if g["count"] >= web_attacks.CRITICAL_THRESHOLD else "warning"
				title = f"{g['count']} web attack probe(s) from {client} ({', '.join(rules[:3])})"
			events.append(
				event(
					"security",
					category,
					severity,
					g["timestamp"] or ts,
					self.host,
					title[:140],
					fingerprint(site, category, client),
					{
						"ip": client,
						"count": g["count"],
						"rules": g["rules"],
						"attack_techniques": sorted(
							{web_attacks.ATTACK_TECHNIQUES[r] for r in rules if r in web_attacks.ATTACK_TECHNIQUES}
						),
						"statuses": g["statuses"],
						"targets": g["targets"],
						"user_agents": g["user_agents"],
						"sample_lines": g["samples"],
						"log_file": self.log_file,
					},
					source="nginx",
					bench=self.bench_for(site),
					site=site,
				)
			)
		return events

	def drain(self, now=None):
		ts = utc_iso(now)
		metrics, events = [], []
		# one sample per minute with traffic, stamped with its newest line; a known site with
		# no traffic in this interval still reports zeros, stamped now
		buckets = dict(self.counts)
		quiet = set(self.site_benches) | ({self.default_site} if self.default_site else set())
		quiet -= {site for _, site in buckets}
		for site in quiet:
			buckets[(None, site)] = [0, 0, 0, None]
		for (_, site), (requests, e5xx, e502, newest) in sorted(
			buckets.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")
		):
			bench = self.bench_for(site)
			at = newest or ts
			metrics.append(metric("http_requests", requests, at, self.host, bench, site))
			metrics.append(metric("http_5xx", e5xx, at, self.host, bench, site))
			metrics.append(metric("http_502", e502, at, self.host, bench, site))

		for (_, site, status, method, route), err in self.errors.items():
			events.append(
				event(
					"error",
					"http_502" if status == 502 else "http_5xx",
					"critical" if status in CRITICAL_STATUSES else "warning",
					err["timestamp"] or ts,
					self.host,
					f"{status} on {method} {route}"[:140],
					fingerprint(site, status, method, route),
					{
						"route": route,
						"method": method,
						"status": status,
						"count": err["count"],
						"sample_lines": err["samples"],
						"log_file": self.log_file,
					},
					source="nginx",
					bench=self.bench_for(site),
					site=site,
				)
			)
		events.extend(self._probe_events(ts))
		self._reset()
		return metrics, events


def _window(minute):
	"""The minutes a rate counts over: this one and the RATE_WINDOW - 1 before it."""
	if not minute:
		return [minute]
	try:
		at = datetime.strptime(minute, "%Y-%m-%dT%H:%M")
	except ValueError:
		return [minute]
	return [(at - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M") for i in range(web_attacks.RATE_WINDOW)]
