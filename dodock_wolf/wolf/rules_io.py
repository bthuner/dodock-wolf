"""Alert rules as a document, for YAML import and export (no frappe imports).

The document is `{"version": 1, "rules": [...]}`. A rule holds `rule_name`, `enabled` and the
fields whose value is not the DocType default, with the DocType's own field names; `channels` and
`escalation_channels` are lists of channel rows. Secrets (every Password field, and each channel
type's `SECRETS`) are never written, and a document that holds one is refused: they stay out of
git. On import a channel keeps the stored secret of the row it matches (see `merge_channels`); a
new one that needs a secret it does not have comes in disabled, to be completed in the form.

An import is a plan first: per rule `create`, `update` (with the fields that change), `unchanged`
or `invalid` (with why). A field the document leaves out goes back to its default, so the file
says all of a rule; rules not in the document are left alone. Unknown fields, values a field
cannot take (a Select option it does not have, a number that is not one, an unquoted time) are
errors, so a typo does not silently do something else.

A field spec is `(fieldtype, default)` or `(fieldtype, default, options)`.
"""

import datetime
import re

VERSION = 1
# the evaluator's own state and markers: never in a document, never imported
RUNTIME_FIELDS = {"last_evaluated", "last_fired", "last_error", "evaluation_state", "is_preset"}
# channel fields a v0.1.0 export may hold that 0.2 removed (digests): read and left out, so the file
# still imports
LEGACY_CHANNEL_FIELDS = {"digest"}
CHANNEL_LISTS = ("channels", "escalation_channels")
# the non-secret settings that tell two channels of a type apart (Slack, Mattermost and PagerDuty
# have none: their webhook or routing key is the secret)
IDENTITY = {
	"Email": ("recipients",),
	"Webhook": ("webhook_url",),
	"Raven": ("raven_channel",),
	"Matrix": ("matrix_homeserver", "matrix_room_id"),
	"ntfy": ("ntfy_server", "ntfy_topic"),
	"Gotify": ("gotify_server",),
	"SMS": ("sms_url", "sms_numbers"),
}
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


class DocumentError(ValueError):
	pass


def _type(spec):
	return spec[0]


def _default(spec):
	return spec[1]


def _options(spec):
	return [o for o in str(spec[2] or "").split("\n") if o] if len(spec) > 2 and _type(spec) == "Select" else []


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


def _hidden(channel_type, channel_fields, secrets):
	"""Fields never written for a channel row: every Password field, and the type's secrets."""
	return {name for name, spec in channel_fields.items() if _type(spec) == "Password"} | set(secrets.get(channel_type, ()))


def export_rules(rules, fields, channel_fields, secrets):
	"""The document for `rules` (dicts with their channel rows).

	`fields`: `{fieldname: spec}` of the rule; `channel_fields` the same for a channel row;
	`secrets`: channel type → fields never written (besides every Password field)."""
	out = []
	for rule in sorted(rules, key=lambda r: r["rule_name"]):
		item = {"rule_name": rule["rule_name"], "enabled": normalize("Check", rule.get("enabled"))}
		for name, spec in fields.items():
			if name in RUNTIME_FIELDS or name in ("rule_name", "enabled"):
				continue
			value = normalize(_type(spec), rule.get(name))
			if value != normalize(_type(spec), _default(spec)):
				item[name] = value
		for listname in CHANNEL_LISTS:
			rows = [_export_channel(row, channel_fields, secrets) for row in rule.get(listname) or []]
			if rows:
				item[listname] = rows
		out.append(item)
	return {"version": VERSION, "rules": out}


def _export_channel(row, channel_fields, secrets):
	hidden = _hidden(row.get("channel_type"), channel_fields, secrets)
	item = {"channel_type": row.get("channel_type")}
	for name, spec in channel_fields.items():
		if name == "channel_type" or name in hidden:
			continue
		value = normalize(_type(spec), row.get(name))
		if value != normalize(_type(spec), _default(spec)):
			item[name] = value
	return item


def _value_error(name, spec, value):
	"""Why `value` cannot go in the field, or None. None and "" always can (the default)."""
	if value is None or value == "":
		return None
	fieldtype = _type(spec)
	if fieldtype == "Time":
		if not isinstance(value, str) or not _TIME_RE.match(value.strip()):
			return f"{name}: write times quoted, as '22:00' (YAML reads an unquoted 22:00 as a number)"
		hours, minutes = (int(p) for p in value.strip().split(":")[:2])
		if hours > 23 or minutes > 59:
			return f"{name}: {value!r} is not a time of day"
	elif fieldtype in ("Int", "Float"):
		if isinstance(value, bool):
			return f"{name}: expected a number, got {value!r}"
		try:
			float(value)
		except (TypeError, ValueError):
			return f"{name}: expected a number, got {value!r}"
		if fieldtype == "Int" and float(value) != int(float(value)):
			return f"{name}: expected a whole number, got {value!r}"
	elif fieldtype == "Check":
		if value not in (0, 1, True, False, "0", "1"):
			return f"{name}: expected 0 or 1, got {value!r}"
	elif _options(spec) and str(value) not in _options(spec):
		return f"{name}: {value!r} is not one of {', '.join(_options(spec))}"
	elif isinstance(value, (dict, list)):
		return f"{name}: expected a value, got a {type(value).__name__}"
	return None


def parse(document, fields, channel_fields):
	"""The rules of a loaded document, checked: a list of `(rule, errors)`."""
	if not isinstance(document, dict) or document.get("version") != VERSION or not isinstance(document.get("rules"), list):
		raise DocumentError(f'expected a mapping with "version: {VERSION}" and a "rules" list')
	allowed = (set(fields) - RUNTIME_FIELDS) | set(CHANNEL_LISTS)
	passwords = {name for name, spec in channel_fields.items() if _type(spec) == "Password"}
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
		errors += [e for e in (_value_error(f, fields[f], rule[f]) for f in rule if f in fields and f in allowed) if e]
		for listname in CHANNEL_LISTS:
			rows = rule.get(listname, [])
			if not isinstance(rows, list):
				errors.append(f"{listname} must be a list")
				continue
			for j, row in enumerate(rows, 1):
				if not isinstance(row, dict) or not row.get("channel_type"):
					errors.append(f"{listname} #{j}: a channel needs a channel_type")
					continue
				for legacy in LEGACY_CHANNEL_FIELDS - set(channel_fields):
					row.pop(legacy, None)
				bad = sorted(set(row) - set(channel_fields))
				if bad:
					errors.append(f"{listname} #{j}: unknown field(s): " + ", ".join(bad))
				secret = sorted(set(row) & passwords)
				if secret:
					errors.append(f"{listname} #{j}: {', '.join(secret)}: secrets are not read from a file (keep them out of git): set them in the form")
				errors += [f"{listname} #{j}: {e}" for e in (_value_error(f, channel_fields[f], row[f]) for f in row
				           if f in channel_fields and f not in passwords) if e]  # fmt: skip
		out.append(({**rule, "rule_name": name}, errors))
	return out


def target(rule, fields):
	"""Every field of the rule as the document says it: what it leaves out goes back to its default."""
	values = {}
	for name, spec in fields.items():
		if name in RUNTIME_FIELDS:
			continue
		values[name] = normalize(_type(spec), rule[name] if name in rule else _default(spec))
	values["rule_name"] = rule["rule_name"]
	return values


def _identity(row, channel_fields):
	keys = IDENTITY.get(row.get("channel_type"), ())
	return tuple(normalize(_type(channel_fields.get(k, ("Data", None))), row.get(k)) for k in keys)


def merge_channels(incoming, existing, channel_fields, secrets):
	"""Channel rows to save: the document's, each with the row name (which its stored secret belongs
	to) and the secrets of the existing row it matches. Returns `(rows, notes)`.

	A row matches the existing row of its type with the same identity (server and topic, room,
	numbers...). A type without one (Slack, Mattermost, PagerDuty) matches by position, and only
	when the document keeps the same number of rows of that type: after a deletion the order says
	nothing, and a row must never send with another's webhook. A row that matches nothing is new,
	and one missing a secret it needs comes in disabled."""
	unused = [dict(row) for row in existing or []]
	counts = {}
	for row in incoming or []:
		counts[row["channel_type"]] = counts.get(row["channel_type"], 0) + 1
	rows, notes, by_position = [], [], {}
	for j, row in enumerate(incoming or [], 1):
		kind = row["channel_type"]
		values = {name: normalize(_type(spec), row[name] if name in row else _default(spec)) for name, spec in channel_fields.items()}
		values["channel_type"] = kind
		match = None
		if kind in IDENTITY:
			ident = _identity(values, channel_fields)
			match = next((r for r in unused if r.get("channel_type") == kind and _identity(r, channel_fields) == ident), None)
		else:
			same = [r for r in unused if r.get("channel_type") == kind]
			stored = sum(1 for r in existing or [] if r.get("channel_type") == kind)
			if same and stored == counts[kind]:
				match = same[0]
				by_position[kind] = by_position.get(kind, 0) + 1
		if match:
			unused.remove(match)
			if match.get("name"):
				values["name"] = match["name"]
		for secret in _hidden(kind, channel_fields, secrets):
			values[secret] = (match or {}).get(secret) or None
		missing = [s for s in secrets.get(kind, ()) if not values.get(s)]
		if missing and values.get("enabled"):
			values["enabled"] = 0
			notes.append(f"{kind} #{j}: imported disabled, set {', '.join(missing)} in the form, then enable it")
		rows.append(values)
	for kind, n in by_position.items():
		if n > 1:
			notes.append(f"{kind}: {n} rows kept their stored secrets by position: check their order in the form")
	return rows, notes


def changes(current, wanted, fields):
	"""Fields whose value differs between the stored rule and the document's."""
	out = []
	for name, value in wanted.items():
		fieldtype = _type(fields.get(name, ("Data", None)))
		if normalize(fieldtype, current.get(name)) != value:
			out.append(name)
	return sorted(out)


def channel_rows_differ(current_rows, wanted_rows, channel_fields, secrets):
	"""Whether the saved channel rows would change, secrets aside (they cannot be compared: the
	form shows them as asterisks), a row's identity included (a new row, a reused one)."""
	if len(current_rows or []) != len(wanted_rows or []):
		return True
	for a, b in zip(current_rows or [], wanted_rows or []):  # noqa: B905 (same lengths, checked above)
		if a.get("name") != b.get("name"):
			return True
		hidden = _hidden(b.get("channel_type"), channel_fields, secrets)
		for name, spec in channel_fields.items():
			if name not in hidden and normalize(_type(spec), a.get(name)) != b.get(name):
				return True
	return False
