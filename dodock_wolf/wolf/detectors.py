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
  external source has reported from the same host in the last FALLBACK_MINUTES: when Suricata
  or Wazuh goes quiet, Wolf's detection comes back by itself.
"""

MODES = ("own", "both", "external")
FALLBACK_MINUTES = 60
DETECTORS = {
	"web": {"setting": "web_detection_mode", "own": ("web_attack_probe",), "external": ("network_ids_alert",)},
	"host": {
		"setting": "host_detection_mode",
		"own": ("ssh_failed_login", "ssh_root_login", "ssh_login_after_failures", "sudo_failure", "account_created",
		        "admin_group_change"),  # fmt: skip
		"external": ("hids_alert",),
	},
}
SOURCE_LABELS = {"suricata": "Suricata", "wazuh": "Wazuh", "frappe": "Wolf site", "wolf": "Wolf site", "api": "Wolf site",
                 "scheduler": "Wolf site", "deployment": "Wolf site"}  # fmt: skip


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
