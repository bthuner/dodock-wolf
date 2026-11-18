"""Where Wolf's own detectors overlap Suricata and Wazuh, and what each mode does (no frappe imports;
#72 step 4).

Two overlaps, each with a mode in Wolf Settings:

- `web`: the agent's nginx web probes (`web_attack_probe`) and Suricata (`network_ids_alert`);
- `host`: the agent's auth.log signals (SSH logins and failures, sudo, accounts) and Wazuh
  (`hids_alert`).

Modes:

- `own` (default): as before, both are stored and counted on their own; Wolf works alone.
- `both`: a Wolf event and an external alert about the same remote IP, with a common ATT&CK
  technique when both name some, within Detector Match Minutes, are one finding with two
  sources. The later one is stored as `duplicate_of` the first: still on the timeline and in
  its own rules, not sent again to CrowdSec or the SIEM.
- `external`: Wolf's own events of that detector are dropped at ingest, but only while the
  external source has sent, about the same host (any of its names), an alert that `covers` the
  detector in the last FALLBACK_MINUTES: a Wazuh file-integrity alert does not stand in for SSH
  detection. When Suricata or Wazuh goes quiet, Wolf's detection comes back by itself.
"""

import re

from dodock_wolf.wolf import attack

MODES = ("own", "both", "external")
FALLBACK_MINUTES = 60
DETECTORS = {
	"web": {"setting": "web_detection_mode", "own": ("web_attack_probe",), "external": ("network_ids_alert",)},
	"host": {
		"setting": "host_detection_mode",
		"own": ("ssh_failed_login", "ssh_root_login", "ssh_login_after_failures", "sudo_failure", "account_created",
		        "service_account_created", "admin_group_change"),  # fmt: skip
		"external": ("hids_alert",),
	},
}
SOURCE_LABELS = {"suricata": "Suricata", "wazuh": "Wazuh", "frappe": "Wolf site", "wolf": "Wolf site", "api": "Wolf site",
                 "scheduler": "Wolf site", "deployment": "Wolf site"}  # fmt: skip


# Wazuh groups of the rules that see what auth.log signals see (SSH, sudo, PAM, accounts)
HOST_GROUPS = {"authentication_failed", "authentication_failures", "authentication_success", "sshd", "sudo",
               "pam", "adduser", "addgroup", "account_changed", "invalid_login"}  # fmt: skip
_HTTP_KEY = re.compile(r"^http_")


# techniques of the web probe rules (agent/wolf_agent/parsers/web_attacks.py), beyond the category's
WEB_RULE_TECHNIQUES = {"T1190", "T1189", "T1552", "T1110"}


def own_techniques(detector):
	"""Base ATT&CK techniques Wolf's own detector names (attack.CATEGORIES, plus its web rules')."""
	ids = {t.split(".")[0] for c in DETECTORS[detector]["own"] for t in attack.CATEGORIES.get(c, [])}
	return ids | WEB_RULE_TECHNIQUES if detector == "web" else ids


def covers(detector, payload):
	"""Whether an external alert shows its source watches what Wolf's detector watches: a web alert
	with HTTP context or a web technique; a host alert of an authentication, sudo or account rule,
	or with one of the auth signals' techniques."""
	payload = payload if isinstance(payload, dict) else {}
	if techniques(payload) & own_techniques(detector):
		return True
	if detector == "web":
		return payload.get("app_proto") == "http" or any(_HTTP_KEY.match(k) for k in payload)
	return bool(HOST_GROUPS.intersection(g.lower() for g in payload.get("groups") or [] if isinstance(g, str)))


def detector_of(category):
	"""(detector, side) of a category, side "own" or "external"; (None, None) elsewhere."""
	for name, d in DETECTORS.items():
		for side in ("own", "external"):
			if category in d[side]:
				return name, side
	return None, None


def mode(settings, detector):
	value = (settings.get(DETECTORS[detector]["setting"]) or "own") if detector else "own"
	return value if value in MODES else "own"


def other_side(detector, side):
	return DETECTORS[detector]["external" if side == "own" else "own"]


def techniques(payload):
	"""Base ATT&CK technique ids of a payload (`T1110.001` counts as `T1110`)."""
	out = set()
	for t in (payload or {}).get("mitre_attack") or []:
		tid = t.get("id") if isinstance(t, dict) else t
		if tid:
			out.add(str(tid).split(".")[0].upper())
	return out


def same_finding(payload, other_payload):
	"""Two events about the same remote IP are one finding unless both name ATT&CK techniques and
	none is common."""
	mine, theirs = techniques(payload), techniques(other_payload)
	return not (mine and theirs) or bool(mine & theirs)


def source_label(source):
	"""Who raised an event, for display: Suricata, Wazuh, the Wolf site or the Wolf agent."""
	return SOURCE_LABELS.get((source or "").lower(), "Wolf agent")
