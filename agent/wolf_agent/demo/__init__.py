"""Live demo data, written where the real agent reads it.

A demo lays out files the way a real host has them (bench logs, nginx's access log, auth.log,
the Press agent's jobs.sqlite3), waits until the running agent tracks them, then appends days
of history and keeps writing live traffic with scripted incidents. Everything Wolf shows goes
through the agent's own discovery, tailers and parsers; only past host metrics, which the agent
samples from /proc, are handed to its spool. See dev/demo/README.md.
"""

KINDS = ("press", "multi", "single")


def build(kind, cfg, root=None, rng=None):
	"""The demo server of `kind` for the agent configured by `cfg` (its host name and spool)."""
	if kind == "press":
		from .press import DEFAULT_ROOT, PressDemo

		return PressDemo(root or DEFAULT_ROOT, host=cfg["hostname"], spool_dir=cfg["spool_dir"], rng=rng)
	from .bench import BenchDemo

	return BenchDemo(kind, root, host=cfg["hostname"], spool_dir=cfg["spool_dir"], rng=rng, mark_deployment=_marker(cfg))


def _marker(cfg):
	"""Deployments through the agent's deployment endpoint, with their own time."""
	if not (cfg.get("url") and cfg.get("agent_id") and cfg.get("agent_secret")):
		return None
	from ..shipper import Shipper
	from ..util import utc_iso

	shipper = Shipper(cfg)
	return lambda bench, site, note, at: shipper.mark_deployment(bench, site, note, timestamp=utc_iso(at))
