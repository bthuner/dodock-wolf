"""bench commands of Dodock Wolf."""

import click
from frappe.commands import get_site, pass_context


@click.command("wolf-verify-journal")
@click.option("--anchor", help="seq:mac copied earlier (Wolf → Security, or the SIEM): check it is still in the chain")
@pass_context
def verify_journal(context, anchor=None):
	"""Check the Wolf journal's HMAC chain: every digest, every mac, no gap."""
	import frappe

	from dodock_wolf.api.journal import verify_journal as verify

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	try:
		result = verify(anchor)
	finally:
		frappe.destroy()
	if result["ok"]:
		purged = f" (1 to {result['purged_through']} purged by the retention, as recorded)" if result.get("purged_through") else ""
		click.echo(f"journal OK: {result['checked']} entries, seq {result.get('first_seq')} to {result.get('last_seq')}{purged}, "
		           f"{result.get('pending', 0)} waiting to be signed; anchor {result.get('last_seq')}:{result.get('last_mac')}")
	else:
		problem = result["problem"] or {}
		click.echo(f"journal BROKEN at seq {problem.get('seq')}: {problem.get('why')} ({result['checked']} entries checked)", err=True)
		raise SystemExit(1)


# the preset rules the demos' storyline trips (wolf_agent/demo/server.py)
DEMO_RULES = [
	"502 spike after deployment", "5xx spike", "Scheduler failure", "Nightly cron failure (01:00-04:00)",
	"Worker crash", "SSH brute force", "SSH login after brute force", "Web attack scan",
]  # fmt: skip


def _demo_command(kind, summary):
	@click.command(f"generate-demo-{kind}")
	@click.option("--root", help=f"where to lay out the demo server (default /home/frappe/demo-{kind})")
	@click.option("--agent-config", help="config of the agent that reads the demo (default: <root>/agent-config.json)")
	@click.option("--days", default=7.0, show_default=True, help="history to write before going live")
	@click.option("--live/--no-live", default=True, show_default=True, help="keep writing traffic and incidents")
	@click.option("--cycle", default=30, show_default=True, help="minutes between live incident cycles")
	@click.option("--timeout", default=300, show_default=True, help="seconds to wait for the agent to track the files")
	@click.option("--webhook", help="also send the demo's alerts to this webhook URL")
	@pass_context
	def command(context, root=None, agent_config=None, days=7.0, live=True, cycle=30, timeout=300, webhook=None):
		_run_demo(context, kind, root, agent_config, days, live, cycle, timeout, webhook)

	command.help = (
		f"{summary}, 7 days of history, then live incidents.\n\n"
		f"The files are read by a Wolf agent (`wolf-agent demo {kind} --configure`), so discovery, "
		"tailing, parsing and alerting all run as on a real server. See dev/demo/README.md."
	)
	return command


def _run_demo(context, kind, root, agent_config, days, live, cycle, timeout, webhook):
	import logging
	import os

	try:
		from wolf_agent.config import load_config
		from wolf_agent.demo import build
	except ImportError:
		raise click.ClickException("the Wolf agent is not installed in this bench's env: env/bin/pip install ./agent") from None

	if webhook:
		_route_demo_rules(get_site(context), webhook)
	root = root or f"/home/frappe/demo-{kind}"
	agent_config = agent_config or os.path.join(root, "agent-config.json")
	try:
		cfg = load_config(agent_config)
	except (OSError, ValueError) as e:
		raise click.ClickException(f"cannot read the demo agent's config {agent_config}: {e}") from None
	handler = logging.StreamHandler()
	handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
	demo_log = logging.getLogger("wolf_agent.demo")
	demo_log.addHandler(handler)
	demo_log.setLevel(logging.INFO)
	demo = build(kind, cfg, root=root)
	click.echo(f"{kind} demo {demo.host} in {demo.root}: {days:g} day(s) of history" + (f", then a cycle every {cycle} min" if live else ""))
	try:
		demo.run(days=days, live=live, cycle=cycle, timeout=timeout)
	except TimeoutError as e:
		raise click.ClickException(f"{e}. Run that agent with `wolf-agent demo {kind} --configure` applied.") from None
	except KeyboardInterrupt:
		click.echo("stopped")


generate_demo_press = _demo_command("press", "A live Press app server for Wolf to watch: 3 benches, 8 sites")
generate_demo_multi = _demo_command("multi", "A live host with plain benches for Wolf to watch: 2 benches, 6 sites")
generate_demo_single = _demo_command("single", "A live single-site bench for Wolf to watch")


def _route_demo_rules(site, url):
	"""Add a webhook channel to the demo's preset rules (once per URL).

	Demos started together route the same rules at the same moment: a save that lost the race
	is retried on the fresh rule.
	"""
	import random
	import time

	import frappe

	frappe.init(site=site)
	frappe.connect()
	try:
		for name in DEMO_RULES:
			for attempt in range(5):
				if not frappe.db.exists("Wolf Alert Rule", name):
					break
				rule = frappe.get_doc("Wolf Alert Rule", name)
				if any(c.channel_type == "Webhook" and c.webhook_url == url for c in rule.channels):
					break
				rule.append("channels", {"channel_type": "Webhook", "webhook_url": url, "enabled": 1})
				try:
					rule.save(ignore_permissions=True)
					frappe.db.commit()
					break
				except frappe.TimestampMismatchError:
					frappe.db.rollback()
					if attempt == 4:
						raise
					time.sleep(random.uniform(0.2, 1.0))
	finally:
		frappe.destroy()


commands = [verify_journal, generate_demo_press, generate_demo_multi, generate_demo_single]
