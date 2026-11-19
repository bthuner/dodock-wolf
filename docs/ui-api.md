# Wolf UI API

Read APIs behind the Wolf UI (`/wolf`, [#19](https://github.com/bthuner/dodock-wolf/issues/19)).
They need the Wolf User, Wolf Manager or System Manager role, and apply the caller's access
rules (see [Privacy and access](../README.md#privacy-and-access)) inside the query. Answers are
not cached, so each one is the caller's own.

## Common arguments

### Time window

| Argument | Meaning |
|---|---|
| `range` | Relative window ending now: a number and `m`, `h` or `d`, such as `15m`, `24h`, `7d`. Default `24h`. |
| `since`, `until` | Explicit window, ISO 8601. A time without an offset is read as UTC, as in the agent protocol. `until` defaults to now and needs `since`. They win over `range`. |

A relative window is measured in real time, so across a DST change `24h` is 24 hours, not 23
or 25 hours of wall clock. Windows longer than 400 days, or with `since` after `until`, are
refused. The Desk overview APIs (`api/ui.py`) accept the same `range` values. Every response that
reads a window returns what it actually read, in UTC:

```json
"window": {"since": "2026-10-29T13:00:00Z", "until": "2026-10-30T13:00:00Z", "relative": "24h", "time_zone": "Europe/Paris"}
```

In the Wolf UI, the window is in the URL (`?range=7d` or `?since=…&until=…`). A range selected on
the HTTP chart of a dashboard becomes an explicit
`since`/`until`: the dashboard's counts and chart, and the event and error explorers opened from
it, are read with it. **Back to a relative window** drops it.

`time_zone` is the site's. Stored times are in that zone; the UI converts with it, never with
the browser's zone.

### Scope

`site`, `bench`, `host` narrow a query to records with those values. **`bench` needs `host`**:
bench names such as `frappe-bench` repeat across hosts, so a bench alone is ambiguous and
refused.

### Access

A restricted Wolf User (one with Wolf User Scope rows) gets counts and inventory over the
records they may see, and `"restricted": true`. A Wolf User **without any** Wolf User Scope
row is not restricted: they see everything, as in Desk. That is the current rule, kept as is.

## Home page: `dodock_wolf.api.security_overview.get_overview`

The Wolf UI opens on the security of the bench (`/wolf`, **Overview**); the general overview it
used to show is **Operations** (`/wolf/operations`, `get_counts` and `get_inventory` below), frozen
with the rest of observability ([#136](https://github.com/bthuner/dodock-wolf/issues/136)).

No argument. One answer with a key per panel, each within the caller's access. A panel the caller
may not have is `null`; one that could not be read is `{"error": "…"}` (the reason goes to the
Error Log) or `{"forbidden": true}`, and the others are still answered. `satellite` is true on a
satellite, which records no score and keeps no incidents: `scores`, `incidents` and `responses` are
then `null`, and the page says that the scores are kept on the central site.

| Panel | What it reads |
|---|---|
| `scores` | The stored `security_score` of each site the caller may see by a site grant, as `security.list_sites` (a score is stored with its site's host, but a host grant does not show it): the newest sample of the last 7 days (`site`, `score`, `at`), never recomputed. `change` is the difference with the newest score of 23 to 25 h earlier, `null` when there is none or when the newest is not newer than 23 h; `late` when the newest is over 3 h old (the job is hourly). Worst first; a site `security.list_sites` knows but that has no score yet comes last with `score: null`, never 0. |
| `incidents` | Open or Acknowledged incidents holding at least one `security` event, merged ones excluded, under the incident access rules: `by_severity` (with `total`), `by_status`, and the 5 `newest`. `null` on a satellite. |
| `responses` | Wolf Response Actions `waiting` (Approved and not expired: for the agent or satellite that applies them) and `failed` in the last `failed_days` (7), with the 5 `newest` (`label`, `status`, `incident`, `result`, `at`); a user action waiting for a satellite names its site in `label`. Wolf Managers and System Managers only, else `null`. |
| `journal` | `last_seq` and `last_at` of the newest signed entry, `pending`, `oldest_pending_at`, and `behind` when an entry has waited over 5 minutes (signing runs every minute); `key`. Wolf Managers and System Managers only, else `null`. |
| `agents` | `agents` and `satellites` per state (`fresh`, `stale`, `never_seen`, `disabled`, `total`) and `to_fix`, the reporting hosts whose last `wolf-agent doctor` run found a failure or a warning (as `get_monitoring` reports it), with `silence_minutes`. |

## `dodock_wolf.api.scope.get_counts`

Exact counts for Operations and the entity dashboards. Arguments: window and scope.

```json
{
  "window": {...},
  "scope": {"host": "bench-01"},
  "restricted": false,
  "incidents": {
    "unresolved": 60, "unacknowledged": 40, "critical_unresolved": 7,
    "by_status": {"Open": 40, "Acknowledged": 20},
    "by_severity": {"info": 0, "warning": 53, "critical": 7},
    "sites_with_unresolved": 1, "unresolved_without_site": 5,
    "opened_in_window": 61, "resolved_in_window": 1,
    "basis": "..."
  },
  "events": {"records": 12, "occurrences": 140, "by_type": {"error": {"records": 3, "occurrences": 90, "by_severity": {...}}}, "basis": "..."},
  "agents": {"agent": {"fresh": 3, "stale": 1, "never_seen": 0, "disabled": 0}, "satellite": {...}, "silence_minutes": 5, "basis": "..."}
}
```

- **Incidents:** `unresolved` counts Open and Acknowledged incidents now, whatever the window.
  `unacknowledged` is Open only. Merged incidents are excluded. `unresolved_without_site`
  counts host- or bench-wide incidents, which have no site. `opened_in_window` and
  `resolved_in_window` use `started_at` and `resolved_at`.
- **Events:** `records` are Wolf Events first seen in the window. `occurrences` sums their
  reported `count`. A deduplicated record keeps counting repeats, including repeats after the
  window, so `occurrences` is not a count of occurrences inside the window.
- **Agents:** agents are hosts, so `site` and `bench` do not filter them. A satellite is not
  a host and is counted apart; with `host`, it counts when one of its registered benches runs on
  that host. `fresh` means seen within the agent silence threshold of Wolf Settings, the same rule
  as the Desk overview's online flag.

## `dodock_wolf.api.scope.get_inventory`

The hosts, benches and sites the caller may see. Argument: `days` (default 7, at most 90), the
telemetry window.

```json
{
  "hosts": [
    {"host": "bench-01", "sources": ["agent", "events", "metrics"], "last_seen": "2026-10-30T12:59:30Z",
     "benches": [{"bench": "frappe-bench", "host": "bench-01", "sources": [...], "last_seen": "...",
                  "sites": [{"site": "a.example.com", "sources": [...], "last_seen": "..."}]}],
     "sites": []}
  ],
  "unplaced_sites": [],
  "note": "Hosts and benches come from agent registrations and from telemetry in the window. ...",
  "days": 7,
  "restricted": false,
  "as_of": "2026-10-30T13:00:02Z"
}
```

`as_of` is when the registrations and telemetry were read: they are cached for a few seconds
(see "Short cache" below).

Sources: `agent` and `satellite` (what an agent declared when it registered), `events` (by
when they last happened, so a recurring deduplicated event keeps its site listed), `metrics`
(rollups) and `incidents` (unresolved ones, whatever their age). A registration names every
site of a bench; a restricted user sees only the granted ones. Neither kind is complete on its own: a
bench added after its agent registered appears once it sends telemetry, and a quiet site only
through its agent's registration. The UI shows `sources` and `note` rather than presenting the
list as complete.

- A bench is always under its host.
- `host.sites` holds sites seen on a host whose bench is unknown.
- `unplaced_sites` holds sites seen without a host (for example a satellite with no host
  information); they are not attached to a guessed host.
- Times are UTC.

## Incident page

### `dodock_wolf.api.incident_view.list_incidents`

Incidents the caller may see, newest first. Arguments: `status` (`unresolved`, the default,
`resolved` or `all`), the scope arguments, `limit` (at most 200) and `cursor`. Pages follow
`(started_at, name)`, so two incidents started at the same second are neither repeated nor
skipped. Returns `incidents`, `paging` (`has_more`, `next_cursor`) and `time_zone`.

### `dodock_wolf.api.incident_view.get_incident`

The incident header in one call: title, status, severity, scope, start, acknowledgement,
resolution and owner, rule, silence, notification and escalation times, merge and split links,
and the timeline window. `deployment` gives the time of the deployment before the incident,
with `available: false` when retention deleted its event but the incident kept the time.
`event_records` (linked Wolf Events; `event_count` is the same number, as on Wolf Incident) and
`event_occurrences` (the occurrences they report, repeats included) are different numbers. `can` says which actions the caller may take: Wolf Users read and comment,
and Wolf Managers also acknowledge, resolve, take the incident, and:
- `merge`: the incident is not merged;
- `split`: not merged, and at least two events are linked (one must stay);
- `postmortem`: not merged, and either resolved or already has one (`postmortem` names it).

Each matches the check the action itself makes.

### `dodock_wolf.api.incident_view.get_timeline`

One page of the timeline, oldest first. Arguments: `incident`, `limit` (default 100, at most
500), `cursor`, and `families`, a comma-separated subset of:

| Family | Rows |
|---|---|
| `evidence` | Wolf Events linked to the incident, at any time |
| `context` | Other events in its scope (site, the same bench on the same host, or host-wide) during its window, if the caller may see them, and the deployment before it even when that is older than the window. When the incident took events from other scopes (by IP or user, or a sequence rule), also the deployments and health events (`error`, `cron_failure`, `worker_failure`, `host_metric_alert`) of those scopes in the window: of the site; of the bench on its host; on a host, its host-wide events and its benches' deployments and failed crons and workers, not its sites' Error Logs. At most 10 such scopes, the same on every page. An incident with no site, bench or host has only that second kind, in Desk too. A user who may read one of those scopes but not the event that brought it in can still tell, from its rows, that the incident reached it. |
| `activity` | Status changes, assignments, comments and notes, from Frappe's Version and Comment history |
| `delivery` | Notification attempts (Wolf Delivery) |

Each row has a stable `id` (`event:<name>`, `activity:comment:<name>`,
`activity:version:<name>:<field>`, `delivery:<name>`, `deployment:<incident>`), `family`,
`kind`, `at` (UTC) and a plain-text `summary`, plus per kind:

- **Events:** `relation` is `linked`, `context` or `preceding_change` (the deployment before the
  incident, never called its cause). `count`, `first_seen` and `last_seen` describe a
  deduplicated record: one row, not one row per occurrence. `details` is the event payload,
  for display as text. `source_label` says who raised it (`Wolf agent`, `Wolf site`, `Suricata`,
  `Wazuh`); `duplicate_of` names another source's event about the same finding, seen first
  (overlapping detectors in `both` mode), whose row id is `event:<duplicate_of>`.
- **Activity:** `user_name`. Comments and notes come as plain `text`, never HTML to render.
- **Deliveries:** `channel`, `action`, `target`, `result` and `http_status`. `result` is
  `accepted` when the endpoint took the message, which does not mean a person read it.

Rows are ordered by time, then events, activity and deliveries, then id. Rows with the same
time have no causal order. `paging.next_cursor` continues after the last row; the same rows
come back once each whatever the page size. Activity keeps the newest 200 recorded changes
and 300 comments; `truncated.activity_version` and `truncated.activity_comment` report when
older ones exist. `window` is the incident's window (start minus `padding_minutes`, to its
resolution or now), the same one Desk and the postmortem use.

### `dodock_wolf.api.incident_view.act`

POST `incident` and `action`, one of `acknowledge`, `resolve` or `assign_to_me`. It runs the
incident's own method, so Frappe's write permission applies, and returns the new
`get_incident`. The incident's state is checked first: acknowledging needs an Open incident,
and resolving or taking needs an unresolved one. A page left open on a stale incident gets
an error instead of reopening it. Merged incidents refuse every action.

### `dodock_wolf.api.incident_view.merge_preview`

`source`, and optionally `target`; Wolf Managers with write permission only. Nothing is written.

- `candidates`: where the source may go. These are unresolved, unmerged incidents the caller may
  read: the newest 50 (`more_candidates` says when there are more), the source's site first,
  then its bench.
- `preview`, for a `target`:
  - `error`: the merge's own refusal (itself, a merged incident, no write permission) or null;
  - the `events` and `comments` that would move;
  - `target_after`: severity, start and status, once the target covers both;
  - `source_after`: Resolved, merged into the target.

The merge itself is `dodock_wolf.api.incident.merge` (POST `source`, `target`), which checks
again.

### `dodock_wolf.api.incident_view.split_preview`

`incident`, and optionally `events` (a JSON list of Wolf Event names); Wolf Managers only.
Nothing is written.

- `events`: the linked events, oldest first, at most 500 (`more_events`).
- `preview`, for a selection:
  - `error`: the split's own refusal (nothing ticked, an event not linked, all of them ticked)
    or null;
  - `moved` and `kept`;
  - `new_incident`: title, severity, start and status. It is Open, or Resolved when the source
    is. It has no alert rule, so nothing resolves it by itself.

The split itself is `dodock_wolf.api.incident.split` (POST `incident`, `events`, `title`).
The postmortem is created by `dodock_wolf.api.incident.create_postmortem` and edited in Desk.

## Dashboards

### `dodock_wolf.api.dashboard.get_signals`

The newest value of every signal series in scope (`site`, `bench` with `host`, `host`), one
series per metric, host, bench, site and label. Each series has a `state`:

| State | Meaning |
|---|---|
| `firing` | An enabled rule on this metric applies to the series and has an open incident for its scope and, for rules grouped by label, its label (`incidents`). A firing series whose samples stopped stays firing, with `stale: true`. |
| `stale` | Samples stopped: none in the last 2 hours, or none for three collection intervals, at least 5 minutes (backups: 30 min). The old value is not presented as current. The cadences are the agent's defaults: an agent set to probe TLS or backups less often looks stale sooner. |
| `watched` | Rules apply (`rules`: aggregation, operator, threshold, window) and none has an open incident. |
| `unwatched` | A value, but no rule watches it. The dashboard does not invent a threshold. |

`missing` lists the signals with no series at all in the last 7 days: not collected for this
scope, not set up, or not available here. They are never shown as zero. `counts` gives exact
states per group whatever the 300-series limit. `email` reports the email queue problems the
site recorded about itself in the last 24 hours. A restricted user sees what each rule checks,
but not the host, bench or site filters it names. The metric meanings (unit, kind, cadence)
are in `wolf/catalog.py`; the `host` group holds the agent's setup checks
(`agent_setup_failed`, `agent_setup_warnings`), the host resource metrics having been removed in
0.2. `as_of` is when the series were read (see "Short cache" below); the
rules, incidents and states are read with each request.

### Short cache: `get_inventory` and `get_signals`

The overview's two slow reads keep what they read for `wolf_read_cache_seconds` (site config,
default 30, an agent's push interval; 0 turns it off): `get_inventory` its registrations and
telemetry triples, `get_signals` its series (newest value and last time seen).
- The cached value is read **without** access conditions and is the same for every caller. Each
  request then keeps the rows its caller may see, by the rule of `wolf/scopes.py`; a cached value
  never carries one user's grants to another.
- Rules, open incidents and the email queue are read per request: a signal's state follows an
  incident at once.
- A value is **fresh** for `wolf_read_cache_seconds`. Older, and up to 4 times that (2 min by
  default), it is still served at once, and one background job (deduplicated, `short` queue)
  reads it again. Older still, or missing, the request reads.
- Between visits, the scheduler reads again, every minute, the values asked for in the last 10
  minutes (10 at most per site) that are no longer fresh (`read_cache.refresh_active`). It needs
  `scheduler_tick_interval` at 60 (see "Install the app" in the README): at Dodock's default
  4 min tick, a visit after 2 quiet minutes reads.
- So a series that starts, or a value that changes, shows up a minute or two later at most;
  `as_of` says when the data was read. A live update (below) refetches, and may get the cached
  value.
- A change of `wolf_read_cache_seconds` takes effect within a minute: Dodock's web workers keep
  the site config in memory for up to 60 s.
- One cached value per site and per scope (`get_signals`' site, bench and host; the inventory's
  `days`): a dashboard of another scope has its own.

### `dodock_wolf.api.dashboard.get_http`

Requests, 5xx and 502 per bucket over the window (the common window and scope arguments),
summed across labels and read at the resolution of the window (`resolution`). Only whole
buckets are read (`window`; `requested_window` is what was asked): the bucket still filling
shows once it closes, instead of drawing a drop in traffic. 502 is part of 5xx and is never
added to it. A bucket without samples is `null`: a gap, not a zero. `has_data` tells "no
data" from "zero". `deployments` lists the deployments in the requested window. On a site's
dashboard that includes deployments recorded for its whole bench (no site), as incidents link
them.

### `dodock_wolf.api.dashboard.get_monitoring`

Whether Wolf itself works: the site's health (rules, scheduler, ingest queue), rollup
watermarks, every agent and satellite with its state, last contact, clock skew and version,
and this site's mode. Each part is reported on its own. An online agent says nothing about
its watchdog's fallback channel.

## Explorers

Wolf Events are deduplicated: one record holds its first time (`first_seen`), last time
(`last_seen`) and the number of repeats it absorbed (`count`). Explorer lists are lists of
records. They never say how many times something happened inside a window when a record
spans the window's edge, and each response says so in `basis`. Searches (`q`) match a plain
substring of the title, at most 100 characters: `%` and `_` match themselves, and there is no
regex.

### `dodock_wolf.api.explore.list_events`

Event records active in the window (first seen before its end, last seen after its start),
newest first, paged by `(first seen, name)`. Arguments: the common window and scope arguments,
`event_type`, `severity`, `category`, `q`, `limit` (at most 200), `cursor` and `entity`.
Payloads are not in the list; `get_event(name)` returns one record with its payload.

`entity` keeps the security events of every source (Wolf, Suricata, Wazuh) that name it:
`ip:203.0.113.5`, `host:erp-01`, `site:erp.example.com` or `user:jane@example.com`. Values are
normalised and resolved through the aliases (#72 step 3). For example, `host:erp-01` also finds
the Wazuh alerts of the agent named `wazuh-erp01` when an alias says they are the same host.
`dodock_wolf.api.entities.find(entity, ...)` is the same list. The response echoes `entity`.

### `dodock_wolf.api.explore.list_error_groups`

Groups of error records, by fingerprint, that have a record active in the window, latest
first. The window and `q` choose the groups. Their figures cover every record of the group the
caller may see, whatever its age, as on the group's page, so a recurring error isn't
presented as new:
- `records`, and `records_in_window`;
- `occurrences`, the sum of the records' counts;
- `first_seen` and `last_seen`;
- the number of `sites`, and whether some records are host-wide;
- the number of linked `incidents`;
- the title of the most recently seen record, which stands for the group. A fingerprint
includes the site unless the agent sends its own, so most groups concern one site.

### `dodock_wolf.api.explore.get_error_group`

Every visible record of one group, whatever its age:
- where it happened, by site, bench and host;
- the incidents it is linked to that the caller may read (`incidents_not_visible` counts the
  others);
- its most recently seen record with the payload (the representative traceback, the same
  record the list shows);
- its 50 most recently seen records.

A restricted user sees only the records of their sites, benches or hosts, and counts over
those.

## Live updates

The Wolf UI stays current over Frappe's own socket.io server (`dodock_wolf/wolf/live.py`,
`frontend/src/services/live.js`). The server never pushes telemetry: it sends an
**invalidation**, the event `wolf_invalidate`, and the page fetches again through the APIs
above, which check permissions as usual.

| Room | Joined with | Frappe checks | Message |
|---|---|---|---|
| `doc:Wolf Incident/<name>` | `doc_subscribe` | read permission on that incident (Wolf User Scope applies) | `{"kind": "incident", "incident": "<name>"}` |
| `doctype:Wolf Incident` | `doctype_subscribe` | read permission on the DocType | `{"kind": "incidents"}` |
| `doctype:Wolf Event` | `doctype_subscribe` | read permission on the DocType | `{"kind": "events"}` |

- **Sent when**: an incident is created, saved, updated by the engine (new linked events, reopen,
  auto-resolve, silence, escalation, assignment, postmortem) or deleted; a comment on an incident
  is added, edited or deleted; a delivery is recorded; an event is stored.
- **At most one message per room and transaction**, after commit; the bookkeeping is cleared on
  commit and on rollback, so a job that commits many times announces each transaction and a
  rolled-back one announces nothing. List messages are also throttled to one per 5 s per kind;
  one held back is marked after commit and sent by `flush_live_updates` (every minute): a
  committed change can be delayed, never lost.
- **No names in list rooms**: a restricted reader only learns that something changed somewhere.
- **Boot**: `capabilities.realtime` gives `namespace` (`/<site>`), `port` (`socketio_port`, for
  `bench start`), `dev_server` and `poll_seconds`. Behind nginx the socket uses the site's own
  origin (`/socket.io` is proxied, as for Desk).

What each page does with a message:

| Page | On a message | Without a socket |
|---|---|---|
| Incident | header refreshed; new timeline rows are added without scrolling, and a "N new rows: show" button takes the reader to the first one. Loaded rows and expanded rows stay; past 500 loaded rows only the header follows and the rows wait for Refresh | polls every 60 s |
| Incidents | refreshed, unless "Load more" was used: then "Incidents changed · Refresh" | polls, same rule |
| Overview and dashboards | refreshed at most every 10 s (messages carry no scope; relative windows move); also polled every 60 s while live, because metrics are not announced | polls |
| Events, Errors | never reshuffled under the reader: "New events recorded · Refresh" (the new events may not match the filters) | not polled: "Not live: refresh by hand" |

Every page reconciles once when the socket first joins its rooms (what changed after its first
fetch is unknown) and after each reconnect (messages sent while offline are lost). A page that
does not reload by itself shows "Reconnected, changes may have been missed · Refresh" after a
reconnect; a poll or the first connect never claims a change. **Pause** holds messages (the
page says changes are waiting) until **Resume**. Every refresh, the reader's included, goes
through one queue: never two at once. Polling skips hidden tabs.

## Security

### `dodock_wolf.api.security.list_sites`

Sites with a recent `site_config_risks` or `backup_age_hours` sample, plus the Wolf site itself
(not on a satellite), filtered by the caller's access.

### `dodock_wolf.api.security.get_posture`

Argument: `site` (default: the Wolf site). Returns `site`, `local` (the Wolf site: System Settings
are readable), `hosts`, `recent_hours`, `score`, `coverage`, `passed`, `failed`, `unknown` and
`checks`: `{id, label, weight, status, evidence, fix}` with `status` `pass`, `fail` or `unknown`.
The score is the weight passed over the total weight; an unknown check counts as not passed.
Agent samples older than `recent_hours` (3) are not used. A site the caller may not see is a 403.
The hourly `record_security_scores` job stores the score as the `security_score` metric.

## Regulatory reporting

`get_incident` returns `regulatory`: `null` when neither flag is set, else `{nis2, gdpr,
reference, deadlines}`; each deadline is `{id, regime, label, due_at, done_at, status,
estimated}` with `status` `open`, `due_soon` (within 6 h), `overdue`, `done` or `done_late`.

### `dodock_wolf.api.compliance.get_report`

Argument: `incident`. Returns `{incident, markdown}`: a draft with the facts, the deadlines,
the timeline (linked events and comments, 100 each at most) and the postmortem's impact, root
cause, lessons and action items. Read permission on the incident is enough. Nothing is sent.

## Response actions

### `dodock_wolf.api.response.get_response`

Argument: `incident`. Returns `proposals` (`{action, target, agent, host, bench, site, reason,
label, executors}`; a block names the attacked `host`, its Wolf Agent in `agent` when it applies it,
and `executors`: `wolf_agent`, `wazuh`; from the incident's security events, without the ones already approved or applied),
`actions` (the incident's Wolf Response Action rows), `can_approve`, `default_hours`, `max_hours`.

### `dodock_wolf.api.response.approve` (POST)

Arguments: `incident`, `action` (`block_ip`, `disable_user`, `logout_sessions`,
`revoke_api_keys`), `target`, `host` (block_ip: the attacked host as proposed; `agent` instead, from
older links), `duration_hours` (the Wolf Agent's block, 1 to 168; a Wazuh block lasts its command's
timeout), `reason`.
Wolf Manager / System Manager only. Refused targets (private or reserved address, Administrator,
Guest, yourself) are a validation error and nothing is recorded. Returns the Wolf Response Action;
user actions come back `Applied` or `Failed`, blocks `Approved` until the agent reports, and a
Wazuh block `Applied` or `Failed` at once. With Block With `both`, `also` holds the second row.
