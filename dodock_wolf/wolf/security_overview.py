"""The pure parts of the Wolf UI's home page (api/security_overview.py), without frappe imports.

Each panel reads what Wolf already stores: the hourly `security_score` samples, the security
incidents, the response actions, the journal's signing and the agents' reports. Nothing here
grades a score or invents a threshold for it; the only times are the jobs' own cadence.
"""

from datetime import timedelta

# record_security_scores runs hourly: a score older than this means runs were missed
SCORE_LATE = timedelta(hours=3)
# chain_journal signs every minute: an entry still unsigned after this means signing is behind
SIGNING_LATE = timedelta(minutes=5)
# "about 24 h earlier": the newest score between 25 h and 23 h ago
BEFORE_SINCE, BEFORE_UNTIL = timedelta(hours=25), timedelta(hours=23)
SEVERITIES = ("critical", "warning", "info")
AGENT_STATES = ("fresh", "stale", "never_seen", "disabled")


def score_rows(sites, current, previous, now):
	"""One row per site, worst score first, then the sites not scored yet (never shown as 0).

	`sites`: the sites known to the security page; `current`: {site: (score, at)}, the newest
	score; `previous`: {site: score} about 24 h earlier, when one was recorded then. A current
	score no newer than that window (the job stopped) would be compared with itself: no change
	is claimed then.
	"""
	rows = []
	for site in sorted(set(sites) | set(current)):
		if site not in current:
			rows.append({"site": site, "score": None, "at": None, "late": False, "change": None})
			continue
		value, at = current[site]
		score = int(round(value))
		before = previous.get(site)
		comparable = before is not None and at is not None and at > now - BEFORE_UNTIL
		rows.append({
			"site": site, "score": score, "at": at, "late": at is not None and now - at > SCORE_LATE,
			"change": score - int(round(before)) if comparable else None,
		})  # fmt: skip
	rows.sort(key=lambda r: (r["score"] is None, r["score"] or 0, r["site"]))
	return rows


def severity_counts(rows):
	"""{critical, warning, info, total} from (severity, count) pairs; an empty severity is info."""
	out = dict.fromkeys(SEVERITIES, 0)
	for severity, n in rows:
		key = severity if severity in out else "info"
		out[key] += int(n or 0)
	out["total"] = sum(out[s] for s in SEVERITIES)
	return out


def journal_state(last_seq, last_at, pending, oldest_pending_at, now):
	"""The journal's signing at a glance: the newest signed entry, the entries waiting, and
	whether signing is behind (an entry has waited longer than SIGNING_LATE)."""
	return {
		"last_seq": int(last_seq or 0) or None,
		"last_at": last_at if last_seq else None,
		"pending": int(pending or 0),
		"oldest_pending_at": oldest_pending_at if pending else None,
		"behind": bool(pending and oldest_pending_at and now - oldest_pending_at > SIGNING_LATE),
	}


def agent_summary(agents):
	"""Counts per state of the host agents and of the satellites, and the reporting hosts whose
	last setup check (`wolf-agent doctor`) found something to fix, as the Monitoring page shows.

	`agents`: rows of api/dashboard.monitored_agents (kind, state, hostname, setup)."""
	counts = {kind: dict.fromkeys(AGENT_STATES, 0) for kind in ("agent", "satellite")}
	to_fix, reported = [], 0
	for a in agents:
		kind = a.get("kind") or "agent"
		state = a.get("state")
		if kind in counts and state in counts[kind]:
			counts[kind][state] += 1
		setup = a.get("setup")
		if kind != "agent" or state != "fresh" or not setup:
			continue
		reported += 1
		if setup.get("failed") or setup.get("warnings"):
			to_fix.append({"hostname": a.get("hostname"), "failed": setup.get("failed") or 0, "warnings": setup.get("warnings") or 0})
	for kind in counts:
		counts[kind]["total"] = sum(counts[kind][s] for s in AGENT_STATES)
	return {"agents": counts["agent"], "satellites": counts["satellite"], "setup_reported": reported,
	        "to_fix": sorted(to_fix, key=lambda h: str(h["hostname"]))}  # fmt: skip
