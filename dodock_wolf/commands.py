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


@click.group("wolf-rules")
def wolf_rules():
	"""Alert rules as YAML: export them, import a file (a dry run unless --apply)."""


@wolf_rules.command("export")
@click.option("--rule", "rules", multiple=True, help="a rule to export (repeatable); default: every rule")
@click.option("--output", "-o", type=click.Path(dir_okay=False, writable=True), help="file to write; default: stdout")
@pass_context
def rules_export(context, rules=(), output=None):
	"""Write the alert rules as YAML. Channel secrets are never written."""
	import frappe

	from dodock_wolf.api import rules_io

	frappe.init(site=get_site(context))
	frappe.connect()
	try:
		missing = [r for r in rules if not frappe.db.exists("Wolf Alert Rule", r)]
		if missing:
			raise click.ClickException("no such rule: " + ", ".join(missing))
		text = rules_io.dump(rules_io.export_document(list(rules) or None))
	finally:
		frappe.destroy()
	if output:
		with open(output, "w") as f:
			f.write(text)
		click.echo(f"wrote {output}", err=True)
	else:
		click.echo(text, nl=False)


@wolf_rules.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--apply", is_flag=True, help="write the changes (default: show them)")
@pass_context
def rules_import(context, path, apply=False):
	"""Show what a YAML file would create or change; --apply writes it, when every rule is valid."""
	import frappe

	from dodock_wolf.api import rules_io
	from dodock_wolf.wolf.rules_io import DocumentError

	with open(path) as f:
		text = f.read()
	frappe.init(site=get_site(context))
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		try:
			result = rules_io.import_document(rules_io.load(text), apply=apply)
		except DocumentError as e:
			raise click.ClickException(str(e)) from e
		if result["applied"]:
			frappe.db.commit()
		else:
			frappe.db.rollback()
	finally:
		frappe.destroy()
	for item in result["rules"]:
		line = f"{item['action']:>9}  {item['rule_name']}"
		if item["changes"]:
			line += "  (" + ", ".join(item["changes"]) + ")"
		click.echo(line)
		for text_ in item["errors"]:
			click.echo(f"           error: {text_}")
		for text_ in item["notes"]:
			click.echo(f"           note: {text_}")
	counts = result["counts"]
	summary = ", ".join(f"{n} {a}" for a, n in counts.items() if n)
	if result["applied"]:
		click.echo(f"applied: {summary}")
	elif not result["valid"]:
		click.echo(f"nothing applied, fix the invalid rule(s) first: {summary}", err=True)
		raise SystemExit(1)
	else:
		click.echo(f"dry run: {summary}; run again with --apply to write it")


commands = [verify_journal, wolf_rules]
