"""Alert rules as YAML: export, and import with a dry run first (dodock_wolf/wolf/rules_io.py).

Desk (the Wolf Alert Rule list's menu) and `bench --site <site> wolf-rules export|import` call
these. An import writes only with `apply`, and only when every rule of the document is valid:
nothing half-applied.
"""

import frappe
from frappe import _

from dodock_wolf.wolf import rules_io
from dodock_wolf.wolf.channels import SECRETS

RULE = "Wolf Alert Rule"
CHANNEL = "Wolf Alert Channel"
MANAGERS = ("System Manager", "Wolf Manager")
LAYOUT = {"Section Break", "Column Break", "Tab Break", "Table", "Table MultiSelect", "HTML", "Button", "Heading", "Fold"}
MAX_BYTES = 2 * 1024 * 1024


def _fields(doctype):
	return {f.fieldname: (f.fieldtype, f.default) for f in frappe.get_meta(doctype).fields if f.fieldtype not in LAYOUT}


def _rule_dict(doc):
	data = {f: doc.get(f) for f in _fields(RULE)}
	data["rule_name"] = doc.rule_name
	for listname in rules_io.CHANNEL_LISTS:
		data[listname] = [{"name": row.name, **{f: row.get(f) for f in _fields(CHANNEL)}} for row in doc.get(listname) or []]
	return data


def export_document(names=None):
	"""The document for the named rules, every rule when none is named."""
	names = names or frappe.get_all(RULE, pluck="name", order_by="name asc")
	rules = [_rule_dict(frappe.get_doc(RULE, name)) for name in names]
	return rules_io.export_rules(rules, _fields(RULE), _fields(CHANNEL), SECRETS)


def dump(document):
	import yaml

	return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False, width=110)


def load(text):
	import yaml

	if len(text.encode()) > MAX_BYTES:
		raise rules_io.DocumentError(f"the document is larger than {MAX_BYTES // 1024 // 1024} MB")
	try:
		return yaml.safe_load(text)
	except yaml.YAMLError as e:
		raise rules_io.DocumentError(f"not valid YAML: {e}") from e


def import_document(document, apply=False):
	"""The plan for a loaded document, applied when `apply` and every rule is valid."""
	fields, channel_fields = _fields(RULE), _fields(CHANNEL)
	plan, docs = [], []
	for rule, errors in rules_io.parse(document, fields, channel_fields):
		item = {"rule_name": rule["rule_name"], "action": None, "changes": [], "notes": [], "errors": list(errors)}
		plan.append(item)
		if errors:
			item["action"] = "invalid"
			continue
		exists = frappe.db.exists(RULE, rule["rule_name"])
		doc = frappe.get_doc(RULE, rule["rule_name"]) if exists else frappe.new_doc(RULE)
		current = _rule_dict(doc) if exists else {}
		wanted = rules_io.target(rule, fields)
		rows = {}
		for listname in rules_io.CHANNEL_LISTS:
			rows[listname], notes = rules_io.merge_channels(rule.get(listname), current.get(listname), channel_fields, SECRETS)
			item["notes"] += [f"{listname}: {n}" for n in notes]
		changed = rules_io.changes(current, wanted, fields) if exists else []
		changed += [listname for listname in rules_io.CHANNEL_LISTS
		            if rules_io.channel_rows_differ(current.get(listname), rows[listname], channel_fields, SECRETS)]  # fmt: skip
		item["changes"] = sorted(set(changed))
		item["action"] = ("update" if item["changes"] else "unchanged") if exists else "create"
		doc.update(wanted)
		for listname in rules_io.CHANNEL_LISTS:
			doc.set(listname, rows[listname])
		try:
			doc.run_method("validate")  # the form's own checks, nothing written
		except frappe.ValidationError as e:
			item["action"], item["errors"] = "invalid", [frappe.utils.strip_html(str(e)) or type(e).__name__]
			continue
		docs.append((item, doc))
	valid = all(item["action"] != "invalid" for item in plan)
	applied = bool(apply) and valid
	if applied:
		for item, doc in docs:
			if item["action"] == "create":
				doc.insert()
			elif item["action"] == "update":
				doc.save()
	frappe.local.message_log = []  # validate's own messages are in the plan
	counts = {a: sum(i["action"] == a for i in plan) for a in ("create", "update", "unchanged", "invalid")}
	return {"applied": applied, "valid": valid, "counts": counts, "rules": plan}


@frappe.whitelist()
def export_yaml(names=None):
	frappe.only_for(MANAGERS)
	if isinstance(names, str):
		names = frappe.parse_json(names)
	return {"filename": f"wolf-rules-{frappe.local.site}.yaml", "content": dump(export_document(names or None))}


@frappe.whitelist(methods=["POST"])
def import_yaml(content, apply=0):
	"""A dry run by default; `apply=1` writes, when every rule is valid."""
	frappe.only_for(MANAGERS)
	try:
		document = load(content or "")
		result = import_document(document, apply=frappe.utils.cint(apply))
	except rules_io.DocumentError as e:
		frappe.throw(_("Cannot import: {0}").format(str(e)))
	if not result["applied"]:
		frappe.db.rollback()  # a dry run writes nothing, even through hooks
	return result
