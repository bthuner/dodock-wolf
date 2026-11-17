# Incidents

> Acknowledge, assign, merge, split and close incidents, and write the postmortem.

A **Wolf Incident** groups the events of one rule for one group (a site, bench, host or label). It
is `Open`, then `Acknowledged`, then `Resolved`. Rules with **Auto Resolve** close it when the
condition clears; a person can acknowledge or resolve it at any time, from the Wolf UI, Desk or a
signed link in the alert.

<screenshot alt="A resolved incident in the Wolf UI" caption="A resolved incident: timeline with the deployment, the events, comments and status changes." name="incident-resolved">



</screenshot>

## The timeline

The incident's timeline interleaves its events with comments, assignments and status changes: who
acknowledged or resolved it (from Version history), and auto-resolves (from the incident's own
fields).

**Evidence** is what the incident's rule matched: the events of an event rule, both events of a
sequence rule, and for a metric rule its summary and the events behind the metric (the 502
responses of `http_502`). Evidence is what the event count, Merge, Split and the proposed
[response actions](/agent/response-actions) work on.

The timeline also shows every other event of the incident's scope (site, bench, host) in its window,
whatever the source, as **context**, and the deployment that preceded it. Sharing a site, bench or
host alone never makes an event evidence: a 502 on a site does not belong to the site's *Server
Script can run new code* incident. When the incident took events from other scopes (by
IP or user, or through a sequence rule), it shows the deployments and health events of those scopes
too: a Suricata alert on the database host comes with that host's deployment and failed crons, not
the Error Logs of every site it serves. Each user sees only the scopes they may read.

## Grouping by IP or user

A security event joins the open incident that holds an event naming the same IP or user, seen
within **Entity Correlation Minutes** (60), whatever its source, host, bench or site. A Suricata scan
on one host, a Wazuh SSH alert on another and a web probe on a site, all from one address, read as
one incident.

- Only a public remote address (`payload.ip`) counts. A server's own address, private, loopback and
documentation ranges would tie unrelated attacks together.
- A user ties events only when it is an e-mail address (`root` on two hosts or `Administrator` on
two sites are not one person), and not from failed logins or `sudo` failures, whose user the
attacker chose.
- Only incidents started in the last 24 hours take events by entity, so a scanner coming back every
hour does not keep one incident growing.
- A rule's evidence is its own: when a rule fires on events another incident took by IP, they move
to the rule's incident.

Both settings are in **Wolf Settings → Correlation**. Untick **Group Incidents by IP or User** (on by
default) and events become evidence only of the rules that match them.

Each event says who raised it: the Wolf agent, the Wolf site, Suricata or Wazuh. An event that is
the [same finding](/security/wazuh-suricata#both-one-finding-two-sources) as another source's says
"same finding as …" and links to that row when it is on the page.

## Working an incident

Wolf Managers can:

- **Assign to me**, or set **Assigned To**. Frappe's assignment runs (ToDo, sidebar, notification to
the assignee), and the sidebar's own assign and unassign keep the field in step.
- **Add comment** on the timeline. Wolf Users can comment too.
- Take a [response action](/agent/response-actions) on a security incident.

### Manual incidents

Create one in Desk, or use **Open incident from this event** on a Wolf Event. Manual incidents have
no rule, so the rules engine never auto-resolves them.

### Merge and split

- **Merge into…** (Desk: **Actions**; Wolf UI: **Merge…**) moves events and comments to the target
and resolves the source with **Merged Into** set. If the source came from a rule, further
breaches of that rule feed the target instead of opening a duplicate.
- **Split…** moves the events you tick to a new incident (no rule, **Split From** set).

The Wolf UI's dialogs say what will move and what each incident becomes before you confirm.

## Postmortems

**Write postmortem** on a resolved incident creates a **Wolf Postmortem**:

- summary, impact (scope, duration, event count), root cause, lessons;
- action items, each with an owner, a due date and a status;
- a frozen, escaped snapshot of the timeline.

## Metrics

The **Wolf Incident Metrics** script report gives incidents, MTTA (acknowledged − started) and MTTR
(resolved − started): average, p50 and p90 in minutes, per site, bench, host, rule or severity, over
a date range. Merged incidents are left out, so an outage counts once.

## Regulatory reporting

Flag an incident as a **Significant incident (NIS2 Art. 23)**, a **Major ICT-related incident (DORA
Art. 19)** or a **Personal data breach (GDPR Art. 33)** to start its deadlines. They are shown on
the incident, and the **Regulatory deadline** preset alerts before each one. Wolf tracks dates only:
it does not decide what is reportable and sends nothing to an authority. See
[Compliance](/security/compliance).

## Public status

Give an incident a **Public Title** to control how it appears on a [status page](/alerts/status-pages).
