"""`wolf-agent` command line: register, run, check, discover, mark-deployment, test-fallback."""

import argparse
import json
import logging
import os
import platform
import signal
import socket
import sys
import threading

from . import __version__, press
from .collector import Collector
from .config import DEFAULTS, config_path, load_config, press_settings, save_config, section
from .discovery import discover_benches
from .fallback import FallbackError
from .responder import Responder
from .shipper import AuthError, RejectedError, Shipper, TransportError, register
from .util import parse_duration_minutes
from .watchdog import STATE_FILE, Watchdog, assess

log = logging.getLogger("wolf_agent")
EXIT_AUTH = 2
PLATFORMS = ("auto", "press", "generic")  # systemd unit sets RestartPreventExitStatus=2


def _os_name():
	try:
		with open("/etc/os-release") as f:
			for line in f:
				if line.startswith("PRETTY_NAME="):
					return line.split("=", 1)[1].strip().strip('"')
	except OSError:
		pass
	return platform.platform()


def _load(args):
	path = config_path(args.config)
	try:
		return path, load_config(path)
	except FileNotFoundError:
		sys.exit(f"config not found: {path} (run `wolf-agent register` first)")
	except ValueError as e:
		sys.exit(f"invalid config {path}: {e}")


def _platform(args, cfg=None):
	"""--platform wins, then the config's `platform`; None means auto-detect."""
	value = getattr(args, "platform", None)
	if value and value != "auto":
		return value
	return (cfg or {}).get("platform")


def _discover(args, cfg=None):
	press_cfg = press_settings(cfg or {})
	return discover_benches(
		args.bench or None,
		platform=_platform(args, cfg),
		press_agent_dir=press_cfg["agent_dir"],
		press_benches_dir=press_cfg.get("benches_directory"),
	)


def _remember_press(cfg):
	"""Registration runs as root; the daemon runs as wolf-agent, which cannot read the Press agent's
	config.json (mode 0600). Keep what root found: that this is Press, the benches folder and the
	proxy in front of it; on a proxy server, read its nginx log.
	Returns the server's name in Press (`agent setup config --name`), or None."""
	press_cfg = press_settings(cfg)
	if cfg.get("platform") in (None, "auto") and press.detect(press_cfg["agent_dir"]):
		cfg["platform"] = "press"
	if cfg.get("platform") != "press":
		return None
	agent_cfg = press.read_agent_config(press_cfg["agent_dir"]) or {}
	if agent_cfg:  # read as root: what it says now, a removed proxy included
		press_now = dict(cfg.get("press") or {})
		for key, value in (("benches_directory", agent_cfg.get("benches_directory")), ("proxy_ip", agent_cfg.get("proxy_ip")),
		                   ("server_name", agent_cfg.get("name"))):  # fmt: skip
			if value:
				press_now[key] = value
			elif key != "benches_directory":
				press_now.pop(key, None)
		cfg["press"] = press_now
	# a Press proxy server (n*): no bench, the sites' traffic in its nginx log, with the real clients
	if press.is_proxy(press_cfg["agent_dir"]):
		log_path = press_cfg.get("nginx_access_log") or press.DEFAULT_NGINX_ACCESS_LOG
		entry = {"path": log_path, "parser": "nginx", "site_from_host": True}
		extra = [dict(e) for e in cfg.get("extra_logs") or []]
		same = [e for e in extra if e.get("path") == log_path]
		if not same:
			extra.append(entry)
		for e in same:
			if e.get("parser", "nginx") == "nginx":
				e.update(entry)  # one registered before: its sites from $host too
		cfg["extra_logs"] = extra
	name = agent_cfg.get("name")
	return name if isinstance(name, str) and name.strip() else None


def cmd_discover(args):
	print(json.dumps(_discover(args), indent=2))


def cmd_register(args):
	path = config_path(args.config)
	try:
		cfg = load_config(path)
	except (FileNotFoundError, ValueError):
		cfg = dict(DEFAULTS)
	cfg["url"] = args.url.rstrip("/")
	cfg["verify_tls"] = not args.insecure
	if args.platform and args.platform != "auto":
		cfg["platform"] = args.platform
	# on Press, the server's name in Press: what its benches' sites report as their host
	press_name = _remember_press(cfg)
	cfg["hostname"] = args.hostname or cfg.get("hostname") or press_name or socket.getfqdn() or socket.gethostname()
	cfg["benches"] = _discover(args, cfg)
	if not cfg["benches"]:
		log.warning("no bench found; only host metrics and auth logs will be collected")

	try:
		resp = register(cfg["url"], args.token, cfg["hostname"], cfg["benches"], _os_name(), cfg["verify_tls"])
	except (AuthError, RejectedError, TransportError) as e:
		sys.exit(f"registration failed: {e}")
	if not resp.get("agent_id") or not resp.get("agent_secret"):
		sys.exit(f"registration failed: unexpected response {resp!r}")

	cfg["agent_id"] = resp["agent_id"]
	cfg["agent_secret"] = resp["agent_secret"]
	cfg["push_interval"] = int(resp.get("push_interval") or cfg.get("push_interval") or 30)
	save_config(path, cfg)
	print(f"registered as {cfg['agent_id']} with {cfg['url']}; config written to {path}")
	for bench in cfg["benches"]:
		print(f"  bench {bench['name']} at {bench['path']}: {len(bench['sites'])} site(s)")


def cmd_refresh(args):
	"""As root: read again what the daemon's user cannot (a Press server's benches folder, its proxy;
	a Press proxy's access log) and save it, without registering again. install.sh runs it."""
	path, cfg = _load(args)
	before = json.dumps(cfg, sort_keys=True)
	_remember_press(cfg)
	if json.dumps(cfg, sort_keys=True) != before:
		save_config(path, cfg)
		print(f"updated {path}")
	else:
		print(f"{path} is up to date")


def cmd_check(args):
	path = config_path(args.config)
	cfg = _load(args)[1] if os.path.exists(path) else _ephemeral_config(args)
	if args.bench:
		cfg["benches"] = _discover(args, cfg)
	if args.platform and args.platform != "auto":
		cfg["platform"] = args.platform
	collector = Collector(cfg, state_path=None, from_start=args.from_start, sync_checks=True)
	metrics, events = collector.collect()
	collector.close()
	body = {"hostname": cfg["hostname"], "agent_version": __version__, "metrics": metrics, "events": events}
	print(json.dumps(body, indent=2))
	# stdout stays the payload; the watchdog report goes to stderr
	for line in _watchdog_report(cfg, live=args.status):
		print(line, file=sys.stderr)


def _watchdog(cfg):
	return Watchdog(cfg, state_path=os.path.join(cfg["spool_dir"], STATE_FILE))


def _watchdog_report(cfg, live=False):
	try:
		watchdog = _watchdog(cfg)
		lines = watchdog.summary()
	except Exception as e:
		return [f"watchdog: cannot read state: {e}"]
	if live and not (cfg.get("url") and cfg.get("agent_id") and cfg.get("agent_secret")):
		lines.append("live status: not registered")
	elif live:
		try:
			health = Shipper(cfg).status().get("health")
		except (AuthError, RejectedError, TransportError) as e:
			lines.append(f"live status: unavailable ({e})")
		else:
			if isinstance(health, dict):
				problems = assess(health, watchdog.stale_minutes)
				lines.append(f"live status: {'; '.join(problems) if problems else 'healthy'}")
				lines.append("health: " + json.dumps(health, sort_keys=True))
			else:
				lines.append("live status: the Wolf site returned no health")
	return lines


def cmd_test_fallback(args):
	_, cfg = _load(args)
	watchdog = _watchdog(cfg)
	try:
		delivered = watchdog.test()
	except FallbackError as e:
		sys.exit(f"fallback failed: {e}")
	if not delivered:
		sys.exit("no fallback channel configured: set watchdog.webhook_url and/or watchdog.smtp in the config")
	print(f"test message sent via {', '.join(delivered)}")


def _ephemeral_config(args):
	cfg = dict(DEFAULTS)
	cfg["hostname"] = socket.gethostname()
	cfg["benches"] = _discover(args, cfg)
	return cfg


def cmd_mark_deployment(args):
	silence = None
	if args.silence:
		try:
			silence = parse_duration_minutes(args.silence)
		except ValueError as e:
			sys.exit(str(e))
	_, cfg = _load(args)
	shipper = Shipper(cfg)
	try:
		resp = shipper.mark_deployment(args.bench, args.site, args.note, args.source, silence_minutes=silence)
	except (AuthError, RejectedError, TransportError) as e:
		sys.exit(f"could not record deployment: {e}")
	print(f"deployment recorded for bench {args.bench}")
	if silence:
		if resp.get("silence"):
			print(f"notifications silenced until {resp.get('silence_until') or 'the window ends'} ({resp['silence']})")
		else:
			log.warning("the Wolf App did not create a silence (older version?): notifications are not muted")


def cmd_demo(args):
	"""Lay out a demo server for this agent, backfill its history, then keep it alive."""
	from .demo import build

	path, cfg = _load(args)
	demo = build(args.kind, cfg, root=args.root)
	if args.configure:
		with open(path) as f:
			raw = json.load(f)
		raw.update(demo.agent_overrides())
		save_config(path, raw)
		print(f"{path}: {args.kind} demo in {demo.root} ({demo.host}); restart the agent")
		return
	stop = threading.Event()
	for sig in (signal.SIGTERM, signal.SIGINT):
		signal.signal(sig, lambda *_: stop.set())
	try:
		demo.run(days=args.days, live=not args.no_live, cycle=args.cycle, timeout=args.timeout, stop=stop)
	except TimeoutError as e:
		sys.exit(f"{e}. Is it running with `wolf-agent demo {args.kind} --configure` applied?")


def cmd_run(args):
	_, cfg = _load(args)
	if not (cfg.get("url") and cfg.get("agent_id") and cfg.get("agent_secret")):
		sys.exit("config is missing url/agent_id/agent_secret; run `wolf-agent register`")
	state_path = os.path.join(cfg["spool_dir"], "tail-state.json")
	collector = Collector(cfg, state_path=state_path)
	shipper = Shipper(cfg)
	responder = Responder(section(cfg, "response"))
	watchdog = _watchdog(cfg)

	stop = threading.Event()
	for sig in (signal.SIGTERM, signal.SIGINT):
		signal.signal(sig, lambda *_: stop.set())

	log.info("wolf-agent %s started: %d log source(s), pushing to %s", __version__, len(collector.sources), cfg["url"])
	try:
		while not stop.is_set():
			metrics, events = collector.collect()
			try:
				ok = shipper.send(metrics, events)
			except AuthError as e:
				log.error("Wolf App rejected agent %s credentials (%s); re-register this host", cfg["agent_id"], e)
				watchdog.fatal(f"the Wolf site rejected agent {cfg['agent_id']} credentials ({e}); re-register this host")
				return EXIT_AUTH
			watchdog.observe(ok, shipper.health)
			if ok and shipper.actions:
				shipper.results += responder.handle(shipper.actions)
			stop.wait(shipper.push_interval)
	finally:
		collector.close()
	log.info("wolf-agent stopped")
	return 0


def build_parser():
	p = argparse.ArgumentParser(prog="wolf-agent", description="Dodock Wolf host agent")
	p.add_argument("--config", help="config path (default $WOLF_AGENT_CONFIG or /etc/wolf-agent/config.json)")
	p.add_argument("-v", "--verbose", action="store_true")
	p.add_argument("--version", action="version", version=__version__)
	sub = p.add_subparsers(dest="command", required=True)

	r = sub.add_parser("register", help="register this host with a Wolf site and write the config")
	r.add_argument("--url", required=True, help="Wolf site URL, e.g. https://wolf.example.com")
	r.add_argument("--token", required=True, help="registration token from Wolf Settings")
	r.add_argument("--bench", action="append", help="bench path (repeatable; default: auto-discover)")
	r.add_argument("--hostname", help="override the reported hostname")
	r.add_argument("--insecure", action="store_true", help="do not verify TLS certificates")
	r.add_argument("--platform", choices=PLATFORMS, default="auto", help="bench layout (default: auto-detect)")
	r.set_defaults(func=cmd_register)

	sub.add_parser("run", help="run the agent loop").set_defaults(func=cmd_run)
	sub.add_parser("refresh", help="as root: re-read the Press facts the agent's user cannot, keep the registration").set_defaults(
		func=cmd_refresh
	)

	c = sub.add_parser("check", help="collect once and print the payload without sending")
	c.add_argument("--from-start", action="store_true", help="parse logs from the beginning instead of EOF")
	c.add_argument("--bench", action="append", help="bench path when no config exists")
	c.add_argument("--platform", choices=PLATFORMS, default="auto", help="bench layout (default: config or auto)")
	c.add_argument("--status", action="store_true", help="also ask the Wolf site for its health (read-only)")
	c.set_defaults(func=cmd_check)

	d = sub.add_parser("discover", help="print benches found on this host")
	d.add_argument("--bench", action="append", help="bench path to inspect")
	d.add_argument("--platform", choices=PLATFORMS, default="auto", help="bench layout (default: auto-detect)")
	d.set_defaults(func=cmd_discover)

	m = sub.add_parser("mark-deployment", help="record a deployment on the Wolf timeline")
	m.add_argument("--bench", required=True)
	m.add_argument("--site")
	m.add_argument("--note")
	m.add_argument("--source", default="manual", choices=["manual", "pilot", "press", "migrate"])
	m.add_argument("--silence", metavar="DURATION", help="mute notifications for this bench/site, e.g. 15m or 1h")
	m.set_defaults(func=cmd_mark_deployment)

	sub.add_parser(
		"test-fallback", help="send a test message through the watchdog fallback channel(s)"
	).set_defaults(func=cmd_test_fallback)
	dm = sub.add_parser("demo", help="write live demo data where this agent reads it (dev/demo/README.md)")
	dm.add_argument(
		"kind", choices=["press", "multi", "single"],
		help="press: a Press app server, 3 benches, 8 sites; multi: 2 benches, 6 sites; single: 1 bench, 1 site",
	)  # fmt: skip
	dm.add_argument("--root", help="where to lay out the demo server (default /home/frappe/demo-<kind>)")
	dm.add_argument("--days", type=float, default=7, help="history to write before going live (default 7)")
	dm.add_argument("--no-live", action="store_true", help="write the history and exit")
	dm.add_argument("--cycle", type=int, default=30, help="minutes between live incident cycles (default 30)")
	dm.add_argument("--timeout", type=int, default=300, help="seconds to wait for the agent to track the files")
	dm.add_argument("--configure", action="store_true", help="point this agent's config at the demo and exit")
	dm.set_defaults(func=cmd_demo)

	return p


def main(argv=None):
	args = build_parser().parse_args(argv)
	logging.basicConfig(
		level=logging.DEBUG if args.verbose else logging.INFO,
		format="%(asctime)s %(levelname)s %(name)s: %(message)s",
	)
	return args.func(args) or 0


if __name__ == "__main__":
	sys.exit(main())
