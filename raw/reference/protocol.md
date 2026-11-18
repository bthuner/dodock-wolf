# Agent protocol

> Every endpoint, field and status code the Wolf Agent, satellites and integrations use to talk to the Wolf App (protocol v1).

All traffic is HTTPS + JSON. All timestamps are ISO-8601 **UTC** strings (`2026-10-29T02:00:13Z`).
The app converts them to the site's system time zone.

Responses follow the Frappe convention: the answer is under the `message` key.

<table>
<thead>
  <tr>
    <th>
      Endpoint
    </th>
    
    <th>
      Method
    </th>
    
    <th>
      Auth
    </th>
    
    <th>
      Section
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.agent.register
      </code>
    </td>
    
    <td>
      POST
    </td>
    
    <td>
      registration token
    </td>
    
    <td>
      <a href="#registration">
        Registration
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.ingest.push
      </code>
    </td>
    
    <td>
      POST
    </td>
    
    <td>
      agent headers
    </td>
    
    <td>
      <a href="#telemetry-push">
        Telemetry push
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.ingest.deployment
      </code>
    </td>
    
    <td>
      POST
    </td>
    
    <td>
      agent headers
    </td>
    
    <td>
      <a href="#deployment-marker">
        Deployment marker
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.ingest.status
      </code>
    </td>
    
    <td>
      GET or POST
    </td>
    
    <td>
      agent headers
    </td>
    
    <td>
      <a href="#wolf-health-heartbeat">
        Wolf health
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.wazuh.alert
      </code>
    </td>
    
    <td>
      POST
    </td>
    
    <td>
      integration headers
    </td>
    
    <td>
      <a href="#wazuh-integration">
        Wazuh integration
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.actions.incident_action
      </code>
    </td>
    
    <td>
      GET, then POST
    </td>
    
    <td>
      signed link
    </td>
    
    <td>
      <a href="#incident-action-links">
        Incident action links
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /api/method/dodock_wolf.api.actions.response_action
      </code>
    </td>
    
    <td>
      GET, then POST
    </td>
    
    <td>
      signed link + login
    </td>
    
    <td>
      <a href="#response-links">
        Response links
      </a>
    </td>
  </tr>
</tbody>
</table>

## Registration

```http [POST /api/method/dodock_wolf.api.agent.register]
POST /api/method/dodock_wolf.api.agent.register
Content-Type: application/json

{
  "registration_token": "<Wolf Settings → Registration Token>",
  "hostname": "bench-01",
  "kind": "agent",
  "agent_version": "0.1.0",
  "os": "Debian GNU/Linux 12",
  "benches": [{"name": "main", "path": "/home/frappe/frappe-bench", "sites": ["a.example.com"]}]
}
```

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
        registration_token
      </code>
    </td>
    
    <td>
      The value of <strong>
        Wolf Settings → Registration Token
      </strong>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        hostname
      </code>
    </td>
    
    <td>
      The host's name. For a satellite, its site name.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        kind
      </code>
    </td>
    
    <td>
      Optional. <code>
        agent
      </code>
      
       (default), <code>
        satellite
      </code>
      
      , or <code>
        integration
      </code>
      
       (see <a href="#wazuh-integration">
        Wazuh integration
      </a>
      
      ).
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        agent_version
      </code>
    </td>
    
    <td>
      Version of the sender.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        os
      </code>
    </td>
    
    <td>
      Operating system string.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        benches
      </code>
    </td>
    
    <td>
      List of <code>
        {name, path, sites}
      </code>
      
      . A satellite adds <code>
        host
      </code>
      
      .
    </td>
  </tr>
</tbody>
</table>

Response:

```json [Response]
{"message": {"agent_id": "WAG-0001", "agent_secret": "<random 40 chars>", "push_interval": 30}}
```

The response also carries `server_version`, the Wolf App version.

The secret is returned once. The agent stores it in `/etc/wolf-agent/config.json` (mode 0600).
The Wolf site keeps only a salted hash (`hmac-sha256$<salt>$<digest>` on **Wolf Agent**), so it
cannot show the secret again. Two things replace it:

- re-registering the same hostname;
- **Rotate secret** on the **Wolf Agent** form, which shows the new secret once.

### Satellites

A satellite is another Frappe site running `dodock_wolf` in satellite mode (see
[Every site on a bench](/install/every-site)). It registers with `hostname` set to its site name
and one bench entry carrying its real `host`:

```json [Satellite registration]
{"registration_token": "...", "kind": "satellite", "hostname": "b.example.com", "agent_version": "0.1.0",
 "os": "Linux-6.1...", "benches": [{"name": "frappe-bench", "path": "/home/frappe/frappe-bench",
 "sites": ["b.example.com"], "host": "bench-01"}]}
```

### Refusals

- A hostname already registered with another kind is refused.
- A site in satellite mode refuses all registrations: register with its central site instead.
- A wrong registration token is refused.
- Registration is rate limited to 20 calls an hour.

## Telemetry push

```http [POST /api/method/dodock_wolf.api.ingest.push]
POST /api/method/dodock_wolf.api.ingest.push
Content-Type: application/json
X-Wolf-Agent-Id: WAG-0001
X-Wolf-Agent-Secret: <secret>

{
  "sent_at": "2026-10-29T02:00:30Z",
  "agent_version": "0.1.0",
  "hostname": "bench-01",
  "behind_proxy": null,
  "metrics": [
    {"metric_name": "cpu_usage", "value": 12.5, "timestamp": "...", "host": "bench-01",
     "bench": null, "site": null, "labels": {}}
  ],
  "events": [
    {"type": "error", "category": "http_502", "severity": "critical", "timestamp": "...",
     "host": "bench-01", "bench": "main", "site": "a.example.com", "source": "nginx",
     "title": "502 on GET /api/method/foo", "fingerprint": "sha1-of-stable-parts",
     "payload": {"route": "/api/method/foo", "status": 502, "count": 14, "sample_lines": ["..."]}}
  ]
}
```

### Headers

<table>
<thead>
  <tr>
    <th>
      Header
    </th>
    
    <th>
      Value
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        X-Wolf-Agent-Id
      </code>
    </td>
    
    <td>
      <code>
        agent_id
      </code>
      
       from registration.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        X-Wolf-Agent-Secret
      </code>
    </td>
    
    <td>
      <code>
        agent_secret
      </code>
      
       from registration.
    </td>
  </tr>
</tbody>
</table>

The same two headers authenticate the deployment marker, the status call and the Wazuh route.

### Body

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
        sent_at
      </code>
    </td>
    
    <td>
      When the request is sent, also for replayed spool batches. Used for <a href="#clock-skew">
        clock skew
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        agent_version
      </code>
    </td>
    
    <td>
      Version of the agent.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        hostname
      </code>
    </td>
    
    <td>
      The host's name.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        behind_proxy
      </code>
    </td>
    
    <td>
      The proxy this host's web traffic comes through (a Press app server's <code>
        proxy_ip
      </code>
      
      ), or <code>
        null
      </code>
      
      . Stored on Wolf Agent; blocks for web clients are then not proposed on this host. Absent from older agents: the stored value stays.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        metrics
      </code>
    </td>
    
    <td>
      List of metric samples.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        events
      </code>
    </td>
    
    <td>
      List of events.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        action_results
      </code>
    </td>
    
    <td>
      Optional. Results of <a href="#response-actions">
        response actions
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        setup
      </code>
    </td>
    
    <td>
      Optional, about once an hour: the agent's own <code>
        wolf-agent doctor
      </code>
      
       run, <code>
        {"checked_at", "checks": [{"area", "status": "ok" | "warn" | "fail" | "info", "title", "fix"}]}
      </code>
      
      . The Wolf site counts failures and warnings, keeps the checks that are not ok on Wolf Agent (100 at most) and shows them on the Monitoring page.
    </td>
  </tr>
</tbody>
</table>

A metric sample:

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
        metric_name
      </code>
    </td>
    
    <td>
      See <a href="#metric-names">
        Metric names
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        value
      </code>
    </td>
    
    <td>
      Number.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        timestamp
      </code>
    </td>
    
    <td>
      UTC.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        host
      </code>
      
      , <code>
        bench
      </code>
      
      , <code>
        site
      </code>
    </td>
    
    <td>
      Scope. <code>
        null
      </code>
      
       where it does not apply.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        labels
      </code>
    </td>
    
    <td>
      Object, for example <code>
        {"mount": "/"}
      </code>
      
       or <code>
        {"queue": "default"}
      </code>
      
      .
    </td>
  </tr>
</tbody>
</table>

An event:

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
        type
      </code>
    </td>
    
    <td>
      See <a href="#event-types">
        Event types
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        category
      </code>
    </td>
    
    <td>
      Finer kind within the type, such as <code>
        http_502
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        severity
      </code>
    </td>
    
    <td>
      <code>
        info
      </code>
      
      , <code>
        warning
      </code>
      
       or <code>
        critical
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        timestamp
      </code>
    </td>
    
    <td>
      UTC.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        host
      </code>
      
      , <code>
        bench
      </code>
      
      , <code>
        site
      </code>
    </td>
    
    <td>
      Scope.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        source
      </code>
    </td>
    
    <td>
      What produced it: <code>
        nginx
      </code>
      
      , <code>
        sshd
      </code>
      
      , <code>
        supervisor
      </code>
      
      …
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        title
      </code>
    </td>
    
    <td>
      One line.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        fingerprint
      </code>
    </td>
    
    <td>
      Hash of the event's stable parts, used to deduplicate.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        payload
      </code>
    </td>
    
    <td>
      Object with the details, per category.
    </td>
  </tr>
</tbody>
</table>

### Response

```json [Response]
{"message": {"metrics": 1, "events": 1, "rejected": [], "push_interval": 30, "health": {...},
             "clock_skew_seconds": 2, "clamped": 0, "queued": true, "actions": []}}
```

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
        metrics
      </code>
      
      , <code>
        events
      </code>
    </td>
    
    <td>
      Items accepted. In async mode, items that passed validation and were queued.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rejected
      </code>
    </td>
    
    <td>
      Items refused.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        push_interval
      </code>
    </td>
    
    <td>
      Seconds between pushes the agent should use.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        health
      </code>
    </td>
    
    <td>
      Wolf's own heartbeat (see <a href="#wolf-health-heartbeat">
        Wolf health
      </a>
      
      ). <code>
        null
      </code>
      
       if the site could not compute it; absent on older servers.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        clock_skew_seconds
      </code>
    </td>
    
    <td>
      <code>
        sent_at
      </code>
      
       minus server time.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        clamped
      </code>
    </td>
    
    <td>
      Timestamps moved back to server time.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        queued
      </code>
    </td>
    
    <td>
      <code>
        true
      </code>
      
       when the batch was queued, <code>
        false
      </code>
      
       when stored during the request. Absent on older servers: agents must not rely on it.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        actions
      </code>
    </td>
    
    <td>
      Response actions approved for this agent, not yet reported. Empty when there are none.
    </td>
  </tr>
</tbody>
</table>

### Response actions

`actions` holds the blocks a Wolf Manager approved for this agent and that it has not yet
reported:

```json [actions]
[{"id": "WRA-00001", "action": "block_ip", "ip": "45.33.32.156", "seconds": 86400}]
```

The agent sends each result with a later push:

```json [action_results]
"action_results": [{"id": "WRA-00001", "ok": true, "detail": "..."}]
```

An id is accepted once, and only from the agent it was given to. See
[Response actions](/agent/response-actions) and [Security](/security).

### Ingest mode

Set in **Wolf Settings → Ingest Mode**.

<table>
<thead>
  <tr>
    <th>
      Mode
    </th>
    
    <th>
      Behaviour
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        async
      </code>
      
       (default)
    </td>
    
    <td>
      The app validates and normalizes the batch during the request, queues the inserts for a background worker and answers <code>
        "queued": true
      </code>
      
      . The worker inserts them and attaches the events to open incidents a few seconds later. A failure in the worker is not reported back to the agent: it is in the site's Error Log.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sync
      </code>
    </td>
    
    <td>
      The batch is stored during the request and <code>
        queued
      </code>
      
       is <code>
        false
      </code>
      
      . Storage errors fail the request (HTTP 5xx) and the agent retries.
    </td>
  </tr>
</tbody>
</table>

If the queue is unreachable in `async` mode, the batch is stored as in `sync` mode. In both
modes, the agent's last seen time and clock skew are recorded during the request, so heartbeats
do not wait for the queue.

### Rate limit

Pushes are counted per agent in one-minute windows: **Wolf Settings → Max Pushes Per Minute**,
default `120`, `0` = off. Over the limit the server answers HTTP 429. Agents and satellites treat
429 like a network error: the batch stays spooled and is replayed after a backoff.

### Scrubbing

The agent removes e-mail addresses, credentials, card numbers and IBANs from event titles and
payloads before sending (see [Scrubbing](/agent/scrubbing)). The server stores what it receives
as is.

### Clock skew

- `sent_at` is stamped when the request is sent, also for replayed spool batches.
- The server records `sent_at - server time` as the agent's `clock_skew_seconds` (positive =
agent ahead, shown on **Wolf Agent**) and returns it. The agent logs a warning above 60 s.
- Metric and event timestamps more than **Wolf Settings → Max Clock Skew** in the future
(default 300 s, `0` = off) are clamped to the server time and counted in `clamped`.
- Rule windows and charts also ignore rows stamped more than a minute in the future.

### Status codes and limits

<table>
<thead>
  <tr>
    <th>
      Answer
    </th>
    
    <th>
      Agent behaviour
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      HTTP 401 / 403
    </td>
    
    <td>
      Bad credentials: the agent stops and logs.
    </td>
  </tr>
  
  <tr>
    <td>
      HTTP 429
    </td>
    
    <td>
      Over the rate limit: treated as a network error.
    </td>
  </tr>
  
  <tr>
    <td>
      HTTP 5xx or network error
    </td>
    
    <td>
      The agent keeps the batch in its on-disk spool and retries with backoff.
    </td>
  </tr>
</tbody>
</table>

At most 5000 metrics and 1000 events per request. The agent splits larger batches.

### Satellites

Satellites use the same endpoint with their satellite credentials.

- They send no metrics.
- At most 100 events per request.
- Every event has explicit `host`, `bench`, `site`, `fingerprint` and `count`. Duplicates seen
before forwarding are merged into one event.
- An empty body every minute is their heartbeat.

<table>
<thead>
  <tr>
    <th>
      Answer
    </th>
    
    <th>
      Satellite behaviour
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      401 / 403
    </td>
    
    <td>
      Retry in 15 minutes.
    </td>
  </tr>
  
  <tr>
    <td>
      Other 4xx (except 408 / 429)
    </td>
    
    <td>
      The batch is dropped.
    </td>
  </tr>
  
  <tr>
    <td>
      5xx or network error
    </td>
    
    <td>
      Retry after 1, 2, 4, 8, then 15 minutes.
    </td>
  </tr>
</tbody>
</table>

## Event types

<table>
<thead>
  <tr>
    <th>
      <code>
        type
      </code>
    </th>
    
    <th>
      Typical <code>
        category
      </code>
      
       values
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        error
      </code>
    </td>
    
    <td>
      <code>
        http_5xx
      </code>
      
      , <code>
        http_502
      </code>
      
      , <code>
        traceback
      </code>
      
      , <code>
        press_job_failed
      </code>
      
      , <code>
        pilot_task_failed
      </code>
      
      , <code>
        backup_failed
      </code>
      
      , <code>
        email_queue_backlog
      </code>
      
      , <code>
        email_queue_error
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        cron_failure
      </code>
    </td>
    
    <td>
      <code>
        scheduled_job
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        worker_failure
      </code>
    </td>
    
    <td>
      <code>
        worker_crash
      </code>
      
      , <code>
        job_failed
      </code>
      
      , <code>
        worker_killed
      </code>
      
      , <code>
        process_down
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        security
      </code>
    </td>
    
    <td>
      <code>
        data_exfiltration
      </code>
      
      , <code>
        ssh_failed_login
      </code>
      
      , <code>
        ssh_root_login
      </code>
      
      , <code>
        ssh_login_after_failures
      </code>
      
      , <code>
        sudo_failure
      </code>
      
      , <code>
        account_created
      </code>
      
      , <code>
        service_account_created
      </code>
      
      , <code>
        admin_group_change
      </code>
      
      , <code>
        web_attack_probe
      </code>
      
      , <code>
        web_sensitive_file_exposed
      </code>
      
      , <code>
        server_script_change
      </code>
      
      , <code>
        client_script_change
      </code>
      
      , <code>
        console_execution
      </code>
      
      , <code>
        permission_change
      </code>
      
      , <code>
        security_settings_weakened
      </code>
      
      , <code>
        api_key_generated
      </code>
      
      , <code>
        api_key_new_ip
      </code>
      
      , <code>
        network_ids_alert
      </code>
      
      , <code>
        hids_alert
      </code>
      
      , <code>
        webhook_external
      </code>
      
      , <code>
        service_exposed
      </code>
      
      , <code>
        insecure_site_config
      </code>
      
      , <code>
        frappe_failed_login
      </code>
      
      , <code>
        new_admin_ip
      </code>
      
      , <code>
        admin_login_new_country
      </code>
      
      , <code>
        privileged_user
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        host_metric_alert
      </code>
    </td>
    
    <td>
      Created by the app: metric rule fired, <code>
        agent_silent
      </code>
      
      , <code>
        scheduler_stalled
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        deployment
      </code>
    </td>
    
    <td>
      <code>
        manual
      </code>
      
      , <code>
        pilot
      </code>
      
       (Pilot tasks, see <a href="/install/pilot">
        Pilot
      </a>
      
      ), <code>
        migrate
      </code>
      
      , <code>
        press
      </code>
      
       (Press agent jobs, see <a href="/install/press">
        Press
      </a>
      
      )
    </td>
  </tr>
</tbody>
</table>

`severity`: `info` | `warning` | `critical`.

### Enrichment at ingest

- **IP reputation.** With IP reputation enabled, a security event whose payload `ip` is on a
downloaded blocklist gets `reputation: {"listed": true, "lists": [...]}` and one severity step
more.
- **MITRE ATT&CK.** Security payloads may carry `attack_techniques`, a list of technique IDs
(`T1110`, `T1552.001`). The app adds `mitre_attack`, a list of `{id, name, tactic}` merging
those IDs with the category's own mapping (see [Security](/security)).
- **Entities.** Every `security` event gets `payload.entities`, whatever its source:
`{"ip": [...], "host": [...], "site": [...], "user": [...]}`, normalised and resolved through
the **Wolf Entity Alias** rows. Agents do not send it: the site computes it.

### Infrastructure and security categories

<table>
<thead>
  <tr>
    <th>
      Category
    </th>
    
    <th>
      Raised by
    </th>
    
    <th>
      When
    </th>
    
    <th>
      Payload
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        process_down
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        supervisor
      </code>
      
       / <code>
        systemd
      </code>
      
      )
    </td>
    
    <td>
      A bench process enters supervisor <code>
        FATAL
      </code>
      
      /<code>
        UNKNOWN
      </code>
      
       or systemd <code>
        failed
      </code>
      
      ; once per transition.
    </td>
    
    <td>
      <code>
        process
      </code>
      
      , <code>
        state
      </code>
      
      , <code>
        detail
      </code>
      
      , <code>
        manager
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        backup_failed
      </code>
    </td>
    
    <td>
      site (Error Log hook)
    </td>
    
    <td>
      An Error Log whose title or method names a backup (S3, Dropbox, Google Drive backup failures) or whose traceback goes through <code>
        frappe/utils/backups.py
      </code>
      
      ; <code>
        critical
      </code>
      
      .
    </td>
    
    <td>
      as <code>
        traceback
      </code>
      
       events
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        email_queue_backlog
      </code>
    </td>
    
    <td>
      site, every 5 min (satellites too)
    </td>
    
    <td>
      Email Queue rows <code>
        Not Sent
      </code>
      
      /<code>
        Sending
      </code>
      
      , due, older than <strong>
        Wolf Settings → Email Queue Stale Minutes
      </strong>
      
       (default 30); one event per site, bumped while it lasts.
    </td>
    
    <td>
      <code>
        pending
      </code>
      
      , <code>
        oldest
      </code>
      
      , <code>
        stale_minutes
      </code>
      
      , <code>
        suspended
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        email_queue_error
      </code>
    </td>
    
    <td>
      site, every 5 min
    </td>
    
    <td>
      Email Queue rows that went to <code>
        Error
      </code>
      
       in the last 15 min.
    </td>
    
    <td>
      <code>
        errors
      </code>
      
      , <code>
        latest
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ssh_login_after_failures
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        sshd
      </code>
      
      )
    </td>
    
    <td>
      A successful SSH login from an address with 5+ failures in the hour before; <code>
        critical
      </code>
      
      .
    </td>
    
    <td>
      <code>
        ip
      </code>
      
      , <code>
        users
      </code>
      
      , <code>
        failures_before
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sudo_failure
      </code>
      
       / <code>
        account_created
      </code>
      
       / <code>
        admin_group_change
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        auth
      </code>
      
      )
    </td>
    
    <td>
      Failed sudo or user not in sudoers / <code>
        useradd
      </code>
      
      , or an account given a login shell or UID 0 (<code>
        change
      </code>
      
      : <code>
        shell
      </code>
      
       / <code>
        uid
      </code>
      
      ) / user added to an admin group (<code>
        critical
      </code>
      
      ).
    </td>
    
    <td>
      <code>
        users
      </code>
      
      , <code>
        count
      </code>
      
      , <code>
        uid
      </code>
      
      , <code>
        shell
      </code>
      
      , <code>
        change
      </code>
      
       / <code>
        group
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        service_account_created
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        auth
      </code>
      
      )
    </td>
    
    <td>
      <code>
        useradd
      </code>
      
       of a system UID (1-999) with a no-login shell, as a package adds one (<code>
        info
      </code>
      
      ).
    </td>
    
    <td>
      <code>
        users
      </code>
      
      , <code>
        count
      </code>
      
      , <code>
        uid
      </code>
      
      , <code>
        shell
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        web_attack_probe
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        nginx
      </code>
      
      )
    </td>
    
    <td>
      Requests matching probe rules, per (site, client) and minute of log time; <code>
        critical
      </code>
      
       from 50.
    </td>
    
    <td>
      <code>
        ip
      </code>
      
      , <code>
        count
      </code>
      
      , <code>
        rules
      </code>
      
      , <code>
        statuses
      </code>
      
      , <code>
        targets
      </code>
      
      , <code>
        user_agents
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        web_sensitive_file_exposed
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        nginx
      </code>
      
      )
    </td>
    
    <td>
      A secret-bearing file (<code>
        .env
      </code>
      
      , <code>
        .git/
      </code>
      
      , keys, dumps) answered with a 2xx; <code>
        critical
      </code>
      
      .
    </td>
    
    <td>
      as <code>
        web_attack_probe
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        server_script_change
      </code>
      
       / <code>
        client_script_change
      </code>
    </td>
    
    <td>
      site (doc events)
    </td>
    
    <td>
      A script created, enabled, or its code, type or trigger changed; <code>
        critical
      </code>
      
       for API / Scheduler Event Server Scripts and guest access.
    </td>
    
    <td>
      <code>
        script
      </code>
      
      , <code>
        change
      </code>
      
      , <code>
        script_type
      </code>
      
      , <code>
        reference_doctype
      </code>
      
      , <code>
        api_method
      </code>
      
      , <code>
        allow_guest
      </code>
      
      , <code>
        by
      </code>
      
      , <code>
        excerpt
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        console_execution
      </code>
    </td>
    
    <td>
      site (Console Log)
    </td>
    
    <td>
      A System Console run.
    </td>
    
    <td>
      <code>
        console_log
      </code>
      
      , <code>
        by
      </code>
      
      , <code>
        type
      </code>
      
      , <code>
        committed
      </code>
      
      , <code>
        excerpt
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        permission_change
      </code>
    </td>
    
    <td>
      site (Role Permission Manager request, Role Profile, Custom DocPerm, User Permission, User)
    </td>
    
    <td>
      A permission rule added, changed, removed or reset; a Role Profile created or granting more roles; a User Permission letting its user see more; a Website user given desk access.
    </td>
    
    <td>
      <code>
        doctype
      </code>
      
      , <code>
        role
      </code>
      
      , <code>
        action
      </code>
      
      , <code>
        ptype
      </code>
      
      , <code>
        value
      </code>
      
       / <code>
        role_profile
      </code>
      
      , <code>
        roles
      </code>
      
      , <code>
        added
      </code>
      
       / <code>
        kind
      </code>
      
       (<code>
        custom_docperm
      </code>
      
      , <code>
        user_permission
      </code>
      
      , <code>
        desk_access
      </code>
      
      ), <code>
        granted
      </code>
      
      , <code>
        revoked
      </code>
      
      , <code>
        everyone
      </code>
      
      , <code>
        user
      </code>
      
      , <code>
        allow
      </code>
      
      , <code>
        for_value
      </code>
      
      , <code>
        previous
      </code>
      
      , <code>
        via
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        security_settings_weakened
      </code>
    </td>
    
    <td>
      site (System Settings)
    </td>
    
    <td>
      A save that lowers a defence; <code>
        critical
      </code>
      
      .
    </td>
    
    <td>
      <code>
        changes
      </code>
      
       (<code>
        field
      </code>
      
      , <code>
        label
      </code>
      
      , <code>
        old
      </code>
      
      , <code>
        new
      </code>
      
      ), <code>
        by
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        api_key_generated
      </code>
    </td>
    
    <td>
      site (User)
    </td>
    
    <td>
      A new API secret; <code>
        critical
      </code>
      
       for privileged users.
    </td>
    
    <td>
      <code>
        user
      </code>
      
      , <code>
        api_key
      </code>
      
      , <code>
        privileged
      </code>
      
      , <code>
        by
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        hids_alert
      </code>
    </td>
    
    <td>
      agent on the Wazuh manager's host (<code>
        alerts.json
      </code>
      
      )
    </td>
    
    <td>
      One per rule and subject (source IP, else host) per minute of log time; level 12+ critical, 7–11 warning; <code>
        sca
      </code>
      
       excluded by default, <code>
        dodock_wolf
      </code>
      
       always.
    </td>
    
    <td>
      <code>
        ip
      </code>
      
      , <code>
        user
      </code>
      
      , <code>
        count
      </code>
      
      , <code>
        rule_id
      </code>
      
      , <code>
        level
      </code>
      
      , <code>
        description
      </code>
      
      , <code>
        groups
      </code>
      
      , <code>
        wazuh_agent
      </code>
      
      , <code>
        location
      </code>
      
      , <code>
        decoder
      </code>
      
      , <code>
        sample_lines
      </code>
      
      , <code>
        wazuh_alert_id
      </code>
      
      , <code>
        attack_techniques
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        network_ids_alert
      </code>
    </td>
    
    <td>
      agent (Suricata <code>
        eve.json
      </code>
      
      )
    </td>
    
    <td>
      One per signature and remote address per minute of log time; severity from the rule priority (1 critical, 2 warning, 3 info).
    </td>
    
    <td>
      <code>
        ip
      </code>
      
       (remote address), <code>
        count
      </code>
      
      , <code>
        signature
      </code>
      
      , <code>
        sid
      </code>
      
      , <code>
        rev
      </code>
      
      , <code>
        rule_category
      </code>
      
      , <code>
        priority
      </code>
      
      , <code>
        action
      </code>
      
      , <code>
        src_ip
      </code>
      
      /<code>
        dest_ip
      </code>
      
      /ports, <code>
        proto
      </code>
      
      , <code>
        app_proto
      </code>
      
      , <code>
        flow_id
      </code>
      
      , <code>
        community_id
      </code>
      
      , <code>
        targets
      </code>
      
      , <code>
        attack_techniques
      </code>
      
      , <code>
        http_hostname
      </code>
      
      , <code>
        url
      </code>
      
      , <code>
        http_method
      </code>
      
      , <code>
        http_status
      </code>
      
      , <code>
        http_user_agent
      </code>
      
      , <code>
        tls_sni
      </code>
      
      , <code>
        dns_query
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        api_key_new_ip
      </code>
    </td>
    
    <td>
      site (<code>
        after_request
      </code>
      
      )
    </td>
    
    <td>
      A successful API-key request from an address outside every /24 or /64 the key was used from, once the key's first 24 h are past; <code>
        critical
      </code>
      
       for privileged users.
    </td>
    
    <td>
      <code>
        user
      </code>
      
      , <code>
        api_key
      </code>
      
      , <code>
        ip
      </code>
      
      , <code>
        privileged
      </code>
      
      , <code>
        path
      </code>
      
      , <code>
        user_agent
      </code>
      
      , <code>
        known_ips
      </code>
      
       (last 10), <code>
        known_count
      </code>
      
      , <code>
        key_first_seen
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        data_exfiltration
      </code>
    </td>
    
    <td>
      site (<code>
        after_request
      </code>
      
      )
    </td>
    
    <td>
      A user's exports and list reads this hour past the floor and the factor times their largest hour of 14 days; <code>
        critical
      </code>
      
       at 20x or without history.
    </td>
    
    <td>
      <code>
        user
      </code>
      
      , <code>
        hour_bytes
      </code>
      
      , <code>
        hour_requests
      </code>
      
      , <code>
        hour_rows
      </code>
      
      , <code>
        baseline_bytes
      </code>
      
      , <code>
        ratio
      </code>
      
      , <code>
        factor
      </code>
      
      , <code>
        floor_bytes
      </code>
      
      , <code>
        last_request
      </code>
      
       (<code>
        kind
      </code>
      
      , <code>
        label
      </code>
      
      , <code>
        method
      </code>
      
      , <code>
        doctype
      </code>
      
      , <code>
        bytes
      </code>
      
      ), <code>
        ip
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        service_exposed
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        exposure
      </code>
      
      )
    </td>
    
    <td>
      A bench port starts listening beyond loopback (or its addresses change); <code>
        critical
      </code>
      
       for Redis.
    </td>
    
    <td>
      <code>
        port
      </code>
      
      , <code>
        service
      </code>
      
      , <code>
        addresses
      </code>
      
      , <code>
        note
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        insecure_site_config
      </code>
    </td>
    
    <td>
      agent (<code>
        source
      </code>
      
      : <code>
        exposure
      </code>
      
      )
    </td>
    
    <td>
      A site's risky settings change and are not empty; <code>
        critical
      </code>
      
       with <code>
        developer_mode
      </code>
      
      .
    </td>
    
    <td>
      <code>
        findings
      </code>
      
       (<code>
        setting
      </code>
      
      , <code>
        value
      </code>
      
      , <code>
        why
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        honeytoken_triggered
      </code>
    </td>
    
    <td>
      site (Activity Log, <code>
        before_request
      </code>
      
      )
    </td>
    
    <td>
      A decoy user, API key or path was used; <code>
        critical
      </code>
      
      , once per token and address every 10 min.
    </td>
    
    <td>
      <code>
        kind
      </code>
      
       (<code>
        user
      </code>
      
      , <code>
        api_key
      </code>
      
      , <code>
        path
      </code>
      
      ), <code>
        token
      </code>
      
      , <code>
        ip
      </code>
      
      , <code>
        user_agent
      </code>
      
      , <code>
        path
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        regulatory_deadline
      </code>
    </td>
    
    <td>
      app (<code>
        source
      </code>
      
      : <code>
        wolf
      </code>
      
      , every 5 min)
    </td>
    
    <td>
      A NIS2 / GDPR deadline of a flagged incident is within 6 h (<code>
        warning
      </code>
      
      ) or passed (<code>
        critical
      </code>
      
      ); once per obligation and stage, linked to the incident.
    </td>
    
    <td>
      <code>
        incident
      </code>
      
      , <code>
        obligation
      </code>
      
      , <code>
        regime
      </code>
      
      , <code>
        stage
      </code>
      
      , <code>
        due_at
      </code>
      
      , <code>
        estimated
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        webhook_external
      </code>
    </td>
    
    <td>
      site (Webhook)
    </td>
    
    <td>
      A Webhook created, enabled or pointed at another host.
    </td>
    
    <td>
      <code>
        webhook
      </code>
      
      , <code>
        doctype
      </code>
      
      , <code>
        event
      </code>
      
      , <code>
        domain
      </code>
      
      , <code>
        previous_domain
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        admin_login_new_country
      </code>
    </td>
    
    <td>
      site (Activity Log hook)
    </td>
    
    <td>
      A privileged login from a new IP whose country (offline <strong>
        GeoIP Database
      </strong>
      
      ) differs from the countries of all the user's earlier logins; <code>
        critical
      </code>
      
      .
    </td>
    
    <td>
      <code>
        user
      </code>
      
      , <code>
        ip
      </code>
      
      , <code>
        country
      </code>
      
      , <code>
        known_countries
      </code>
    </td>
  </tr>
</tbody>
</table>

## Metric names

Metrics emitted by the agent, unless noted.

<table>
<thead>
  <tr>
    <th>
      <code>
        metric_name
      </code>
    </th>
    
    <th>
      Unit
    </th>
    
    <th>
      Scope / labels
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        cpu_usage
      </code>
    </td>
    
    <td>
      %
    </td>
    
    <td>
      host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        memory_used_percent
      </code>
    </td>
    
    <td>
      %
    </td>
    
    <td>
      host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        swap_used_percent
      </code>
    </td>
    
    <td>
      %
    </td>
    
    <td>
      host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        disk_used_percent
      </code>
    </td>
    
    <td>
      %
    </td>
    
    <td>
      host, <code>
        labels.mount
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        agent_setup_failed
      </code>
      
      , <code>
        agent_setup_warnings
      </code>
    </td>
    
    <td>
      checks
    </td>
    
    <td>
      host: from the agent's hourly <code>
        wolf-agent doctor
      </code>
      
       run
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        load_1m
      </code>
      
       / <code>
        load_5m
      </code>
      
       / <code>
        load_15m
      </code>
    </td>
    
    <td>
      —
    </td>
    
    <td>
      host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        load_per_core
      </code>
    </td>
    
    <td>
      —
    </td>
    
    <td>
      host (<code>
        load_1m
      </code>
      
       / CPU count)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        http_requests
      </code>
    </td>
    
    <td>
      count per minute of log time
    </td>
    
    <td>
      host, bench, site
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        http_5xx
      </code>
    </td>
    
    <td>
      count per minute of log time
    </td>
    
    <td>
      host, bench, site
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        http_502
      </code>
    </td>
    
    <td>
      count per minute of log time
    </td>
    
    <td>
      host, bench, site
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        queue_length
      </code>
    </td>
    
    <td>
      jobs
    </td>
    
    <td>
      host, bench, <code>
        labels.queue
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_failed_jobs
      </code>
    </td>
    
    <td>
      jobs
    </td>
    
    <td>
      host, bench, <code>
        labels.queue
      </code>
      
      : size of RQ's failed-job registry (<code>
        rq:failed:<queue>
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_failed_jobs_added
      </code>
    </td>
    
    <td>
      jobs per push interval
    </td>
    
    <td>
      host, bench, <code>
        labels.queue
      </code>
      
      : increase of that registry since the previous push (never negative; none on the agent's first cycle)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_long_running_jobs
      </code>
    </td>
    
    <td>
      jobs
    </td>
    
    <td>
      host, bench, <code>
        labels.queue
      </code>
      
      : started jobs (<code>
        rq:wip:<queue>
      </code>
      
      ) running longer than <code>
        rq.long_job_minutes
      </code>
      
       (default 30)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_workers
      </code>
    </td>
    
    <td>
      workers
    </td>
    
    <td>
      host, bench: live members of <code>
        rq:workers
      </code>
      
       (dead workers whose key expired are not counted)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        redis_used_memory_percent
      </code>
    </td>
    
    <td>
      %
    </td>
    
    <td>
      host, bench, <code>
        labels.of
      </code>
      
      : queue Redis <code>
        used_memory
      </code>
      
       / <code>
        maxmemory
      </code>
      
       (<code>
        of=maxmemory
      </code>
      
      ), else / <code>
        total_system_memory
      </code>
      
       (<code>
        of=system
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        redis_evicted_keys
      </code>
    </td>
    
    <td>
      keys per push interval
    </td>
    
    <td>
      host, bench: increase of <code>
        evicted_keys
      </code>
      
       in the queue Redis
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        backup_age_hours
      </code>
    </td>
    
    <td>
      hours
    </td>
    
    <td>
      host, bench, site: age of the newest <code>
        sites/<site>/private/backups/*-database.sql*
      </code>
      
      ; every 10 min; sites without any backup send nothing
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        tls_days_left
      </code>
    </td>
    
    <td>
      days (negative = expired)
    </td>
    
    <td>
      host, bench, site, <code>
        labels.domain
      </code>
      
      : certificate <code>
        notAfter
      </code>
      
       of each public site name / custom domain, hourly
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        hsts_max_age_days
      </code>
    </td>
    
    <td>
      days
    </td>
    
    <td>
      host, bench, site, <code>
        labels.domain
      </code>
      
      : <code>
        Strict-Transport-Security
      </code>
      
       max-age of the first response to <code>
        HEAD /
      </code>
      
       on the TLS check's connection, 0 without the header; no sample when no HTTP response came back; hourly
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        app_version
      </code>
    </td>
    
    <td>
      version number
    </td>
    
    <td>
      host, bench, <code>
        labels.app
      </code>
      
      : <code>
        __version__
      </code>
      
       of <code>
        apps/<app>/<app>/__init__.py
      </code>
      
       as major × 10⁶ + minor × 10³ + patch (15.100.0 → 15100000); development versions (<code>
        16.0.0-dev
      </code>
      
      ) are not sent; hourly (<code>
        versions.interval
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        site_setting
      </code>
    </td>
    
    <td>
      value
    </td>
    
    <td>
      host, bench, site, <code>
        labels.setting
      </code>
      
      : a System Settings value read from the site's database (<code>
        enable_two_factor_auth
      </code>
      
      , <code>
        enable_password_policy
      </code>
      
      , <code>
        minimum_password_score
      </code>
      
      , <code>
        allow_consecutive_login_attempts
      </code>
      
      , <code>
        allow_guests_to_upload_files
      </code>
      
      ; unset → 0) and <code>
        system_manager_2fa
      </code>
      
       (the System Manager role's <code>
        two_factor_auth
      </code>
      
      ); hourly (<code>
        site_settings.interval
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        exposed_services
      </code>
    </td>
    
    <td>
      count
    </td>
    
    <td>
      host: bench ports (MariaDB/Postgres, bench Redis, socket.io, gunicorn) listening on all interfaces or a public address, from <code>
        /proc/net/tcp{,6}
      </code>
      
      ; every 10 min
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        integrity_files
      </code>
    </td>
    
    <td>
      count
    </td>
    
    <td>
      bench (or host, for <code>
        /etc
      </code>
      
       paths): files under <a href="/security/detection#file-integrity">
        file integrity
      </a>
      
       watch (app code, site configs, nginx and supervisor config); every 15 min
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        integrity_unreadable
      </code>
    </td>
    
    <td>
      count
    </td>
    
    <td>
      bench (or host): watched files or folders the agent could not read, kept at their baseline; every 15 min
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        bench_outbound_destinations
      </code>
    </td>
    
    <td>
      count
    </td>
    
    <td>
      bench (the bench folder's user): public network and port destinations of its established client connections, sampled every minute
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        bench_new_outbound_usual
      </code>
    </td>
    
    <td>
      count
    </td>
    
    <td>
      bench: new destinations on usual ports this sample, counted rather than reported
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        site_config_risks
      </code>
    </td>
    
    <td>
      count
    </td>
    
    <td>
      host, bench, site: <code>
        developer_mode
      </code>
      
      , <code>
        allow_tests
      </code>
      
      , a plain-HTTP <code>
        host_name
      </code>
      
      , <code>
        allow_cors: "*"
      </code>
      
       in the merged site config; every 10 min
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        security_score
      </code>
    </td>
    
    <td>
      0–100
    </td>
    
    <td>
      site: written by the app (hourly), not the agent; see <a href="/security">
        Security
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        user_export_bytes
      </code>
    </td>
    
    <td>
      bytes per hour
    </td>
    
    <td>
      site, <code>
        labels.user
      </code>
      
      : response bytes of a user's exports and list reads over the past hour, written by the app (hourly); see <a href="/security">
        Security
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        db_threads_connected
      </code>
    </td>
    
    <td>
      connections
    </td>
    
    <td>
      host, bench (when one bench uses the server), <code>
        labels.db
      </code>
      
       (<code>
        host:port
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        db_connections_used_percent
      </code>
    </td>
    
    <td>
      %
    </td>
    
    <td>
      same: <code>
        Threads_connected
      </code>
      
       / <code>
        max_connections
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        db_slow_queries
      </code>
    </td>
    
    <td>
      queries per push interval
    </td>
    
    <td>
      same: increase of <code>
        Slow_queries
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        db_replication_lag_seconds
      </code>
    </td>
    
    <td>
      s
    </td>
    
    <td>
      same: <code>
        Seconds_Behind_Master
      </code>
      
      , only on a replica and with REPLICATION CLIENT
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        db_replication_running
      </code>
    </td>
    
    <td>
      0/1
    </td>
    
    <td>
      same: both replica threads running
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        bench_processes_down
      </code>
    </td>
    
    <td>
      processes
    </td>
    
    <td>
      host, bench, <code>
        labels.manager
      </code>
      
      : supervisor processes in STOPPED/EXITED/BACKOFF/FATAL/UNKNOWN, or systemd units <code>
        failed
      </code>
      
       / restart loop
    </td>
  </tr>
</tbody>
</table>

Agents older than these signals do not send them. The app accepts any metric name, so no server
change is needed to receive them; the presets only need the samples to exist.

## Deployment marker

```http [POST /api/method/dodock_wolf.api.ingest.deployment]
POST /api/method/dodock_wolf.api.ingest.deployment
X-Wolf-Agent-Id: WAG-0001
X-Wolf-Agent-Secret: <secret>

{"bench": "main", "site": null, "note": "bench update", "source": "manual", "timestamp": "...",
 "silence_minutes": 15}
```

Equivalent to pushing a single `deployment` event. `wolf-agent mark-deployment` calls it (see
[Commands](/agent/commands)).

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
        bench
      </code>
      
      , <code>
        site
      </code>
    </td>
    
    <td>
      Scope of the deployment.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        note
      </code>
    </td>
    
    <td>
      Free text.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        source
      </code>
    </td>
    
    <td>
      For example <code>
        manual
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        timestamp
      </code>
    </td>
    
    <td>
      UTC.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        silence_minutes
      </code>
    </td>
    
    <td>
      Optional. Positive integer: also open a maintenance window.
    </td>
  </tr>
</tbody>
</table>

`silence_minutes` was added after v1 and is backward compatible: older apps ignore it, and
agents omit it unless `--silence` is given. When it is a positive integer, the app creates a
**Wolf Silence** from now for that many minutes, capped at 24 h, scoped to the agent's host plus
the given bench and site.

- Incidents matching the silence still open and update, so the timeline stays complete.
- Their notifications are held back.
- Incidents still open when the window ends are notified then.

Response:

```json [Response]
{"message": {"event": "<Wolf Event name>", "silence": "WSIL-00001", "silence_until": "2026-10-29 02:15:00"}}
```

`silence` and `silence_until` (site time zone) are present only when a silence was created.

<warning>

An agent that asked for a silence and gets no `silence` key back is talking to an app without
silence support, and should warn.

</warning>

## Wolf health (heartbeat)

```http [GET|POST /api/method/dodock_wolf.api.ingest.status]
GET /api/method/dodock_wolf.api.ingest.status
X-Wolf-Agent-Id: WAG-0001
X-Wolf-Agent-Secret: <secret>
```

Response: `{"message": {"agent": "WAG-0001", "push_interval": 30, "health": {...}}}`.

The same `health` object comes back with every push, so the agent does not need to poll
`status`. It is for `wolf-agent check` and scripts. The call is read-only: it does not update
the agent's last seen time.

```json [health]
{
  "ok": false,
  "problems": ["alert rules not evaluated for 12 min; scheduler disabled (pause_scheduler)"],
  "checked_at": "2026-10-29T02:12:30Z",
  "server_version": "0.1.0",
  "rules": {"last_evaluated": "2026-10-29T02:00:01Z", "age_seconds": 749},
  "scheduler": {"enabled": false, "reason": "pause_scheduler",
                "last_job_run": "2026-10-29T02:00:00Z", "age_seconds": 750},
  "queues": {"lengths": {"short": 0, "default": 3, "long": 0}, "workers": 2,
             "ingest_queue": "short", "ingest_backlog_seconds": null}
}
```

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
        rules.last_evaluated
      </code>
    </td>
    
    <td>
      Latest <code>
        last_evaluated
      </code>
      
       over enabled <strong>
        Wolf Alert Rules
      </strong>
      
       (the rule engine runs at each scheduler tick); <code>
        null
      </code>
      
       if no rule ran yet.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        scheduler.enabled
      </code>
      
       / <code>
        reason
      </code>
    </td>
    
    <td>
      <code>
        false
      </code>
      
       with <code>
        maintenance_mode
      </code>
      
      , <code>
        pause_scheduler
      </code>
      
      , <code>
        disable_scheduler
      </code>
      
       or <code>
        enable_scheduler unset in System Settings
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        scheduler.last_job_run
      </code>
    </td>
    
    <td>
      Latest <code>
        Scheduled Job Type.last_execution
      </code>
      
      , stamped when a worker starts a job.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        scheduler.tick_seconds
      </code>
    </td>
    
    <td>
      Seconds between Frappe scheduler ticks, so between two rule evaluations: 240 on Frappe 15 and Dodock unless <code>
        scheduler_tick_interval
      </code>
      
       is set; <code>
        null
      </code>
      
       on a Frappe without the setting. Informative, never a problem.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        *.age_seconds
      </code>
    </td>
    
    <td>
      Server-side <code>
        now - timestamp
      </code>
      
      , so agent clock skew does not matter. <strong>
        Negative
      </strong>
      
       when the stored time lies in the future, which happens after a system time-zone change and stalls the scheduler until that time.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        queues
      </code>
    </td>
    
    <td>
      RQ queue lengths and worker count for the bench, or <code>
        {"error": "..."}
      </code>
      
       if Redis is unreachable.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        queues.ingest_backlog_seconds
      </code>
    </td>
    
    <td>
      How long the oldest job of the ingest queue (<code>
        ingest_queue
      </code>
      
      ) has waited; <code>
        null
      </code>
      
       when it is empty. Queued pushes are answered before they are stored, so this is the only sign that telemetry is not arriving.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ok
      </code>
      
       / <code>
        problems
      </code>
    </td>
    
    <td>
      The server's own reading, with a 5 minute threshold.
    </td>
  </tr>
</tbody>
</table>

Two things are problems:

- **staleness**: `abs(age) >= stale threshold` on `rules`, or on `scheduler` when no rule is
enabled;
- **ingest backlog**: `ingest_backlog_seconds >= stale threshold`.

Scheduler and queue state are context appended to the staleness text. The agent applies its own
threshold (`watchdog.stale_minutes`) to the raw ages rather than trusting `ok`.

While rules are stale, each push also records a `host_metric_alert` / `scheduler_stalled` event
on the site, bumped rather than duplicated for 15 minutes. The **Scheduler stalled** preset turns
it into an incident once the scheduler runs again. A stalled site cannot alert about itself, so
the live alert is raised by the agent watchdog through its own fallback channel (see
[Watchdog](/agent/watchdog)).

## Wazuh integration

```http [POST /api/method/dodock_wolf.api.wazuh.alert]
POST /api/method/dodock_wolf.api.wazuh.alert
X-Wolf-Agent-Id: WAG-0005
X-Wolf-Agent-Secret: <secret>
Content-Type: application/json

<one Wazuh alert, as Wazuh writes it in alerts.json>
```

<table>
<thead>
  <tr>
    <th>
      Aspect
    </th>
    
    <th>
      Rule
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Credentials
    </td>
    
    <td>
      A <strong>
        Wolf Agent
      </strong>
      
       registered with <code>
        "kind": "integration"
      </code>
      
      , through the same <a href="#registration">
        registration
      </a>
      
      . It is never reported silent, since it only pushes when Wazuh has an alert.
    </td>
  </tr>
  
  <tr>
    <td>
      What Wolf keeps
    </td>
    
    <td>
      The alert becomes a <code>
        hids_alert
      </code>
      
       event, mapped like the agent's <code>
        alerts.json
      </code>
      
       reader. The <code>
        dodock_wolf
      </code>
      
       group (Wazuh's alerts on Wolf's own export) and the <code>
        sca
      </code>
      
       group are not stored, and the answer says why: <code>
        {"stored": false, "reason": ...}
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      Repeats
    </td>
    
    <td>
      The same rule and subject within 10 minutes bump the event's count.
    </td>
  </tr>
  
  <tr>
    <td>
      Rate limit
    </td>
    
    <td>
      Up to 600 calls a minute per integration.
    </td>
  </tr>
  
  <tr>
    <td>
      Sender
    </td>
    
    <td>
      <a href="https://github.com/bthuner/dodock-wolf/blob/main/agent/wazuh/custom-dodock-wolf" rel="nofollow">
        <code>
          agent/wazuh/custom-dodock-wolf
        </code>
      </a>
      
      , the script Wazuh's integration daemon runs.
    </td>
  </tr>
</tbody>
</table>

See [Wazuh and Suricata](/security/wazuh-suricata).

## Incident action links

Email, Raven and webhook alerts for unresolved incidents carry signed links:

```http [GET /api/method/dodock_wolf.api.actions.incident_action]
GET /api/method/dodock_wolf.api.actions.incident_action
    ?incident=WINC-00012&action=ack|resolve&expires=<unix seconds>[&actor=<email>]&sig=<hex>
```

<table>
<thead>
  <tr>
    <th>
      Parameter
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
        ack
      </code>
      
       or <code>
        resolve
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        expires
      </code>
    </td>
    
    <td>
      Unix seconds.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        actor
      </code>
    </td>
    
    <td>
      The recipient's address in emails (one email per recipient). Absent for Raven and webhooks.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sig
      </code>
    </td>
    
    <td>
      HMAC-SHA256 over <code>
        wolf-incident-action\n<incident>\n<action>\n<expires>\n<actor>
      </code>
      
      , with a key derived from the site's <code>
        encryption_key
      </code>
      
      .
    </td>
  </tr>
</tbody>
</table>

Links expire after **Wolf Settings → Action Link Hours** (default 24, `0` disables them).

GET only renders a confirmation page. Its button POSTs the same parameters, and only the POST
acknowledges or resolves, so link scanners cannot act on an incident. The incident records
`acknowledged_by` / `resolved_by` as the logged-in user, else the `actor`, else `link`.

Where the links appear:

<table>
<thead>
  <tr>
    <th>
      Channel
    </th>
    
    <th>
      Form
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Webhook
    </td>
    
    <td>
      <code>
        incident.actions = {"ack": "...", "resolve": "..."}
      </code>
      
      , empty once resolved
    </td>
  </tr>
  
  <tr>
    <td>
      Slack
    </td>
    
    <td>
      Block Kit buttons
    </td>
  </tr>
  
  <tr>
    <td>
      Mattermost
    </td>
    
    <td>
      Attachment links
    </td>
  </tr>
  
  <tr>
    <td>
      ntfy
    </td>
    
    <td>
      <code>
        Actions
      </code>
      
       header
    </td>
  </tr>
  
  <tr>
    <td>
      Matrix, Gotify, SMS
    </td>
    
    <td>
      Incident URL only
    </td>
  </tr>
</tbody>
</table>

Hourly digests are posted to webhooks as:

```json [Digest webhook body]
{"text": "...", "digest": [{"incident", "kind", "severity", "title", "at", "url"}]}
```

### Response links

One link per action Wolf proposes on the incident, up to 5:

```http [GET /api/method/dodock_wolf.api.actions.response_action]
GET /api/method/dodock_wolf.api.actions.response_action
    ?incident=WINC-00012&action=block_ip|disable_user|logout_sessions|revoke_api_keys&target=<ip or user>
    [&agent=<Wolf Agent>&hours=<1..168>]&expires=<unix seconds>[&actor=<email>]&sig=<hex>
```

`sig` is HMAC-SHA256 over
`wolf-response-action\n<incident>\n<action>\n<target>\n<agent>\n<hours>\n<expires>\n<actor>`
with the same key.

<caution>

Only a logged-in Wolf Manager or System Manager can confirm (POST), through the Response panel's
rules.

</caution>

<table>
<thead>
  <tr>
    <th>
      Channel
    </th>
    
    <th>
      Form
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Email (one per recipient), Raven, Matrix, Gotify, ntfy
    </td>
    
    <td>
      Links in the text and HTML of the alert
    </td>
  </tr>
  
  <tr>
    <td>
      Webhook
    </td>
    
    <td>
      <code>
        incident.responses = [{"label", "url"}]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Slack
    </td>
    
    <td>
      Buttons
    </td>
  </tr>
  
  <tr>
    <td>
      Mattermost
    </td>
    
    <td>
      Links
    </td>
  </tr>
  
  <tr>
    <td>
      SMS
    </td>
    
    <td>
      None
    </td>
  </tr>
</tbody>
</table>

## Native channels

Each native channel is a pure builder in
[`dodock_wolf/wolf/channels/`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/channels/)
that maps a notification to the documented format of the service. The module docstrings cite the
reference pages. See [Channels](/alerts/channels) for setup.

<table>
<thead>
  <tr>
    <th>
      Channel
    </th>
    
    <th>
      Request
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Slack
    </td>
    
    <td>
      <code>
        POST <webhook>
      </code>
      
       <code>
        {"text", "attachments": [{"color", "fallback", "blocks": [section, actions]}]}
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Mattermost
    </td>
    
    <td>
      <code>
        POST <webhook>
      </code>
      
       <code>
        {"attachments": [{"fallback", "color", "pretext", "title", "title_link", "text", "fields", "footer"}]}
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Matrix
    </td>
    
    <td>
      <code>
        PUT <homeserver>/_matrix/client/v3/rooms/<room>/send/m.room.message/wolf-<attempt>
      </code>
      
       (Bearer token) <code>
        {"msgtype": "m.text", "body", "format": "org.matrix.custom.html", "formatted_body"}
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      ntfy
    </td>
    
    <td>
      <code>
        POST <server>/<topic>
      </code>
      
      , body = text, headers <code>
        Title
      </code>
      
       (RFC 2047 when not ASCII), <code>
        Priority
      </code>
      
      , <code>
        Tags
      </code>
      
      , <code>
        Click
      </code>
      
      , <code>
        Actions
      </code>
      
      , optional <code>
        Authorization: Bearer
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Gotify
    </td>
    
    <td>
      <code>
        POST <server>/message
      </code>
      
       (<code>
        X-Gotify-Key
      </code>
      
      ) <code>
        {"title", "message", "priority", "extras": {"client::display", "client::notification": {"click": {"url"}}}}
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      SMS
    </td>
    
    <td>
      The configured template, one request per number
    </td>
  </tr>
  
  <tr>
    <td>
      PagerDuty
    </td>
    
    <td>
      <code>
        POST <events url>
      </code>
      
       <code>
        {"routing_key", "event_action", "dedup_key": "<incident>", "payload": {"summary", "source", "severity", "component", "group", "class", "custom_details"}, "client", "client_url", "links"}
      </code>
      
       (payload on trigger only)
    </td>
  </tr>
</tbody>
</table>

PagerDuty event actions:

<table>
<thead>
  <tr>
    <th>
      Wolf notification
    </th>
    
    <th>
      <code>
        event_action
      </code>
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        fired
      </code>
      
      , <code>
        reopened
      </code>
      
      , <code>
        escalated
      </code>
    </td>
    
    <td>
      <code>
        trigger
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Acknowledgement
    </td>
    
    <td>
      <code>
        acknowledge
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Resolution
    </td>
    
    <td>
      <code>
        resolve
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Test
    </td>
    
    <td>
      <code>
        trigger
      </code>
      
      , then <code>
        resolve
      </code>
    </td>
  </tr>
</tbody>
</table>

### Wolf Delivery

Every request is recorded as a **Wolf Delivery**:

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
        incident
      </code>
      
      , <code>
        alert_rule
      </code>
    </td>
    
    <td>
      What was notified.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        at
      </code>
    </td>
    
    <td>
      When.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        channel_type
      </code>
    </td>
    
    <td>
      Slack, Matrix, PagerDuty…
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        target
      </code>
    </td>
    
    <td>
      The destination without secrets: host, room, masked phone numbers.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        kind
      </code>
      
      , <code>
        action
      </code>
      
      , <code>
        digest
      </code>
    </td>
    
    <td>
      What was sent.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ok
      </code>
      
      , <code>
        http_status
      </code>
    </td>
    
    <td>
      The result.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        error
      </code>
    </td>
    
    <td>
      The error, with secrets and URL paths and queries removed.
    </td>
  </tr>
</tbody>
</table>

Digests of native channels are merged on a SHA-256 of the channel settings, and the digest item
keeps a reference to the channel row rather than any secret.
