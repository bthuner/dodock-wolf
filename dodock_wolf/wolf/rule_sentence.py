"""An alert rule read back as plain sentences (no frappe imports, unit tested).

The rule form shows them above its fields and redraws them as they change: what the evaluator
(wolf/rules.py) will do with the rule, in words. `describe` returns a list of sentences, each a
list of `(text, is_value)` parts: a value is a field's content, shown in bold.

Every sentence is a template with numbered placeholders, translated whole by the `_` the caller
passes (frappe._ in the form): word order differs between languages, so pieces are never glued
together. Frappe's extractor reads the `_("...")` literals of this file.
"""

import re

from dodock_wolf.wolf import conditions
from dodock_wolf.wolf.channels import STATEFUL

_PLACEHOLDER = re.compile(r"\{(\d+)\}")


def _english(text):
	return text


def _operator_words(_):
	return {">": _("above"), ">=": _("at least"), "<": _("below"), "<=": _("at most"), "==": _("exactly"),
	        "!=": _("anything but")}  # fmt: skip


def _aggregation_templates(_):
	return {"avg": _("the average of {0}"), "min": _("the lowest {0}"), "max": _("the highest {0}"),
	        "sum": _("the sum of {0}"), "count": _("the number of samples of {0}"), "last": _("the latest {0}")}  # fmt: skip


def _group_words(_):
	return {"none": _("across everything it watches"), "host": _("per host"), "bench": _("per bench"),
	        "site": _("per site"), "host_label": _("per host and series (a disk, a queue...)")}  # fmt: skip


def _entity_words(_):
	return {"ip": _("IP address"), "user": _("user"), "host": _("host")}


def fill(template, *args):
	"""Parts of a translated template: its own text plain, each argument in its placeholder. A
	string argument is a value (bold); a list is parts already built."""
	parts, at = [], 0
	for match in _PLACEHOLDER.finditer(template):
		if match.start() > at:
			parts.append((template[at : match.start()], False))
		i = int(match.group(1))
		arg = args[i] if i < len(args) else match.group(0)
		parts += arg if isinstance(arg, list) else [(str(arg), True)]
		at = match.end()
	if at < len(template):
		parts.append((template[at:], False))
	return parts


def _int(value, default=0):
	try:
		return int(float(value))
	except (TypeError, ValueError, OverflowError):
		return default


def _word(table, value, default):
	"""A field's value in words: the table's, else the value itself (a form being edited may hold anything)."""
	key = default if value in (None, "") else str(value)
	return table.get(key, key)


def _number(value):
	try:
		return conditions.format_value(float(value or 0))
	except (TypeError, ValueError, OverflowError):
		return str(value)


def _minutes(value, _):
	n = max(_int(value), 0)
	if n and n % 1440 == 0:
		return (_("{0} day") if n == 1440 else _("{0} days")).format(n // 1440)
	if n and n % 60 == 0:
		return _("{0} h").format(n // 60)
	return _("{0} min").format(n)


def _lines(value):
	return [line.strip() for line in str(value or "").replace(",", "\n").splitlines() if line.strip()]


def _either(values, _, both=False):
	"""['a', 'b', 'c'] → parts for 'a, b or c' ('a, b and c' with `both`), each a value."""
	if not values:
		return []
	if len(values) == 1:
		return [(values[0], True)]
	head = []
	for i, v in enumerate(values[:-1]):
		head += ([(", ", False)] if i else []) + [(v, True)]
	return fill(_("{0} and {1}") if both else _("{0} or {1}"), head, values[-1])


def _hhmm(value):
	try:
		t = conditions.to_time(value)
	except (TypeError, ValueError, OverflowError):
		return None
	return t.strftime("%H:%M:%S" if t.second else "%H:%M") if t else None


def _severity_filter(phrase, severity, _):
	if not severity:
		return phrase
	if severity == "critical":
		return fill(_("{0} at {1} severity"), phrase, str(severity))
	return fill(_("{0} at {1} severity or worse"), phrase, str(severity))


def _condition(rule, _):
	"""What is measured and when it breaches, as parts."""
	threshold = _number(rule.get("threshold"))
	operator = _word(_operator_words(_), rule.get("operator"), ">")
	window_minutes = 5 if rule.get("window_minutes") is None else _int(rule.get("window_minutes"))  # the DocType default
	window = _minutes(window_minutes, _) if window_minutes >= 1 else _("(no window set)")
	kind = _kind(rule)
	if kind == "sequence":
		first, then = _lines(rule.get("first_categories")), _lines(rule.get("then_categories"))
		first_parts = _either(first, _) if first else [(_("(no first category set)"), True)]
		severity = rule.get("first_min_severity")
		if severity:
			template = _("{0} ({1})") if severity == "critical" else _("{0} ({1} or worse)")
			first_parts = fill(template, first_parts, str(severity))
		then_parts = _either(then, _) if then else [(_("(no then category set)"), True)]
		return fill(
			_("the same {0} sets off {1} and then {2} within {3} of it, and the number of times it happens over the last {4} is {5} {6}"),
			_word(_entity_words(_), rule.get("sequence_entity"), "ip"), first_parts, then_parts,
			_minutes(rule.get("sequence_minutes") or 60, _), window, operator, threshold,
		)  # fmt: skip
	if kind == "metric":
		metric = str(rule.get("metric_name") or _("(no metric set)"))
		measured = fill(_word(_aggregation_templates(_), rule.get("aggregation"), "avg"), metric)
	else:
		measured = fill(_("the number of {0} events"), str(rule.get("event_type") or _("(no event type set)")))
		if rule.get("event_category"):
			measured = fill(_("{0} of category {1}"), measured, str(rule["event_category"]))
		measured = _severity_filter(measured, rule.get("min_severity"), _)
	return fill(_("{0} over the last {1} is {2} {3}"), measured, window, operator, threshold)


def _scope(rule, _):
	words = {"filter_host": _("host {0}"), "filter_bench": _("bench {0}"), "filter_site": _("site {0}")}
	parts = []
	for field, template in words.items():
		if rule.get(field):
			parts += ([(", ", False)] if parts else []) + fill(template, str(rule[field]))
	return parts


def _rows(value):
	return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _channels(rows, severity, _):
	"""'ntfy and 2 Email' style: the enabled channels by type, those batched into the hourly digest
	(below critical, conditions.should_digest) apart."""
	counts = {}
	for row in rows:
		if _int(row.get("enabled"), 1) and row.get("channel_type"):
			hourly = row.get("digest") == "hourly" and severity != "critical"
			key = (str(row["channel_type"]), hourly)
			counts[key] = counts.get(key, 0) + 1
	names = []
	for (kind, hourly), n in counts.items():
		name = f"{n} {kind}" if n > 1 else kind
		names.append(_("{0} (in the hourly digest)").format(name) if hourly else name)
	stateful = sorted({kind for kind, _hourly in counts if kind in STATEFUL})
	return names, sum(counts.values()), stateful


def _kind(rule):
	kind = str(rule.get("signal_type") or "metric")
	return kind if kind in ("metric", "event", "sequence") else "metric"


def describe(rule, _=None):
	"""The rule as sentences. `rule` is a dict of its fields, with its channel rows as lists; `_`
	translates a template (English when none is given)."""
	_ = _ or _english
	sentences = []
	enabled = _int(rule.get("enabled"), 1)
	severity = str(rule.get("severity") or "warning")
	opening = _("Opens a {0} incident when {1}") if enabled else _("Disabled: would open a {0} incident when {1}")
	head = fill(opening, severity, _condition(rule, _))
	if _kind(rule) != "sequence":
		head += [(", ", False), (_word(_group_words(_), rule.get("group_by"), "none"), True)]
	scope = _scope(rule, _)
	if scope:
		head += [(", ", False)] + fill(_("only for {0}"), scope)
	sentences.append(head + [(".", False)])

	min_samples = _int(rule.get("min_samples"), 1)
	if min_samples > 1:  # the evaluator applies it to every kind (rules.evaluate)
		template = {
			"metric": _("It needs at least {0} samples in the window."),
			"event": _("It needs at least {0} distinct events in the window."),
			"sequence": _("It needs at least {0} occurrences in the window."),
		}[_kind(rule)]
		sentences.append(fill(template, str(min_samples)))
	start, end = _hhmm(rule.get("active_from")), _hhmm(rule.get("active_to"))
	if start and end and start == end:  # [from, to) is empty: conditions.in_active_window
		sentences.append(fill(_("It is never checked: Active From and Active To are both {0}."), start))
	elif start and end:
		template = (_("It is checked only between {0} and {1} (over midnight), server time.") if start > end
		            else _("It is checked only between {0} and {1}, server time."))  # fmt: skip
		sentences.append(fill(template, start, end))
	if _int(rule.get("require_recent_deployment")):
		minutes = _int(rule.get("deployment_window_minutes")) or 30
		sentences.append(fill(_("It fires only within {0} of a deployment."), _minutes(minutes, _)))
	fire_after = max(_int(rule.get("fire_after_evaluations"), 1), 1)
	if fire_after > 1:
		sentences.append(fill(_("It waits until the condition holds {0} in a row."), _("{0} evaluations").format(fire_after)))

	if _int(rule.get("auto_resolve"), 1):
		back = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}.get(str(rule.get("operator") or ">"))
		if not _int(rule.get("use_resolve_threshold")):
			resolve = fill(_("It resolves by itself once the condition no longer holds"))
		elif back:
			resolve = fill(_("It resolves by itself once the value is {0} {1}"), _operator_words(_)[back],
			               _number(rule.get("resolve_threshold")))  # fmt: skip
		else:
			resolve = fill(_("It resolves by itself"))
		resolve_after = max(_int(rule.get("resolve_after_evaluations"), 1), 1)
		if resolve_after > 1:
			resolve = fill(_("{0} for {1} in a row"), resolve, _("{0} evaluations").format(resolve_after))
	else:
		resolve = fill(_("It stays open until someone resolves it"))
	cooldown = _int(rule.get("cooldown_minutes"))
	if cooldown > 0:  # whoever resolved it (incidents.open_incident)
		resolve = fill(_("{0}; if it matches again within {1} of being resolved, the same incident reopens"), resolve,
		               _minutes(cooldown, _))  # fmt: skip
	sentences.append(resolve + [(".", False)])

	channels = _rows(rule.get("channels"))
	names, enabled_count, stateful = _channels(channels, severity, _)
	if enabled_count:
		notify = fill(_("It notifies {0}"), _either(names, _, both=True))
		if _int(rule.get("notify_on_resolve"), 1):
			notify = fill(_("{0}, and again when it resolves"), notify)
		elif stateful:  # they close their own alert (rules.evaluate, notify.on_status_change)
			notify = fill(_("{0} ({1} still hears when it is acknowledged or resolved)"), notify, _either(stateful, _, both=True))
		sentences.append(notify + [(".", False)])
	elif channels:
		sentences.append(fill(_("Its channels are all disabled: it notifies nobody.")))
	else:
		sentences.append(fill(_("It notifies nobody: the incident shows in Wolf only.")))
	escalate = _int(rule.get("escalate_after_minutes"))
	esc_names, esc_count, _stateful = _channels(_rows(rule.get("escalation_channels")), severity, _)
	if escalate > 0 and esc_count:
		sentences.append(fill(_("Not acknowledged after {0}, it also notifies {1}."), _minutes(escalate, _),
		                      _either(esc_names, _, both=True)))  # fmt: skip
	elif escalate > 0:
		sentences.append(fill(_("It would escalate after {0}, but has no enabled escalation channel."), _minutes(escalate, _)))
	return sentences


def as_text(sentences):
	"""Plain text, for tests and logs."""
	return " ".join("".join(text for text, _value in s) for s in sentences)
