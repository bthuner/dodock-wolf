# UI API

> The read and action APIs behind the Wolf UI at /wolf, their arguments, answers and access rules.

These are the APIs behind the Wolf UI (`/wolf`,
[#19](https://github.com/bthuner/dodock-wolf/issues/19)). They need the Wolf User, Wolf Manager or
System Manager role, and apply the caller's access rules inside the query (see
[Access](/security/access)). Answers are not cached per user, so each one is the caller's own;
two reads share a short cache filtered per caller (see [Short cache](#short-cache)).

<table>
<thead>
  <tr>
    <th>
      Area
    </th>
    
    <th>
      Methods
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <a href="#overview">
        Overview
      </a>
    </td>
    
    <td>
      <code>
        scope.get_counts
      </code>
      
      , <code>
        scope.get_inventory
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#incident-page">
        Incident page
      </a>
    </td>
    
    <td>
      <code>
        incident_view.list_incidents
      </code>
      
      , <code>
        get_incident
      </code>
      
      , <code>
        get_timeline
      </code>
      
      , <code>
        act
      </code>
      
      , <code>
        merge_preview
      </code>
      
      , <code>
        split_preview
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#dashboards">
        Dashboards
      </a>
    </td>
    
    <td>
      <code>
        dashboard.get_signals
      </code>
      
      , <code>
        get_http
      </code>
      
      , <code>
        get_monitoring
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#explorers">
        Explorers
      </a>
    </td>
    
    <td>
      <code>
        explore.list_events
      </code>
      
      , <code>
        list_error_groups
      </code>
      
      , <code>
        get_error_group
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#metrics-explorer">
        Metrics explorer
      </a>
    </td>
    
    <td>
      <code>
        metrics.get_metric_catalog
      </code>
      
      , <code>
        query_metric
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#security">
        Security
      </a>
    </td>
    
    <td>
      <code>
        security.list_sites
      </code>
      
      , <code>
        get_posture
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#regulatory-reporting">
        Regulatory reporting
      </a>
    </td>
    
    <td>
      <code>
        compliance.get_report
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="#response-actions">
        Response actions
      </a>
    </td>
    
    <td>
      <code>
        response.get_response
      </code>
      
      , <code>
        approve
      </code>
    </td>
  </tr>
</tbody>
</table>

Every method is under `dodock_wolf.api.`, for example `/api/method/dodock_wolf.api.scope.get_counts`.

## Common arguments

### Time window

<table>
<thead>
  <tr>
    <th>
      Argument
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        range
      </code>
    </td>
    
    <td>
      Relative window ending now: a number and <code>
        m
      </code>
      
      , <code>
        h
      </code>
      
       or <code>
        d
      </code>
      
      , such as <code>
        15m
      </code>
      
      , <code>
        24h
      </code>
      
      , <code>
        7d
      </code>
      
      . Default <code>
        24h
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        since
      </code>
      
      , <code>
        until
      </code>
    </td>
    
    <td>
      Explicit window, ISO 8601. A time without an offset is read as UTC, as in the <a href="/reference/protocol">
        agent protocol
      </a>
      
      . <code>
        until
      </code>
      
       defaults to now and needs <code>
        since
      </code>
      
      . They win over <code>
        range
      </code>
      
      .
    </td>
  </tr>
</tbody>
</table>

- A relative window is measured in real time: across a DST change, `24h` is 24 hours, not 23 or
25 hours of wall clock.
- Windows longer than 400 days, or with `since` after `until`, are refused.
- The Desk overview APIs (`api/ui.py`) accept the same `range` values.

Every response that reads a window returns what it actually read, in UTC:

```json [window]
"window": {"since": "2026-10-29T13:00:00Z", "until": "2026-10-30T13:00:00Z", "relative": "24h", "time_zone": "Europe/Paris"}
```

`time_zone` is the site's. Stored times are in that zone. The UI converts with it, never with the
browser's zone.

In the Wolf UI, the window is in the URL (`?range=7d` or `?since=…&until=…`). A range selected on
the HTTP chart of a dashboard, or on the chart of the metrics explorer, becomes an explicit
`since`/`until`: the dashboard's counts and chart, and the event and error explorers opened from
it, are read with it. **Back to a relative window** drops it.

### Scope

`site`, `bench` and `host` narrow a query to records with those values.

<warning>

**bench needs host.** Bench names such as `frappe-bench` repeat across hosts, so a bench alone
is ambiguous and refused.

</warning>

### Access

A restricted Wolf User, one with **Wolf User Scope** rows, gets counts and inventory over the
records they may see, and `"restricted": true`.

<note>

A Wolf User **without any** Wolf User Scope row is not restricted: they see everything, as in
Desk. That is the current rule, kept as is.

</note>

## Overview

### `dodock_wolf.api.scope.get_counts`

Exact counts for the overview and entity dashboards. Arguments: window and scope.

```json [get_counts]
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

<table>
<thead>
  <tr>
    <th>
      Part
    </th>
    
    <th>
      Rule
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        incidents
      </code>
    </td>
    
    <td>
      <code>
        unresolved
      </code>
      
       counts Open and Acknowledged incidents now, whatever the window. <code>
        unacknowledged
      </code>
      
       is Open only. Merged incidents are excluded. <code>
        unresolved_without_site
      </code>
      
       counts host- or bench-wide incidents, which have no site. <code>
        opened_in_window
      </code>
      
       and <code>
        resolved_in_window
      </code>
      
       use <code>
        started_at
      </code>
      
       and <code>
        resolved_at
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        events
      </code>
    </td>
    
    <td>
      <code>
        records
      </code>
      
       are Wolf Events first seen in the window. <code>
        occurrences
      </code>
      
       sums their reported <code>
        count
      </code>
      
      . A deduplicated record keeps counting repeats, including repeats after the window, so <code>
        occurrences
      </code>
      
       is not a count of occurrences inside the window.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        agents
      </code>
    </td>
    
    <td>
      Agents are hosts, so <code>
        site
      </code>
      
       and <code>
        bench
      </code>
      
       do not filter them. A satellite is not a host and is counted apart; with <code>
        host
      </code>
      
      , it counts when one of its registered benches runs on that host. <code>
        fresh
      </code>
      
       means seen within the agent silence threshold of Wolf Settings, the same rule as the Desk overview's online flag.
    </td>
  </tr>
</tbody>
</table>

### `dodock_wolf.api.scope.get_inventory`

The hosts, benches and sites the caller may see. Argument: `days`, the telemetry window
(default 7, at most 90).

```json [get_inventory]
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

`as_of` is when the registrations and telemetry were read: they are cached for a few seconds (see
[Short cache](#short-cache)).

<table>
<thead>
  <tr>
    <th>
      Source
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        agent
      </code>
      
      , <code>
        satellite
      </code>
    </td>
    
    <td>
      What an agent declared when it registered.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        events
      </code>
    </td>
    
    <td>
      By when they last happened, so a recurring deduplicated event keeps its site listed.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        metrics
      </code>
    </td>
    
    <td>
      Rollups.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        incidents
      </code>
    </td>
    
    <td>
      Unresolved ones, whatever their age.
    </td>
  </tr>
</tbody>
</table>

A registration names every site of a bench; a restricted user sees only the granted ones.
Neither kind of source is complete on its own: a bench added after its agent registered appears
once it sends telemetry, and a quiet site only through its agent's registration. The UI shows
`sources` and `note` rather than presenting the list as complete.

- A bench is always under its host.
- `host.sites` holds sites seen on a host whose bench is unknown.
- `unplaced_sites` holds sites seen without a host, for example a satellite with no host
information. They are not attached to a guessed host.
- Times are UTC.

## Incident page

### `dodock_wolf.api.incident_view.list_incidents`

Incidents the caller may see, newest first.

<table>
<thead>
  <tr>
    <th>
      Argument
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        status
      </code>
    </td>
    
    <td>
      <code>
        unresolved
      </code>
      
       (default), <code>
        resolved
      </code>
      
       or <code>
        all
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        site
      </code>
      
      , <code>
        bench
      </code>
      
      , <code>
        host
      </code>
    </td>
    
    <td>
      Scope.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        limit
      </code>
    </td>
    
    <td>
      At most 200.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        cursor
      </code>
    </td>
    
    <td>
      Continues a page.
    </td>
  </tr>
</tbody>
</table>

Pages follow `(started_at, name)`, so two incidents started at the same second are neither
repeated nor skipped. Returns `incidents`, `paging` (`has_more`, `next_cursor`) and `time_zone`.

### `dodock_wolf.api.incident_view.get_incident`

The incident header in one call: title, status, severity, scope, start, acknowledgement,
resolution and owner, rule, silence, notification and escalation times, merge and split links,
and the timeline window.

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        deployment
      </code>
    </td>
    
    <td>
      Time of the deployment before the incident, with <code>
        available: false
      </code>
      
       when retention deleted its event but the incident kept the time.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        event_records
      </code>
    </td>
    
    <td>
      Linked Wolf Events. <code>
        event_count
      </code>
      
       is the same number, as on <strong>
        Wolf Incident
      </strong>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        event_occurrences
      </code>
    </td>
    
    <td>
      The occurrences they report, repeats included. A different number from <code>
        event_records
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        can
      </code>
    </td>
    
    <td>
      Which actions the caller may take.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        regulatory
      </code>
    </td>
    
    <td>
      See <a href="#regulatory-reporting">
        Regulatory reporting
      </a>
      
      .
    </td>
  </tr>
</tbody>
</table>

Wolf Users read and comment. Wolf Managers also acknowledge, resolve, take the incident, and:

- `merge`: the incident is not merged;
- `split`: not merged, and at least two events are linked (one must stay);
- `postmortem`: not merged, and either resolved or already has one (`postmortem` names it).

Each matches the check the action itself makes.

### `dodock_wolf.api.incident_view.get_timeline`

One page of the timeline, oldest first.

<table>
<thead>
  <tr>
    <th>
      Argument
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        incident
      </code>
    </td>
    
    <td>
      The <strong>
        Wolf Incident
      </strong>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        limit
      </code>
    </td>
    
    <td>
      Default 100, at most 500.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        cursor
      </code>
    </td>
    
    <td>
      Continues a page.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        families
      </code>
    </td>
    
    <td>
      Comma-separated subset of the families below.
    </td>
  </tr>
</tbody>
</table>

<table>
<thead>
  <tr>
    <th>
      Family
    </th>
    
    <th>
      Rows
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        evidence
      </code>
    </td>
    
    <td>
      Wolf Events linked to the incident, at any time.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        context
      </code>
    </td>
    
    <td>
      Other events in its scope (site, the same bench on the same host, or host-wide) during its window, if the caller may see them, and the deployment before it even when that is older than the window. When the incident took events from other scopes (by IP or user, or a sequence rule), also the deployments and health events (<code>
        error
      </code>
      
      , <code>
        cron_failure
      </code>
      
      , <code>
        worker_failure
      </code>
      
      , <code>
        host_metric_alert
      </code>
      
      ) of those scopes in the window: of the site; of the bench on its host; on a host, its host-wide events and its benches' deployments and failed crons and workers, not its sites' Error Logs. At most 10 such scopes, the same on every page. An incident with no site, bench or host has only that second kind, in Desk too. A user who may read one of those scopes but not the event that brought it in can still tell, from its rows, that the incident reached it.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        activity
      </code>
    </td>
    
    <td>
      Status changes, assignments, comments and notes, from Frappe's Version and Comment history.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        delivery
      </code>
    </td>
    
    <td>
      Notification attempts (<strong>
        Wolf Delivery
      </strong>
      
      ).
    </td>
  </tr>
</tbody>
</table>

Each row has a stable `id`, `family`, `kind`, `at` (UTC) and a plain-text `summary`. Ids:
`event:<name>`, `activity:comment:<name>`, `activity:version:<name>:<field>`,
`delivery:<name>`, `deployment:<incident>`.

Per kind:

<table>
<thead>
  <tr>
    <th>
      Kind
    </th>
    
    <th>
      Fields
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Events
    </td>
    
    <td>
      <code>
        relation
      </code>
      
      : <code>
        linked
      </code>
      
      , <code>
        context
      </code>
      
       or <code>
        preceding_change
      </code>
      
       (the deployment before the incident, never called its cause). <code>
        count
      </code>
      
      , <code>
        first_seen
      </code>
      
       and <code>
        last_seen
      </code>
      
       describe a deduplicated record: one row, not one row per occurrence. <code>
        details
      </code>
      
       is the event payload, for display as text. <code>
        source_label
      </code>
      
       says who raised it (<code>
        Wolf agent
      </code>
      
      , <code>
        Wolf site
      </code>
      
      , <code>
        Suricata
      </code>
      
      , <code>
        Wazuh
      </code>
      
      ). <code>
        duplicate_of
      </code>
      
       names another source's event about the same finding, seen first (<a href="/security/wazuh-suricata#when-detectors-overlap">
        overlapping detectors
      </a>
      
       in <code>
        both
      </code>
      
       mode); its row id is <code>
        event:<duplicate_of>
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      Activity
    </td>
    
    <td>
      <code>
        user_name
      </code>
      
      . Comments and notes come as plain <code>
        text
      </code>
      
      , never HTML to render.
    </td>
  </tr>
  
  <tr>
    <td>
      Deliveries
    </td>
    
    <td>
      <code>
        channel
      </code>
      
      , <code>
        action
      </code>
      
      , <code>
        target
      </code>
      
      , <code>
        result
      </code>
      
       and <code>
        http_status
      </code>
      
      . <code>
        result
      </code>
      
       is <code>
        accepted
      </code>
      
       when the endpoint took the message, which does not mean a person read it.
    </td>
  </tr>
</tbody>
</table>

- Rows are ordered by time, then events, activity and deliveries, then id. Rows with the same
time have no causal order.
- `paging.next_cursor` continues after the last row. The same rows come back once each,
whatever the page size.
- Activity keeps the newest 200 recorded changes and 300 comments.
`truncated.activity_version` and `truncated.activity_comment` report when older ones exist.
- `window` is the incident's window: start minus `padding_minutes`, to its resolution or now. It
is the same window Desk and the postmortem use.

### `dodock_wolf.api.incident_view.act`

POST `incident` and `action`, one of `acknowledge`, `resolve` or `assign_to_me`. It runs the
incident's own method, so Frappe's write permission applies, and returns the new
`get_incident`.

The incident's state is checked first:

- acknowledging needs an Open incident;
- resolving or taking needs an unresolved one;
- merged incidents refuse every action.

A page left open on a stale incident gets an error instead of reopening it.

### `dodock_wolf.api.incident_view.merge_preview`

Arguments: `source`, and optionally `target`. Wolf Managers with write permission only. Nothing is
written.

- `candidates`: where the source may go. These are unresolved, unmerged incidents the caller may
read: the newest 50 (`more_candidates` says when there are more), the source's site first,
then its bench.
- `preview`, for a `target`:

  - `error`: the merge's own refusal (itself, a merged incident, no write permission) or `null`;
  - the `events` and `comments` that would move;
  - `target_after`: severity, start and status, once the target covers both;
  - `source_after`: Resolved, merged into the target.

The merge itself is `dodock_wolf.api.incident.merge` (POST `source`, `target`), which checks
again.

### `dodock_wolf.api.incident_view.split_preview`

Arguments: `incident`, and optionally `events` (a JSON list of Wolf Event names). Wolf Managers
only. Nothing is written.

- `events`: the linked events, oldest first, at most 500 (`more_events`).
- `preview`, for a selection:

  - `error`: the split's own refusal (nothing ticked, an event not linked, all of them ticked)
  or `null`;
  - `moved` and `kept`;
  - `new_incident`: title, severity, start and status. It is Open, or Resolved when the source
  is. It has no alert rule, so nothing resolves it by itself.

The split itself is `dodock_wolf.api.incident.split` (POST `incident`, `events`, `title`). The
postmortem is created by `dodock_wolf.api.incident.create_postmortem` and edited in Desk.

## Dashboards

### `dodock_wolf.api.dashboard.get_signals`

The newest value of every signal series in scope (`site`, `bench` with `host`, `host`): one series
per metric, host, bench, site and label. Each series has a `state`:

<table>
<thead>
  <tr>
    <th>
      State
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        firing
      </code>
    </td>
    
    <td>
      An enabled rule on this metric applies to the series and has an open incident for its scope and, for rules grouped by label, its label (<code>
        incidents
      </code>
      
      ). A firing series whose samples stopped stays firing, with <code>
        stale: true
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        stale
      </code>
    </td>
    
    <td>
      Samples stopped: none in the last 2 hours, or none for three collection intervals, at least 5 minutes (backups: 30 min). The old value is not presented as current. The cadences are the agent's defaults: an agent set to probe TLS or backups less often looks stale sooner.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        watched
      </code>
    </td>
    
    <td>
      Rules apply (<code>
        rules
      </code>
      
      : aggregation, operator, threshold, window) and none has an open incident.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        unwatched
      </code>
    </td>
    
    <td>
      A value, but no rule watches it. The dashboard does not invent a threshold.
    </td>
  </tr>
</tbody>
</table>

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        missing
      </code>
    </td>
    
    <td>
      Signals with no series at all in the last 7 days: not collected for this scope, not set up, or not available here. They are never shown as zero.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        counts
      </code>
    </td>
    
    <td>
      Exact states per group, whatever the 300-series limit.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        email
      </code>
    </td>
    
    <td>
      Email queue problems the site recorded about itself in the last 24 hours.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        as_of
      </code>
    </td>
    
    <td>
      When the series were read (see <a href="#short-cache">
        Short cache
      </a>
      
      ). Rules, incidents and states are read with each request.
    </td>
  </tr>
</tbody>
</table>

A restricted user sees what each rule checks, but not the host, bench or site filters it names.
The metric meanings (unit, kind, cadence) are in
[`wolf/catalog.py`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/catalog.py).

### Short cache

`get_inventory` and `get_signals`, the overview's two slow reads, keep what they read for
`wolf_read_cache_seconds`: site config, default `30` (an agent's push interval), `0` turns it off.
`get_inventory` caches its registrations and telemetry triples, `get_signals` its series (newest
value and last time seen).

<caution>

The cached value is read **without** access conditions and is the same for every caller. Each
request then keeps the rows its caller may see, by the rule of
[`wolf/scopes.py`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/scopes.py). A
cached value never carries one user's grants to another.

</caution>

- Rules, open incidents and the email queue are read per request: a signal's state follows an
incident at once.
- A value is **fresh** for `wolf_read_cache_seconds`. Older, and up to 4 times that (2 min by
default), it is still served at once, and one background job (deduplicated, `short` queue)
reads it again. Older still, or missing, the request reads.
- Between visits, the scheduler reads again, every minute, the values asked for in the last 10
minutes (10 at most per site) that are no longer fresh (`read_cache.refresh_active`). It needs
`scheduler_tick_interval` at 60 (see [Install the Wolf App](/install/wolf-app)): at Dodock's
default 4 min tick, a visit after 2 quiet minutes reads.
- A series that starts, or a value that changes, shows up a minute or two later at most. `as_of`
says when the data was read. A [live update](#live-updates) refetches, and may get the cached
value.
- A change of `wolf_read_cache_seconds` takes effect within a minute: Dodock's web workers keep
the site config in memory for up to 60 s.
- There is one cached value per site and per scope (`get_signals`' site, bench and host; the
inventory's `days`): a dashboard of another scope has its own.

Measured effect: [Performance](/reference/performance#the-short-cache).

### `dodock_wolf.api.dashboard.get_http`

Requests, 5xx and 502 per bucket over the window. Arguments: the common window and scope
arguments.

- Values are summed across labels and read at the resolution of the window (`resolution`).
- Only whole buckets are read (`window`; `requested_window` is what was asked): the bucket still
filling shows once it closes, instead of drawing a drop in traffic.
- 502 is part of 5xx and is never added to it.
- A bucket without samples is `null`: a gap, not a zero. `has_data` tells "no data" from "zero".
- `deployments` lists the deployments in the requested window. On a site's dashboard that
includes deployments recorded for its whole bench (no site), as incidents link them.

### `dodock_wolf.api.dashboard.get_monitoring`

Whether Wolf itself works: the site's health (rules, scheduler, ingest queue), rollup watermarks,
every agent and satellite with its state, last contact, clock skew and version, its `setup` (the
agent's last `wolf-agent doctor` run: `checked_at`, `failed`, `warnings`, and the `problems` with
their fix), and this site's mode. Each part is reported on its own.

<note>

An online agent says nothing about its watchdog's fallback channel.

</note>

## Explorers

Wolf Events are deduplicated: one record holds its first time (`first_seen`), last time
(`last_seen`) and the number of repeats it absorbed (`count`). Explorer lists are lists of
records. They never say how many times something happened inside a window when a record spans
the window's edge, and each response says so in `basis`.

Searches (`q`) match a plain substring of the title, at most 100 characters: `%` and `_` match
themselves, and there is no regex.

### `dodock_wolf.api.explore.list_events`

Event records active in the window (first seen before its end, last seen after its start), newest
first, paged by `(first seen, name)`.

<table>
<thead>
  <tr>
    <th>
      Argument
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        range
      </code>
      
      , <code>
        since
      </code>
      
      , <code>
        until
      </code>
    </td>
    
    <td>
      Window.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        site
      </code>
      
      , <code>
        bench
      </code>
      
      , <code>
        host
      </code>
    </td>
    
    <td>
      Scope.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        event_type
      </code>
      
      , <code>
        severity
      </code>
      
      , <code>
        category
      </code>
    </td>
    
    <td>
      Filters.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        q
      </code>
    </td>
    
    <td>
      Title substring.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        limit
      </code>
    </td>
    
    <td>
      At most 200.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        cursor
      </code>
    </td>
    
    <td>
      Continues a page.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        entity
      </code>
    </td>
    
    <td>
      Security events naming an entity (below).
    </td>
  </tr>
</tbody>
</table>

Payloads are not in the list: `get_event(name)` returns one record with its payload.

`entity` keeps the security events of every source (Wolf, Suricata, Wazuh) that name it:
`ip:203.0.113.5`, `host:erp-01`, `site:erp.example.com` or `user:jane@example.com`. Values are
normalised and resolved through the aliases. For example, `host:erp-01` also finds the Wazuh
alerts of the agent named `wazuh-erp01` when an alias says they are the same host.
`dodock_wolf.api.entities.find(entity, ...)` is the same list. The response echoes `entity`.

### `dodock_wolf.api.explore.list_error_groups`

Groups of error records, by fingerprint, that have a record active in the window, latest first.
The window and `q` choose the groups. Their figures cover every record of the group the caller
may see, whatever its age, as on the group's page, so a recurring error is not presented as new:

- `records`, and `records_in_window`;
- `occurrences`, the sum of the records' counts;
- `first_seen` and `last_seen`;
- the number of `sites`, and whether some records are host-wide;
- the number of linked `incidents`;
- the title of the most recently seen record, which stands for the group.

A fingerprint includes the site unless the agent sends its own, so most groups concern one site.

### `dodock_wolf.api.explore.get_error_group`

Every visible record of one group, whatever its age:

- where it happened, by site, bench and host;
- the incidents it is linked to that the caller may read (`incidents_not_visible` counts the
others);
- its most recently seen record with the payload: the representative traceback, the same record
the list shows;
- its 50 most recently seen records.

A restricted user sees only the records of their sites, benches or hosts, and counts over those.

## Metrics explorer

### `dodock_wolf.api.metrics.get_metric_catalog`

Every catalogued metric
([`wolf/catalog.py`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/catalog.py))
and the custom metrics seen in the last 7 days. Each one has:

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        kind
      </code>
      
      , <code>
        unit
      </code>
    </td>
    
    <td>
      What the value is.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        level
      </code>
    </td>
    
    <td>
      <code>
        host
      </code>
      
      , <code>
        bench
      </code>
      
       or <code>
        site
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        label_key
      </code>
    </td>
    
    <td>
      <code>
        mount
      </code>
      
      , <code>
        queue
      </code>
      
      , <code>
        domain
      </code>
      
      , <code>
        db
      </code>
      
      , <code>
        of
      </code>
      
       or <code>
        manager
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        aggregations
      </code>
      
      , <code>
        group_bys
      </code>
    </td>
    
    <td>
      What it allows.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        seen
      </code>
    </td>
    
    <td>
      Whether the caller has data for it.
    </td>
  </tr>
</tbody>
</table>

- Gauges are read as `avg`, `min`, `max` or `last`.
- Interval counts are read as `sum` (the total per bucket), `avg` or `max` (per push interval).
- A custom metric is read as a level.
- Grouping follows the metric's level: a host metric has no bench or site. Metrics with a label
also group by `host_label`, and so may a custom metric, whose labels the catalog cannot name.

The catalog lists every metric the agent sends, which a unit test checks against the agent's
source. `get_labels(metric, scope)` lists a metric's label values (at most 100), including those
first seen in the last hour.

### `dodock_wolf.api.metrics.query_metric`

<table>
<thead>
  <tr>
    <th>
      Argument
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        metric
      </code>
    </td>
    
    <td>
      Metric name.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        aggregation
      </code>
    </td>
    
    <td>
      Default per kind.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        group_by
      </code>
    </td>
    
    <td>
      Default <code>
        none
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        label
      </code>
    </td>
    
    <td>
      Label value.
    </td>
  </tr>
  
  <tr>
    <td>
      window and scope
    </td>
    
    <td>
      The common arguments.
    </td>
  </tr>
</tbody>
</table>

A combination the catalog does not allow is refused: a sum of disk levels, the last value of an
interval count, a host metric grouped by site.

The answer reads whole buckets (`bucket_seconds`; `window` is what was read, `requested_window`
what was asked) at a resolution fine enough for the window's length that still reaches back to
its start (`resolution`). A two-hour zoom into last week reads minute rollups, because raw
samples that old are purged (see [Metric storage](/reference/metric-storage)). It is exact across
raw samples and rollups. Groups are ranked in SQL first, and only the shown ones are read per
bucket.

Each of `series` has:

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        points
      </code>
    </td>
    
    <td>
      One per bucket, <code>
        null
      </code>
      
       for a bucket without samples (a gap, not a zero).
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        value
      </code>
    </td>
    
    <td>
      The aggregation over the whole window.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        samples
      </code>
      
      , <code>
        last_sample
      </code>
    </td>
    
    <td>
      Sample count and newest sample.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        stale
      </code>
    </td>
    
    <td>
      Judged only when the window reaches now (<code>
        live
      </code>
      
      ), and from the newest sample, not the last whole bucket (which lags by up to a bucket). In a past window the last sample is just where the window ends.
    </td>
  </tr>
</tbody>
</table>

`groups` says how many groups exist and which `MAX_GROUPS` (20) are shown, ranked by the
aggregation, highest first (lowest for `min`). `retention.clipped` is true when the window starts
before the data kept at this resolution (`kept_from`, the cutoff purge applies): those buckets
are gaps.

## Live updates

The Wolf UI stays current over Frappe's own socket.io server
([`dodock_wolf/wolf/live.py`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/live.py),
[`frontend/src/services/live.js`](https://github.com/bthuner/dodock-wolf/blob/main/frontend/src/services/live.js)).
The server never pushes telemetry. It sends an **invalidation**, the event `wolf_invalidate`, and
the page fetches again through the APIs above, which check permissions as usual.

<table>
<thead>
  <tr>
    <th>
      Room
    </th>
    
    <th>
      Joined with
    </th>
    
    <th>
      Frappe checks
    </th>
    
    <th>
      Message
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        doc:Wolf Incident/<name>
      </code>
    </td>
    
    <td>
      <code>
        doc_subscribe
      </code>
    </td>
    
    <td>
      read permission on that incident (Wolf User Scope applies)
    </td>
    
    <td>
      <code>
        {"kind": "incident", "incident": "<name>"}
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        doctype:Wolf Incident
      </code>
    </td>
    
    <td>
      <code>
        doctype_subscribe
      </code>
    </td>
    
    <td>
      read permission on the DocType
    </td>
    
    <td>
      <code>
        {"kind": "incidents"}
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        doctype:Wolf Event
      </code>
    </td>
    
    <td>
      <code>
        doctype_subscribe
      </code>
    </td>
    
    <td>
      read permission on the DocType
    </td>
    
    <td>
      <code>
        {"kind": "events"}
      </code>
    </td>
  </tr>
</tbody>
</table>

- **Sent when**: an incident is created, saved, updated by the engine (new linked events, reopen,
auto-resolve, silence, escalation, assignment, postmortem) or deleted; a comment on an incident
is added, edited or deleted; a delivery is recorded; an event is stored.
- **At most one message per room and transaction**, after commit. The bookkeeping is cleared on
commit and on rollback, so a job that commits many times announces each transaction and a
rolled-back one announces nothing. List messages are also throttled to one per 5 s per kind.
One held back is marked after commit and sent by `flush_live_updates` (every minute): a
committed change can be delayed, never lost.
- **No names in list rooms**: a restricted reader only learns that something changed somewhere.
- **Boot**: `capabilities.realtime` gives `namespace` (`/<site>`), `port` (`socketio_port`, for
`bench start`), `dev_server` and `poll_seconds`. Behind nginx the socket uses the site's own
origin (`/socket.io` is proxied, as for Desk).

What each page does with a message:

<table>
<thead>
  <tr>
    <th>
      Page
    </th>
    
    <th>
      On a message
    </th>
    
    <th>
      Without a socket
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Incident
    </td>
    
    <td>
      Header refreshed. New timeline rows are added without scrolling, and a "N new rows: show" button takes the reader to the first one. Loaded rows and expanded rows stay. Past 500 loaded rows only the header follows and the rows wait for Refresh.
    </td>
    
    <td>
      Polls every 60 s
    </td>
  </tr>
  
  <tr>
    <td>
      Incidents
    </td>
    
    <td>
      Refreshed, unless "Load more" was used: then "Incidents changed · Refresh".
    </td>
    
    <td>
      Polls, same rule
    </td>
  </tr>
  
  <tr>
    <td>
      Overview and dashboards
    </td>
    
    <td>
      Refreshed at most every 10 s (messages carry no scope; relative windows move). Also polled every 60 s while live, because metrics are not announced.
    </td>
    
    <td>
      Polls
    </td>
  </tr>
  
  <tr>
    <td>
      Events, Errors
    </td>
    
    <td>
      Never reshuffled under the reader: "New events recorded · Refresh" (the new events may not match the filters).
    </td>
    
    <td>
      Not polled: "Not live: refresh by hand"
    </td>
  </tr>
</tbody>
</table>

- Every page reconciles once when the socket first joins its rooms (what changed after its first
fetch is unknown) and after each reconnect (messages sent while offline are lost).
- A page that does not reload by itself shows "Reconnected, changes may have been missed ·
Refresh" after a reconnect. A poll or the first connect never claims a change.
- **Pause** holds messages, and the page says changes are waiting, until **Resume**.
- Every refresh, the reader's included, goes through one queue: never two at once.
- Polling skips hidden tabs.

## Security

### `dodock_wolf.api.security.list_sites`

Sites with a recent `site_config_risks` or `backup_age_hours` sample, plus the Wolf site itself
(not on a satellite), filtered by the caller's access.

### `dodock_wolf.api.security.get_posture`

Argument: `site` (default: the Wolf site). A site the caller may not see is a 403.

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      The site.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        local
      </code>
    </td>
    
    <td>
      The Wolf site: its System Settings are readable.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        hosts
      </code>
    </td>
    
    <td>
      Hosts of the site.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        recent_hours
      </code>
    </td>
    
    <td>
      Agent samples older than this (3) are not used.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        score
      </code>
    </td>
    
    <td>
      Weight passed over total weight. An unknown check counts as not passed.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        coverage
      </code>
      
      , <code>
        passed
      </code>
      
      , <code>
        failed
      </code>
      
      , <code>
        unknown
      </code>
    </td>
    
    <td>
      Check totals.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        checks
      </code>
    </td>
    
    <td>
      <code>
        {id, label, weight, status, evidence, fix}
      </code>
      
      , <code>
        status
      </code>
      
       being <code>
        pass
      </code>
      
      , <code>
        fail
      </code>
      
       or <code>
        unknown
      </code>
      
      .
    </td>
  </tr>
</tbody>
</table>

The hourly `record_security_scores` job stores the score as the `security_score` metric. See
[Security](/security).

## Regulatory reporting

`get_incident` returns `regulatory`: `null` when neither flag is set, else
`{nis2, gdpr, reference, deadlines}`. Each deadline is
`{id, regime, label, due_at, done_at, status, estimated}`.

<table>
<thead>
  <tr>
    <th>
      <code>
        status
      </code>
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        open
      </code>
    </td>
    
    <td>
      Not done, not due soon.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        due_soon
      </code>
    </td>
    
    <td>
      Due within 6 h.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        overdue
      </code>
    </td>
    
    <td>
      Past due.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        done
      </code>
    </td>
    
    <td>
      Done in time.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        done_late
      </code>
    </td>
    
    <td>
      Done after the deadline.
    </td>
  </tr>
</tbody>
</table>

### `dodock_wolf.api.compliance.get_report`

Argument: `incident`. Returns `{incident, markdown}`: a draft with the facts, the deadlines, the
timeline (linked events and comments, 100 each at most) and the postmortem's impact, root cause,
lessons and action items. Read permission on the incident is enough. Nothing is sent. See
[Compliance](/security/compliance).

## Response actions

### `dodock_wolf.api.response.get_response`

Argument: `incident`.

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        proposals
      </code>
    </td>
    
    <td>
      <code>
        {action, target, agent, host, bench, site, reason, label, executors}
      </code>
      
      , from the incident's security events, without the ones already approved or applied. A block names the attacked <code>
        host
      </code>
      
      , its Wolf Agent in <code>
        agent
      </code>
      
       when it applies it, and <code>
        executors
      </code>
      
       (<code>
        wolf_agent
      </code>
      
      , <code>
        wazuh
      </code>
      
      ).
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        actions
      </code>
    </td>
    
    <td>
      The incident's <strong>
        Wolf Response Action
      </strong>
      
       rows.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        can_approve
      </code>
    </td>
    
    <td>
      Whether the caller may approve.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        default_hours
      </code>
      
      , <code>
        max_hours
      </code>
    </td>
    
    <td>
      Block durations.
    </td>
  </tr>
</tbody>
</table>

### `dodock_wolf.api.response.approve`

POST. Wolf Manager or System Manager only.

<table>
<thead>
  <tr>
    <th>
      Argument
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        incident
      </code>
    </td>
    
    <td>
      The <strong>
        Wolf Incident
      </strong>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        action
      </code>
    </td>
    
    <td>
      <code>
        block_ip
      </code>
      
      , <code>
        disable_user
      </code>
      
      , <code>
        logout_sessions
      </code>
      
       or <code>
        revoke_api_keys
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        target
      </code>
    </td>
    
    <td>
      IP or user.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      For <code>
        block_ip
      </code>
      
      : the attacked host, as proposed.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        agent
      </code>
    </td>
    
    <td>
      For <code>
        block_ip
      </code>
      
      , instead of <code>
        host
      </code>
      
       (older links and pages): the Wolf Agent that applies it.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        duration_hours
      </code>
    </td>
    
    <td>
      For <code>
        block_ip
      </code>
      
      : 1 to 168, for the Wolf Agent's block. A Wazuh block lasts its command's timeout.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        reason
      </code>
    </td>
    
    <td>
      Free text.
    </td>
  </tr>
</tbody>
</table>

Refused targets are a validation error, and nothing is recorded: a private or reserved address,
Administrator, Guest, yourself.

Returns the **Wolf Response Action**. User actions come back `Applied` or `Failed`. Blocks stay
`Approved` until the agent reports (see [protocol](/reference/protocol#response-actions) and
[Response actions](/agent/response-actions)).
