"""An alert rule read back as plain sentences (no frappe imports, unit tested).

The rule form shows them above its fields and redraws them as they change: what the evaluator
(wolf/rules.py) will do with the rule, in words. `describe` returns a list of sentences, each a
list of `(text, is_value)` parts: a value is a field's content, shown in bold.
"""

from dodock_wolf.wolf import conditions
from dodock_wolf.wolf.channels import STATEFUL

OPERATOR_WORDS = {
	">": "above",
	">=": "at least",
	"<": "below",
	"<=": "at most",
	"==": "exactly",
	"!=": "anything but",
}
AGGREGATION_WORDS = {
	"avg": "the average of",
	"min": "the lowest",
	"max": "the highest",
	"sum": "the sum of",
	"count": "the number of samples of",
	"last": "the latest",
}
GROUP_WORDS = {
	"none": "across everything it watches",
	"host": "per host",
	"bench": "per bench",
	"site": "per site",
	"host_label": "per host and series (a disk, a queue...)",
}
ENTITY_WORDS = {"ip": "IP address", "user": "user", "host": "host"}


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


def _minutes(value):
	n = max(_int(value), 0)
	if n and n % 1440 == 0:
		return f"{n // 1440} day" + ("s" if n > 1440 else "")
	if n and n % 60 == 0:
		return f"{n // 60} h"
	return f"{n} min"


def _times(n):
	return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def _lines(value):
	return [line.strip() for line in str(value or "").replace(",", "\n").splitlines() if line.strip()]


def _either(values, last=" or "):
	"""['a', 'b', 'c'] → parts for 'a, b or c', each a value."""
	parts = []
	for i, v in enumerate(values):
		if i:
			parts.append((last if i == len(values) - 1 else ", ", False))
		parts.append((v, True))
	return parts


def _hhmm(value):
	try:
		t = conditions.to_time(value)
	except (TypeError, ValueError, OverflowError):
		return None
	return t.strftime("%H:%M:%S" if t.second else "%H:%M") if t else None


def _condition(rule):
	"""What is measured and when it breaches, as parts."""
	threshold = _number(rule.get("threshold"))
	compare = [(" is ", False), (_word(OPERATOR_WORDS, rule.get("operator"), ">"), True), (" ", False), (threshold, True)]
	window_minutes = 5 if rule.get("window_minutes") is None else _int(rule.get("window_minutes"))  # the DocType default
	window = [(" over the last ", False), (_minutes(window_minutes) if window_minutes >= 1 else "(no window set)", True)]
	kind = _kind(rule)
	if kind == "metric":
		metric = str(rule.get("metric_name") or "(no metric set)")
		parts = [(_word(AGGREGATION_WORDS, rule.get("aggregation"), "avg"), True), (" ", False), (metric, True)]
		return parts + window + compare
	if kind == "sequence":
		first, then = _lines(rule.get("first_categories")), _lines(rule.get("then_categories"))
		entity = _word(ENTITY_WORDS, rule.get("sequence_entity"), "ip")
		parts = [("the same ", False), (entity, True), (" sets off ", False)]
		parts += _either(first) if first else [("(no first category set)", True)]
		if rule.get("first_min_severity"):
			worse = "" if rule["first_min_severity"] == "critical" else " or worse"
			parts += [(" (", False), (str(rule["first_min_severity"]), True), (f"{worse})", False)]
		parts += [(" and then ", False)]
		parts += _either(then) if then else [("(no then category set)", True)]
		parts += [(" within ", False), (_minutes(rule.get("sequence_minutes") or 60), True), (" of it", False)]
		parts += [(", and the number of times it happens", False)] + window + compare
		return parts
	event = str(rule.get("event_type") or "(no event type set)")
	parts = [("the number of ", False), (event, True), (" events", False)]
	if rule.get("event_category"):
		parts += [(" of category ", False), (str(rule["event_category"]), True)]
	if rule.get("min_severity"):
		worse = "" if rule["min_severity"] == "critical" else " or worse"
		parts += [(" at ", False), (str(rule["min_severity"]), True), (f" severity{worse}", False)]
	return parts + window + compare


def _scope(rule):
	parts = []
	for field, word in (("filter_host", "host"), ("filter_bench", "bench"), ("filter_site", "site")):
		if rule.get(field):
			parts += [(", " if parts else "", False), (word + " ", False), (str(rule[field]), True)]
	return parts


def _rows(value):
	return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _channels(rows, severity):
	"""'ntfy and 2 Email' style: the enabled channels by type, those batched into the hourly digest
	(below critical, conditions.should_digest) apart."""
	counts = {}
	for row in rows:
		if _int(row.get("enabled"), 1) and row.get("channel_type"):
			hourly = row.get("digest") == "hourly" and severity != "critical"
			key = (str(row["channel_type"]), hourly)
			counts[key] = counts.get(key, 0) + 1
	names = [(f"{n} {kind}" if n > 1 else kind) + (" (in the hourly digest)" if hourly else "") for (kind, hourly), n in counts.items()]
	stateful = sorted({kind for kind, _hourly in counts if kind in STATEFUL})
	return names, sum(counts.values()), stateful


def _kind(rule):
	kind = str(rule.get("signal_type") or "metric")
	return kind if kind in ("metric", "event", "sequence") else "metric"


def describe(rule):
	"""The rule as sentences. `rule` is a dict of its fields, with its channel rows as lists."""
	sentences = []
	enabled = _int(rule.get("enabled"), 1)
	opening = "Opens" if enabled else "Disabled: would open"
	severity = str(rule.get("severity") or "warning")
	head = [(opening + " a ", False), (severity, True), (" incident when ", False)]
	head += _condition(rule)
	if _kind(rule) != "sequence":
		head += [(", ", False), (_word(GROUP_WORDS, rule.get("group_by"), "none"), True)]
	scope = _scope(rule)
	if scope:
		head += [(", only for ", False)] + scope
	sentences.append(head + [(".", False)])

	when = []
	min_samples = _int(rule.get("min_samples"), 1)
	if min_samples > 1:  # the evaluator applies it to every kind (rules.evaluate)
		counted = {"metric": "samples", "event": "distinct events", "sequence": "occurrences"}[_kind(rule)]
		when.append([("It needs at least ", False), (str(min_samples), True), (f" {counted} in the window.", False)])
	start, end = _hhmm(rule.get("active_from")), _hhmm(rule.get("active_to"))
	if start and end and start == end:  # [from, to) is empty: conditions.in_active_window
		when.append([("It is never checked: Active From and Active To are both ", False), (start, True), (".", False)])
	elif start and end:
		wrap = " (over midnight)" if start > end else ""
		when.append([("It is checked only between ", False), (start, True), (" and ", False), (end, True),
		             (f"{wrap}, server time.", False)])  # fmt: skip
	if _int(rule.get("require_recent_deployment")):
		minutes = _int(rule.get("deployment_window_minutes")) or 30
		when.append([("It fires only within ", False), (_minutes(minutes), True), (" of a deployment.", False)])
	fire_after = max(_int(rule.get("fire_after_evaluations"), 1), 1)
	if fire_after > 1:
		when.append([("It waits until the condition holds ", False), (f"{fire_after} evaluations", True),
		             (" in a row.", False)])  # fmt: skip
	sentences += when

	if _int(rule.get("auto_resolve"), 1):
		resolve = [("It resolves by itself", False)]
		if _int(rule.get("use_resolve_threshold")):
			op = str(rule.get("operator") or ">")
			back = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}.get(op)
			if back:
				resolve += [(" once the value is ", False), (OPERATOR_WORDS[back], True), (" ", False),
				            (_number(rule.get("resolve_threshold")), True)]  # fmt: skip
		else:
			resolve += [(" once the condition no longer holds", False)]
		resolve_after = max(_int(rule.get("resolve_after_evaluations"), 1), 1)
		if resolve_after > 1:
			resolve += [(" for ", False), (f"{resolve_after} evaluations", True), (" in a row", False)]
	else:
		resolve = [("It stays open until someone resolves it", False)]
	cooldown = _int(rule.get("cooldown_minutes"))
	if cooldown > 0:  # whoever resolved it (incidents.open_incident)
		resolve += [("; if it matches again within ", False), (_minutes(cooldown), True),
		            (" of being resolved, the same incident reopens", False)]  # fmt: skip
	sentences.append(resolve + [(".", False)])

	channels = _rows(rule.get("channels"))
	names, enabled_count, stateful = _channels(channels, severity)
	if enabled_count:
		notify = [("It notifies ", False)] + _either(names, " and ")
		if _int(rule.get("notify_on_resolve"), 1):
			notify += [(", and again when it resolves", False)]
		elif stateful:  # they close their own alert (rules.evaluate, notify.on_status_change)
			notify += [(" (", False)] + _either(stateful, " and ") + [(" still hears when it is acknowledged or resolved)", False)]
	elif channels:
		notify = [("Its channels are all disabled: it notifies nobody", False)]
	else:
		notify = [("It notifies nobody: the incident shows in Wolf only", False)]
	sentences.append(notify + [(".", False)])
	escalate = _int(rule.get("escalate_after_minutes"))
	esc_names, esc_count, _ = _channels(_rows(rule.get("escalation_channels")), severity)
	if escalate > 0 and esc_count:
		sentences.append([("Not acknowledged after ", False), (_minutes(escalate), True), (", it also notifies ", False)]
		                 + _either(esc_names, " and ") + [(".", False)])  # fmt: skip
	elif escalate > 0:
		sentences.append([("It would escalate after ", False), (_minutes(escalate), True),
		                  (", but has no enabled escalation channel.", False)])  # fmt: skip
	return sentences


def as_text(sentences):
	"""Plain text, for tests and logs."""
	return " ".join("".join(text for text, _value in s) for s in sentences)
