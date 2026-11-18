"""An alert rule read back as plain sentences (no frappe imports, unit tested).

The rule form shows them above its fields and redraws them as they change: what the evaluator
(wolf/rules.py) will do with the rule, in words. `describe` returns a list of sentences, each a
list of `(text, is_value)` parts: a value is a field's content, shown in bold.
"""

from dodock_wolf.wolf import conditions

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
	except (TypeError, ValueError):
		return default


def _number(value):
	try:
		return conditions.format_value(float(value or 0))
	except (TypeError, ValueError):
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
	except (TypeError, ValueError):
		return None
	return t.strftime("%H:%M") if t else None


def _condition(rule):
	"""What is measured and when it breaches, as parts."""
	op = rule.get("operator") or ">"
	threshold = _number(rule.get("threshold"))
	compare = [(" is ", False), (OPERATOR_WORDS.get(op, op), True), (" ", False), (threshold, True)]
	window = [(" over the last ", False), (_minutes(rule.get("window_minutes") or 5), True)]
	kind = rule.get("signal_type") or "metric"
	if kind == "metric":
		aggregation = rule.get("aggregation") or "avg"
		metric = rule.get("metric_name") or "(no metric set)"
		parts = [(AGGREGATION_WORDS.get(aggregation, aggregation), True), (" ", False), (metric, True)]
		return parts + window + compare
	if kind == "sequence":
		first, then = _lines(rule.get("first_categories")), _lines(rule.get("then_categories"))
		entity = ENTITY_WORDS.get(rule.get("sequence_entity") or "ip", rule.get("sequence_entity"))
		parts = [("the same ", False), (entity, True), (" sets off ", False)]
		parts += _either(first) if first else [("(no first category set)", True)]
		if rule.get("first_min_severity"):
			worse = "" if rule["first_min_severity"] == "critical" else " or worse"
			parts += [(" (", False), (rule["first_min_severity"], True), (f"{worse})", False)]
		parts += [(" and then ", False)]
		parts += _either(then) if then else [("(no then category set)", True)]
		parts += [(" within ", False), (_minutes(rule.get("sequence_minutes") or 60), True), (" of it", False)]
		parts += [(", and the number of times it happens", False)] + window + compare
		return parts
	event = rule.get("event_type") or "(no event type set)"
	parts = [("the number of ", False), (event, True), (" events", False)]
	if rule.get("event_category"):
		parts += [(" of category ", False), (rule["event_category"], True)]
	if rule.get("min_severity"):
		worse = "" if rule["min_severity"] == "critical" else " or worse"
		parts += [(" at ", False), (rule["min_severity"], True), (f" severity{worse}", False)]
	return parts + window + compare


def _scope(rule):
	parts = []
	for field, word in (("filter_host", "host"), ("filter_bench", "bench"), ("filter_site", "site")):
		if rule.get(field):
			parts += [(", " if parts else "", False), (word + " ", False), (rule[field], True)]
	return parts


def _channels(rows):
	"""'ntfy and 2 Email' style: the enabled channels by type."""
	counts = {}
	for row in rows or []:
		if _int(row.get("enabled"), 1) and row.get("channel_type"):
			counts[row["channel_type"]] = counts.get(row["channel_type"], 0) + 1
	names = [f"{n} {kind}" if n > 1 else kind for kind, n in counts.items()]
	return names, sum(counts.values()), len(rows or [])


def describe(rule):
	"""The rule as sentences. `rule` is a dict of its fields, with its channel rows as lists."""
	sentences = []
	enabled = _int(rule.get("enabled"), 1)
	opening = "Opens" if enabled else "Disabled: would open"
	head = [(opening + " a ", False), (rule.get("severity") or "warning", True), (" incident when ", False)]
	head += _condition(rule)
	if (rule.get("signal_type") or "metric") != "sequence":
		head += [(", ", False), (GROUP_WORDS.get(rule.get("group_by") or "none", rule.get("group_by")), True)]
	scope = _scope(rule)
	if scope:
		head += [(", only for ", False)] + scope
	sentences.append(head + [(".", False)])

	when = []
	min_samples = _int(rule.get("min_samples"), 1)
	if (rule.get("signal_type") or "metric") == "metric" and min_samples > 1:
		when.append([("It needs at least ", False), (str(min_samples), True), (" samples in the window.", False)])
	start, end = _hhmm(rule.get("active_from")), _hhmm(rule.get("active_to"))
	if start and end:
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
			op = rule.get("operator") or ">"
			back = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}.get(op)
			if back:
				resolve += [(" once the value is ", False), (OPERATOR_WORDS[back], True), (" ", False),
				            (_number(rule.get("resolve_threshold")), True)]  # fmt: skip
		else:
			resolve += [(" once the condition no longer holds", False)]
		resolve_after = max(_int(rule.get("resolve_after_evaluations"), 1), 1)
		if resolve_after > 1:
			resolve += [(" for ", False), (f"{resolve_after} evaluations", True), (" in a row", False)]
		cooldown = _int(rule.get("cooldown_minutes"))
		if cooldown > 0:
			resolve += [("; matching again within ", False), (_minutes(cooldown), True),
			            (" reopens the same incident", False)]  # fmt: skip
		sentences.append(resolve + [(".", False)])
	else:
		sentences.append([("It stays open until someone resolves it.", False)])

	names, enabled_count, total = _channels(rule.get("channels"))
	if enabled_count:
		notify = [("It notifies ", False)] + _either(names, " and ")
		if _int(rule.get("notify_on_resolve"), 1):
			notify += [(", and again when it resolves", False)]
	elif total:
		notify = [("Its channels are all disabled: it notifies nobody", False)]
	else:
		notify = [("It notifies nobody: the incident shows in Wolf only", False)]
	sentences.append(notify + [(".", False)])
	escalate = _int(rule.get("escalate_after_minutes"))
	esc_names, esc_count, _ = _channels(rule.get("escalation_channels"))
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
