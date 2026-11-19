# Introduction

> What Dodock Wolf is, what it watches, and how its two parts fit together.

Dodock Wolf is self-hosted observability for Frappe benches, ERPNext and Dokos sites and their
Linux hosts. It catches 502 windows, failed nightly crons, worker crashes and suspicious logins
before customers notice, and it keeps all data on a Frappe site you run.

<screenshot alt="The Operations page of the Wolf UI on the demo bench" caption="Operations, the Wolf UI's general overview, after the demo bench's 2AM scenario." name="operations">



</screenshot>

## Two parts

<card-group>
<card icon="i-lucide-app-window" title="Wolf App" to="/install/wolf-app">

A Frappe app (`dodock_wolf`). It stores events, metrics, rules and incidents as DocTypes,
evaluates alert rules at each scheduler tick and shows the timeline in the Wolf UI at `/wolf`
and in Desk.

</card>

<card icon="i-lucide-server" title="Wolf Agent" to="/install/wolf-agent">

A Python daemon on each host, using only the standard library (Python 3.9 or later). It tails
nginx, bench and auth logs, reads `/proc`, Redis, MariaDB and TLS certificates, and pushes
batches over HTTPS.

</card>
</card-group>

The site running the Wolf App also watches itself, with no agent: failed scheduled jobs, Error
Logs, failed logins, privileged role grants and risky changes such as new Server Scripts. Other
sites on a bench can forward the same signals as [satellites](/install/every-site).

## What it is for

<table>
<thead>
  <tr>
    <th>
      Signal
    </th>
    
    <th>
      Example
    </th>
    
    <th>
      Where it comes from
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      5xx and 502 spikes
    </td>
    
    <td>
      14 × 502 on <code>
        a.example.com
      </code>
      
       in 5 min, after a deployment at 01:47
    </td>
    
    <td>
      nginx access log (agent)
    </td>
  </tr>
  
  <tr>
    <td>
      Cron and scheduler failures
    </td>
    
    <td>
      The nightly job failed at 02:00, or the scheduler stalled
    </td>
    
    <td>
      <code>
        scheduler.log
      </code>
      
       (agent), Scheduled Job Log (site)
    </td>
  </tr>
  
  <tr>
    <td>
      Worker problems
    </td>
    
    <td>
      Worker OOM-killed, RQ queue backlog, no live worker
    </td>
    
    <td>
      <code>
        worker.log
      </code>
      
      , Redis (agent)
    </td>
  </tr>
  
  <tr>
    <td>
      Security
    </td>
    
    <td>
      SSH brute force, admin login from a new country, a web attack scan
    </td>
    
    <td>
      auth log, nginx (agent); login and audit hooks (site)
    </td>
  </tr>
  
  <tr>
    <td>
      Operations
    </td>
    
    <td>
      No backup for 26 h, TLS certificate expiring in 3 days, replication stopped
    </td>
    
    <td>
      backups, TLS, MariaDB (agent)
    </td>
  </tr>
</tbody>
</table>

Every signal becomes a **Wolf Event** or a **Wolf Metric Sample**. **Wolf Alert Rules** turn them
into **Wolf Incidents**, which notify your channels when they open, reopen and resolve. See
[Concepts](/getting-started/concepts).

## What it is not

Dodock Wolf is not a full Datadog replacement. It does no LLM observability, data observability,
real-user monitoring or SLO dashboards. It covers operational safety for Frappe (errors, cron,
workers, hosts) and the security signals around it, using open formats (JSON logs, syslog,
OCSF) and storage you own.

## Where it is going

Wolf's new work goes to the **security and compliance of the bench**: what happens inside Frappe
(permissions, scripts, exports, API keys, logins), on the host and in front of it (SSH, attacks
seen in nginx, file integrity, outbound connections), the response to it, and the evidence (signed
journal, NIS2, DORA and GDPR deadlines, SIEM export). No Frappe tool covers that, on Frappe Cloud
or elsewhere.

The general observability features (dashboards, service metrics) stay as they are:
kept working and translated, for operators who run their own benches, but without new features.
Version 0.2 removed the Press v1 integration, the live demos, status pages, the metrics explorer,
digests and the host resource metrics (CPU, memory, swap, disk, load); release v0.1.0 keeps them. Frappe Cloud has its own telemetry, incident manager and status
page (Datum and Beacon); where a tool already does the job, Wolf connects to it rather than doing
it again: Wazuh, Suricata, CrowdSec, a SIEM, PagerDuty, and Frappe's own tools as they open up.

### Staying on v0.1.0

To keep what 0.2 removed, Press v1 hosts among them, install the app and the agent from the
v0.1.0 tag:

```bash [bench]
bench get-app https://github.com/bthuner/dodock-wolf --branch v0.1.0
```

```bash [host]
curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/v0.1.0/agent/install.sh \
  | sudo WOLF_AGENT_REF=v0.1.0 WOLF_URL=https://wolf.example.com WOLF_TOKEN=<registration token> bash
```

A 0.2 agent on a host a v0.1 agent registered as a Press v1 server logs a warning at start, and
`wolf-agent doctor` fails with the same fix: Press v1 is supported by Dodock Wolf v0.1.0 only, so
reinstall the agent with `WOLF_AGENT_REF=v0.1.0`.

## Next

<card-group>
<card icon="i-lucide-timer" title="Quickstart" to="/getting-started/quickstart">

From nothing to a first alert, on one bench.

</card>

<card icon="i-lucide-shapes" title="Concepts" to="/getting-started/concepts">

Events, metrics, rules, incidents and scopes.

</card>
</card-group>
