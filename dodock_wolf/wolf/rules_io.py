"""Alert rules as a document, for YAML import and export (no frappe imports).

The document is `{"version": 1, "rules": [...]}`. A rule holds `rule_name`, `enabled` and the
fields whose value is not the DocType default, with the DocType's own field names; `channels` and
`escalation_channels` are lists of channel rows. Secrets (each channel type's `SECRETS`: tokens,
chat webhook URLs, routing keys) are never written: on import a channel keeps the stored secret
of the matching row (same list, same type, in order), and a new one that needs a secret it does
not have comes in disabled, to be completed in the form.

An import is a plan first: per rule `create`, `update` (with the fields that change), `unchanged`
or `invalid` (with why). A field the document leaves out goes back to its default, so the file
says all of a rule; rules not in the document are left alone. Unknown fields are errors, so a
typo does not silently do nothing.
"""

import datetime

VERSION = 1
# the evaluator's own state and markers: never in a document, never imported
RUNTIME_FIELDS = {"last_evaluated", "last_fired", "last_error", "evaluation_state", "is_preset"}
CHANNEL_LISTS = ("channels", "escalation_channels")
NUMERIC = {"Check", "Int"}


class DocumentError(ValueError):
	pass


def normalize(fieldtype, value):
	"""One comparable value per field type: what the form would show."""
	if fieldtype == "Check":
		return 1 if value in (1, True, "1", "true", "True", "yes") else 0
	if fieldtype == "Int":
		try:
			return int(value or 0)
		except (TypeError, ValueError):
			return 0
	if fieldtype == "Float":
		try:
			number = float(value or 0)
		except (TypeError, ValueError):
			return 0.0
		return int(number) if number.is_integer() else number
	if fieldtype == "Time":
		if value in (None, ""):
			return None
		if isinstance(value, datetime.timedelta):
			seconds = int(value.total_seconds())
			return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
		if isinstance(value, datetime.time):
			return value.strftime("%H:%M:%S")
		parts = [int(p) for p in str(value).split(":")] + [0, 0]
		return f"{parts[0]:02d}:{parts[1]:02d}:{parts[2]:02d}"
	text = "" if value is None else str(value).replace("\r\n", "\n").strip()
	return text or None


def export_rules(rules, fields, channel_fields, secrets):
	"""The document for `rules` (dicts with their channel rows).

	`fields`: `{fieldname: (fieldtype, default)}` of the rule; `channel_fields` the same for a
	channel row; `secrets`: channel type → fields never written."""
	out = []
	for rule in sorted(rules, key=lambda r: r["rule_name"]):
		item = {"rule_name": rule["rule_name"], "enabled": normalize("Check", rule.get("enabled"))}
		for name, (fieldtype, default) in fields.items():
			if name in RUNTIME_FIELDS or name in ("rule_name", "enabled"):
				continue
			value = normalize(fieldtype, rule.get(name))
			if value != normalize(fieldtype, default):
				item[name] = value
		for listname in CHANNEL_LISTS:
			rows = [_export_channel(row, channel_fields, secrets) for row in rule.get(listname) or []]
			if rows:
				item[listname] = rows
		out.append(item)
	return {"version": VERSION, "rules": out}


def _export_channel(row, channel_fields, secrets):
	hidden = set(secrets.get(row.get("channel_type"), ()))
	item = {"channel_type": row.get("channel_type")}
	for name, (fieldtype, default) in channel_fields.items():
		if name == "channel_type" or name in hidden:
			continue
		value = normalize(fieldtype, row.get(name))
		if value != normalize(fieldtype, default):
			item[name] = value
	return item


def parse(document, fields, channel_fields):
	"""The rules of a loaded document, checked: a list of `(rule, errors)`."""
	if not isinstance(document, dict) or document.get("version") != VERSION or not isinstance(document.get("rules"), list):
		raise DocumentError(f'expected a mapping with "version: {VERSION}" and a "rules" list')
	allowed = (set(fields) - RUNTIME_FIELDS) | set(CHANNEL_LISTS)
	seen, out = set(), []
	for i, rule in enumerate(document["rules"], 1):
		errors = []
		if not isinstance(rule, dict) or not isinstance(rule.get("rule_name"), str) or not rule["rule_name"].strip():
			out.append(({"rule_name": f"#{i}"}, ["a rule needs a rule_name"]))
			continue
		name = rule["rule_name"].strip()
		if name in seen:
			errors.append("this rule_name appears twice in the document")
		seen.add(name)
		unknown = sorted(set(rule) - allowed)
		if unknown:
			errors.append("unknown field(s): " + ", ".join(unknown))
		for listname in CHANNEL_LISTS:
			rows = rule.get(listname, [])
			if not isinstance(rows, list):
				errors.append(f"{listname} must be a list")
				continue
			for j, row in enumerate(rows, 1):
				if not isinstance(row, dict) or not row.get("channel_type"):
					errors.append(f"{listname} #{j}: a channel needs a channel_type")
					continue
				bad = sorted(set(row) - set(channel_fields))
				if bad:
					errors.append(f"{listname} #{j}: unknown field(s): " + ", ".join(bad))
		out.append(({**rule, "rule_name": name}, errors))
	return out


def target(rule, fields):
	"""Every field of the rule as the document says it: what it leaves out goes back to its default."""
	values = {}
	for name, (fieldtype, default) in fields.items():
		if name in RUNTIME_FIELDS:
			continue
		values[name] = normalize(fieldtype, rule[name] if name in rule else default)
	values["rule_name"] = rule["rule_name"]
	return values


def merge_channels(incoming, existing, channel_fields, secrets):
	"""Channel rows to save: the document's, with the stored secrets of the matching existing row
	(same type, in order) and its row name, which the stored secret belongs to. Returns `(rows,
	notes)`; a row missing a secret it needs is disabled."""
	pool = {}
	for row in existing or []:  # dicts with the row's name and its secrets as stored
		pool.setdefault(row.get("channel_type"), []).append(row)
	rows, notes = [], []
	for j, row in enumerate(incoming or [], 1):
		kind = row["channel_type"]
		values = {name: normalize(fieldtype, row[name] if name in row else default)
		          for name, (fieldtype, default) in channel_fields.items()}  # fmt: skip
		values["channel_type"] = kind
		match = pool.get(kind, []).pop(0) if pool.get(kind) else None
		if match and match.get("name"):
			values["name"] = match["name"]  # the stored secret belongs to that row: keep it
		for secret in secrets.get(kind, ()):
			values[secret] = (match or {}).get(secret) or None
		missing = [s for s in secrets.get(kind, ()) if not values.get(s)]
		if missing and values.get("enabled"):
			values["enabled"] = 0
			notes.append(f"{kind} #{j}: imported disabled, set {', '.join(missing)} in the form, then enable it")
		rows.append(values)
	return rows, notes


def changes(current, wanted, fields):
	"""Fields whose value differs between the stored rule and the document's."""
	out = []
	for name, value in wanted.items():
		fieldtype = fields.get(name, ("Data", None))[0]
		if normalize(fieldtype, current.get(name)) != value:
			out.append(name)
	return sorted(out)


def channel_rows_differ(current_rows, wanted_rows, channel_fields, secrets):
	"""Whether the saved channel rows would change, secrets aside (they cannot be compared: the
	form shows them as asterisks)."""
	if len(current_rows or []) != len(wanted_rows or []):
		return True
	for a, b in zip(current_rows or [], wanted_rows or []):  # noqa: B905 (same lengths, checked above)
		hidden = set(secrets.get(b.get("channel_type"), ()))
		for name, (fieldtype, _default) in channel_fields.items():
			if name not in hidden and normalize(fieldtype, a.get(name)) != b.get(name):
				return True
	return False
