"""What each metric means, and the state of one signal series (no frappe imports).

The catalog names every metric the agent sends that a dashboard shows: its unit, its kind and
how often it arrives. `kind` decides how it may be read:

- gauge: a level now (disk used, backup age); the latest value is meaningful;
- interval_count: events counted per push interval (5xx responses, failed jobs added); sum
  them over a window, never read one sample as "the count".

`state` keeps apart what a dashboard must not merge: no data at all, data that stopped, a
value no rule watches, a value its rules accept, and a value a rule has opened an incident for.
"""

from datetime import timedelta

from dodock_wolf.wolf.i18n import N_, _, fmt, translate


# Default agent cadences. An agent configured with a longer `tls.interval` or
# `backups.interval` will look stale sooner than it is: the server does not know the setting.
PUSH_SECONDS = 30
MIN_STALE = timedelta(minutes=5)

# metric -> (group, label, kind, unit, level, cadence seconds)
_SPEC = [
	("http_requests", "http", N_("Requests"), "interval_count", N_("requests"), "site", PUSH_SECONDS),
	("http_5xx", "http", N_("5xx responses"), "interval_count", N_("responses"), "site", PUSH_SECONDS),
	# a subset of 5xx: never added to it
	("http_502", "http", N_("502 responses (part of 5xx)"), "interval_count", N_("responses"), "site", PUSH_SECONDS),
	("rq_workers", "workers", N_("RQ workers"), "gauge", N_("workers"), "bench", PUSH_SECONDS),
	("queue_length", "workers", N_("Queue length"), "gauge", N_("jobs"), "bench", PUSH_SECONDS),
	("rq_failed_jobs_added", "workers", N_("Failed jobs added"), "interval_count", N_("jobs"), "bench", PUSH_SECONDS),
	# jobs held in RQ's failed registry now (they expire): not the number that failed lately
	("rq_failed_jobs", "workers", N_("Jobs in the failed registry"), "gauge", N_("jobs"), "bench", PUSH_SECONDS),
	("rq_long_running_jobs", "workers", N_("Long-running jobs"), "gauge", N_("jobs"), "bench", PUSH_SECONDS),
	("bench_processes_down", "processes", N_("Bench processes down"), "gauge", N_("processes"), "bench", PUSH_SECONDS),
	("redis_used_memory_percent", "redis", N_("Redis memory used"), "gauge", "%", "bench", PUSH_SECONDS),
	("redis_evicted_keys", "redis", N_("Redis evicted keys"), "interval_count", N_("keys"), "bench", PUSH_SECONDS),
	("db_connections_used_percent", "database", N_("Database connections used"), "gauge", "%", "bench", PUSH_SECONDS),
	("db_threads_connected", "database", N_("Database connections"), "gauge", N_("connections"), "bench", PUSH_SECONDS),
	("db_slow_queries", "database", N_("Slow queries"), "interval_count", N_("queries"), "bench", PUSH_SECONDS),
	("db_replication_running", "database", N_("Replication running"), "gauge", N_("1 = yes"), "bench", PUSH_SECONDS),
	("db_replication_lag_seconds", "database", N_("Replication lag"), "gauge", "s", "bench", PUSH_SECONDS),
	("backup_age_hours", "backups", N_("Newest backup age"), "gauge", "h", "site", 600),
	("tls_days_left", "tls", N_("Certificate expires in"), "gauge", N_("days"), "site", 3600),
	("hsts_max_age_days", "tls", N_("HSTS max-age"), "gauge", N_("days"), "site", 3600),
	("agent_setup_failed", "host", N_("Agent setup checks failed"), "gauge", "", "host", 3600),
	("agent_setup_warnings", "host", N_("Agent setup warnings"), "gauge", "", "host", 3600),
	("cpu_usage", "host", N_("CPU"), "gauge", "%", "host", PUSH_SECONDS),
	("memory_used_percent", "host", N_("Memory used"), "gauge", "%", "host", PUSH_SECONDS),
	("disk_used_percent", "host", N_("Disk used"), "gauge", "%", "host", PUSH_SECONDS),
	("load_per_core", "host", N_("Load per core"), "gauge", N_("per core"), "host", PUSH_SECONDS),
	("load_1m", "host", N_("Load (1 min)"), "gauge", "", "host", PUSH_SECONDS),
	("load_5m", "host", N_("Load (5 min)"), "gauge", "", "host", PUSH_SECONDS),
	("load_15m", "host", N_("Load (15 min)"), "gauge", "", "host", PUSH_SECONDS),
	("swap_used_percent", "host", N_("Swap used"), "gauge", "%", "host", PUSH_SECONDS),
	("exposed_services", "security", N_("Bench services listening beyond loopback"), "gauge", N_("services"), "host", 600),
	("site_config_risks", "security", N_("Risky site_config settings"), "gauge", N_("settings"), "site", 600),
	("integrity_files", "security", N_("Files under integrity watch"), "gauge", N_("files"), "bench", 900),
	("integrity_unreadable", "security", N_("Files the integrity check cannot read"), "gauge", N_("files"), "bench", 900),
	("bench_outbound_destinations", "security", N_("Outbound destinations of the bench user"), "gauge", N_("destinations"), "bench", 60),
	("bench_new_outbound_usual", "security", N_("New outbound destinations on usual ports"), "gauge", N_("destinations"), "bench", 60),
	("security_score", "security", N_("Security score"), "gauge", "/ 100", "site", 3600),
	("site_setting", "security", N_("System Settings value"), "gauge", "", "site", 3600),
	# major * 1e6 + minor * 1e3 + patch: a step on the chart is an upgrade
	("app_version", "security", N_("App version"), "gauge", N_("version"), "bench", 3600),
]
CATALOG = {
	m: {"metric": m, "group": g, "label": label, "kind": kind, "unit": unit, "level": level, "cadence_seconds": cadence}
	for m, g, label, kind, unit, level, cadence in _SPEC
}
GROUPS = ("workers", "processes", "redis", "database", "backups", "tls", "security", "host")

# what a gauge means for the reader, said once: backup age is not proof a restore works
CAVEATS = {
	"backup_age_hours": N_("Age of the newest backup file; it does not prove the backup restores."),
	"agent_setup_failed": N_("From the agent's hourly wolf-agent doctor run; Monitoring lists what failed and the fix."),
	"tls_days_left": N_("Days until the certificate served on port 443 expires; not a full validity check."),
	"app_version": N_("Version of each app in the bench (apps/<app>/<app>/__init__.py) as major * 1e6 + minor * 1e3 + patch: 15100000 is 15.100.0; development versions are not sent."),
	"hsts_max_age_days": N_("Strict-Transport-Security max-age of the first response to HEAD / (0: no header); redirects are not followed."),
	"site_setting": N_("A System Settings value as stored in the site's database (unset: 0); system_manager_2fa is the System Manager role's two-factor flag."),
	"exposed_services": N_("A listening socket, not proof of reachability: a firewall may still block it."),
	"integrity_files": N_("Files whose content the agent checks: app code, site configs, nginx and supervisor config."),
	"security_score": N_("Share of the checks Wolf could prove passed; a check it cannot read counts as not passed."),
}


def shown(spec):
	"""A catalog entry with its label and unit in the reader's language (a copy: CATALOG stays English).
	A custom metric's label is its name: left as it is."""
	if spec.get("metric") not in CATALOG:
		return dict(spec)
	return {**spec, "label": translate(spec["label"]), "unit": translate(spec["unit"])}


def caveats():
	"""CAVEATS in the reader's language."""
	return {metric: translate(text) for metric, text in CAVEATS.items()}


def stale_after(metric):
	"""How long without a sample before a series counts as stale: three cadences, at least 5 min."""
	cadence = CATALOG.get(metric, {}).get("cadence_seconds", PUSH_SECONDS)
	return max(timedelta(seconds=3 * cadence), MIN_STALE)


def rule_applies(rule, series):
	"""A rule watches a series when it is on its metric and its scope filters match."""
	if rule.get("metric_name") != series.get("metric_name"):
		return False
	return all(not rule.get(f"filter_{k}") or rule.get(f"filter_{k}") == series.get(k) for k in ("host", "bench", "site"))


def incident_matches(incident, series):
	"""An open incident is about a series when every scope field it names is the series'.

	A rule grouped by label (host_label) opens one incident per label: its group_key ends with
	"label_key=<label>", and only that series is concerned, not every disk or queue of the host.
	"""
	if not all(not incident.get(k) or incident.get(k) == series.get(k) for k in ("host", "bench", "site")):
		return False
	key = incident.get("group_key") or ""
	return "label_key=" not in key or key.endswith(f"label_key={series.get('label_key') or '-'}")


def is_stale(series, now):
	"""Samples stopped: none for `stale_after`, or none in the recent read (`recent` False)."""
	return series.get("recent") is False or now - series["last_at"] > stale_after(series["metric_name"])


def state(series, now, rules=(), incidents=()):
	"""The state of one series: last sample (`last_at`, may be None), rules and open incidents.

	- missing: no sample in the lookback (not collected here, not configured, or unsupported);
	- firing: a rule on it has an open incident for this scope, whether or not samples still
	  arrive (a host that went silent mid-incident stays on top; see is_stale for the rest);
	- stale: samples stopped arriving;
	- watched: rules apply and none has an open incident;
	- unwatched: a value, but no rule on it (the dashboard does not invent a threshold).
	"""
	if series.get("last_at") is None:
		return "missing"
	applicable = [r for r in rules if rule_applies(r, series)]
	names = {r["name"] for r in applicable}
	if any(i.get("alert_rule") in names and incident_matches(i, series) for i in incidents):
		return "firing"
	if is_stale(series, now):
		return "stale"
	return "watched" if applicable else "unwatched"


# --- exploring a metric ---------------------------------------------------------------------

# the label each metric carries (one per series), for filtering and grouping
LABELS = {
	"disk_used_percent": "mount", "queue_length": "queue", "rq_failed_jobs": "queue",
	"rq_failed_jobs_added": "queue", "rq_long_running_jobs": "queue", "tls_days_left": "domain", "hsts_max_age_days": "domain",
	"bench_processes_down": "manager", "redis_used_memory_percent": "of",
	"db_connections_used_percent": "db", "db_threads_connected": "db", "db_slow_queries": "db", "db_replication_running": "db",
	"db_replication_lag_seconds": "db", "app_version": "app", "site_setting": "setting",
}  # fmt: skip

# what a bucket may say about each kind. A gauge is a level: its average, extremes or last value
# over the bucket. An interval count is a number of things per push: summed over the bucket it
# is the total, its average or maximum is per push interval.
AGGREGATIONS = {
	"gauge": ("avg", "min", "max", "last"),
	"interval_count": ("sum", "avg", "max"),
	"unknown": ("avg", "min", "max", "last"),  # a custom metric: read it as a level
}
DEFAULT_AGGREGATION = {"gauge": "avg", "interval_count": "sum", "unknown": "avg"}

# grouping a metric only by what its series carry: a host-level metric has no bench or site
GROUP_BYS = {
	"host": ("none", "host"),
	"bench": ("none", "host", "bench"),
	"site": ("none", "host", "bench", "site"),
	# a custom metric may carry labels the catalog cannot name: it may be split by them
	"unknown": ("none", "host", "bench", "site", "host_label"),
}


def describe(metric):
	"""What the explorer may do with a metric: catalog fields, aggregations, groupings, label."""
	spec = CATALOG.get(metric) or {
		"metric": metric, "group": "custom", "label": metric, "kind": "unknown", "unit": "",
		"level": "unknown", "cadence_seconds": PUSH_SECONDS,
	}  # fmt: skip
	label = LABELS.get(metric) or ("label" if spec["kind"] == "unknown" else None)
	group_bys = GROUP_BYS[spec["level"]] + (("host_label",) if label and "host_label" not in GROUP_BYS[spec["level"]] else ())
	return {
		**shown(spec),
		"label_key": label,
		"aggregations": AGGREGATIONS[spec["kind"]],
		"default_aggregation": DEFAULT_AGGREGATION[spec["kind"]],
		"group_bys": group_bys,
		"caveat": translate(CAVEATS[metric]) if metric in CAVEATS else None,
	}


def validate(metric, aggregation, group_by):
	"""(aggregation, group_by) checked against the metric's kind and level; ValueError if not allowed."""
	d = describe(metric)
	aggregation = aggregation or d["default_aggregation"]
	group_by = group_by or "none"
	if aggregation not in d["aggregations"]:
		raise ValueError(fmt(_("{0} is not meaningful for {1} ({2}): use {3}"), aggregation, metric, d["kind"], ", ".join(d["aggregations"])))
	if group_by not in d["group_bys"]:
		raise ValueError(fmt(_("{0} cannot be grouped by {1}: use {2}"), metric, group_by, ", ".join(d["group_bys"])))
	return aggregation, group_by
