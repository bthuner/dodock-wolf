# What is collected

> Every metric and event the Wolf Agent sends, and where it reads it.

Run `wolf-agent check` to see the exact payload on your host. Each check below can be turned off or
tuned in the [configuration](/agent/configuration).

## Host

From `/proc`, every push (`push_interval`, 30 s):

<table>
<thead>
  <tr>
    <th>
      Metric
    </th>
    
    <th>
      Notes
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
      percent
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        memory_used_percent
      </code>
      
      , <code>
        swap_used_percent
      </code>
    </td>
    
    <td>
      
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        load_1m
      </code>
      
      , <code>
        load_5m
      </code>
      
      , <code>
        load_15m
      </code>
      
      , <code>
        load_per_core
      </code>
    </td>
    
    <td>
      
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        disk_used_percent
      </code>
    </td>
    
    <td>
      per real mount, label <code>
        mount
      </code>
    </td>
  </tr>
</tbody>
</table>

## Bench logs

From `<bench>/logs/`, and the site-scoped `sites/<site>/logs/frappe.web.log` and `scheduler.log`:

<table>
<thead>
  <tr>
    <th>
      Log
    </th>
    
    <th>
      Becomes
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        frappe.web.log
      </code>
      
      , <code>
        web.error.log
      </code>
      
      , <code>
        bench.log
      </code>
    </td>
    
    <td>
      <code>
        error
      </code>
      
       events with the traceback
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        scheduler.log
      </code>
    </td>
    
    <td>
      <code>
        cron_failure
      </code>
      
       events for failed scheduled jobs
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        worker.log
      </code>
      
      , <code>
        worker.error.log
      </code>
    </td>
    
    <td>
      <code>
        worker_failure
      </code>
      
       events: worker crashes, OOM kills, failed jobs
    </td>
  </tr>
</tbody>
</table>

<note>

Frappe logs "Scheduled Job Failed" at INFO, which the default logger drops. To catch every failing
cron, also install the app on each site as a [satellite](/install/every-site).

</note>

## nginx access log

Per site and per minute of the log line's own time: `http_requests`, `http_5xx`, `http_502`, plus
one aggregated event per (site, status, route) and minute. Each sample is stamped with the newest
line of its minute, so a backlog read at once (after a restart or a rotation) lands in the minutes
it happened, not as one spike when the agent reads it. A known site with no traffic reports zeros.

The site comes from `$host` when the log format includes it (a leading vhost field or a trailing
quoted field), else from a per-site log file name, else the bench's only site.

The same lines feed [web attack detection](/security/detection): probes for secrets, admin panels,
traversal and injections become `web_attack_probe` events, and a secret-bearing file answered with
a 2xx becomes a critical `web_sensitive_file_exposed` event.

## Auth log

From `/var/log/auth.log`, `/var/log/secure`, or `journalctl` (`sshd`, `sshd-session`, `sudo`,
`useradd`, `usermod`, `gpasswd`):

<table>
<thead>
  <tr>
    <th>
      Signal
    </th>
    
    <th>
      Event
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      failed SSH logins, aggregated per source IP and minute of log time; root logins
    </td>
    
    <td>
      <code>
        security
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      a successful login from an address that failed 5+ times in the hour before
    </td>
    
    <td>
      <code>
        ssh_login_after_failures
      </code>
      
       (critical)
    </td>
  </tr>
  
  <tr>
    <td>
      failed sudo attempts, users outside sudoers
    </td>
    
    <td>
      <code>
        sudo_failure
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      new local accounts
    </td>
    
    <td>
      <code>
        account_created
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      a user added to <code>
        sudo
      </code>
      
      , <code>
        wheel
      </code>
      
      , <code>
        admin
      </code>
      
      , <code>
        root
      </code>
      
      , <code>
        adm
      </code>
      
      , <code>
        docker
      </code>
      
       or <code>
        lxd
      </code>
    </td>
    
    <td>
      <code>
        admin_group_change
      </code>
      
       (critical)
    </td>
  </tr>
</tbody>
</table>

## Redis and RQ

From the bench's queue Redis (`redis_queue`):

<table>
<thead>
  <tr>
    <th>
      Metric
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
        queue_length
      </code>
    </td>
    
    <td>
      length of every <code>
        rq:queue:*
      </code>
      
       list
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_failed_jobs
      </code>
      
      , <code>
        rq_failed_jobs_added
      </code>
    </td>
    
    <td>
      failed-job registry size, and its increase per push
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_long_running_jobs
      </code>
    </td>
    
    <td>
      started jobs older than <code>
        rq.long_job_minutes
      </code>
      
       (30)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        rq_workers
      </code>
    </td>
    
    <td>
      live workers
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        redis_used_memory_percent
      </code>
      
      , <code>
        redis_evicted_keys
      </code>
    </td>
    
    <td>
      from <code>
        INFO
      </code>
    </td>
  </tr>
</tbody>
</table>

Only the queue Redis is watched. The cache Redis is an LRU cache by design (`allkeys-lru`), so a
full cache and evictions are normal there.

## Backups

`backup_age_hours` per site, from the newest `sites/<site>/private/backups/*-database.sql*`, every
10 minutes. A site that never had a backup sends nothing, so *No backup for 26 h* cannot fire for it.
Press benches are skipped, since Press uploads backups offsite. Offsite-only setups can point
`backups.dirs` at a mounted directory per site.

## TLS certificates

`tls_days_left` for every public site name and custom domain (`site_config.json` `domains`), every
hour, in a background thread. The agent connects to `<domain>:443` with SNI and reads the leaf
certificate without verifying it, so expired and self-signed certificates are measured too.

Skipped: `localhost`, `*.localhost`, `.local`, `.test`, bare names, IP addresses and the `example.*`
names. Unreachable domains are logged and skipped.

## MariaDB

Through the `mariadb` (or `mysql`) client, with a site's own credentials written to a private
temporary option file, never on the command line:

<table>
<thead>
  <tr>
    <th>
      Metric
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
        db_threads_connected
      </code>
      
      , <code>
        db_connections_used_percent
      </code>
    </td>
    
    <td>
      against <code>
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
      increase per push
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        db_replication_lag_seconds
      </code>
      
      , <code>
        db_replication_running
      </code>
    </td>
    
    <td>
      on a replica
    </td>
  </tr>
</tbody>
</table>

A site user may not read replica status (REPLICATION CLIENT / SLAVE MONITOR). Then replication is
skipped, unless `mariadb.user` / `password` or `mariadb.defaults_file` names a monitoring user.
Without a client on the host, or for Postgres benches, nothing is sent.

## Processes

From `supervisorctl status`, else `systemctl list-units` for units whose name contains the bench name.
`bench_processes_down` per bench counts processes that are STOPPED, EXITED, BACKOFF, FATAL or
UNKNOWN (systemd: `failed` or a restart loop). A process entering FATAL / UNKNOWN (systemd `failed`)
also sends one `worker_failure` / `process_down` event. Press benches run processes in containers
and are skipped.

## Security posture

<table>
<thead>
  <tr>
    <th>
      Check
    </th>
    
    <th>
      Every
    </th>
    
    <th>
      Sends
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        App versions
      </strong>
    </td>
    
    <td>
      1 h
    </td>
    
    <td>
      <code>
        app_version
      </code>
      
       per bench and app, from <code>
        apps/<app>/<app>/__init__.py
      </code>
      
      . The Wolf site compares them with the GitHub Security Advisories of Frappe and ERPNext. Development versions are not sent.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Site settings
      </strong>
    </td>
    
    <td>
      1 h
    </td>
    
    <td>
      <code>
        site_setting
      </code>
      
       per site: two-factor authentication, password policy and minimum score, lockout, guest uploads, and the System Manager role's two-factor flag. Feeds the <a href="/security/compliance">
        security score
      </a>
      
       of sites other than the Wolf site.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Exposure
      </strong>
    </td>
    
    <td>
      10 min
    </td>
    
    <td>
      <code>
        exposed_services
      </code>
      
       per host: bench ports listening beyond loopback (MariaDB 3306, Postgres 5432, Redis, socket.io 9000, gunicorn). <code>
        site_config_risks
      </code>
      
       per site: <code>
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
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        File integrity
      </strong>
    </td>
    
    <td>
      15 min
    </td>
    
    <td>
      <code>
        integrity_files
      </code>
      
       per bench; <code>
        bench_code_changed
      </code>
      
       and <code>
        bench_config_changed
      </code>
      
       events when an app's code, a site config or the nginx and supervisor config changes, telling a deployment from a change outside one. See <a href="/security/detection#file-integrity">
        Detection
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Outbound connections
      </strong>
    </td>
    
    <td>
      1 min
    </td>
    
    <td>
      <code>
        bench_outbound_destinations
      </code>
      
       per bench; a <code>
        bench_new_outbound
      </code>
      
       event for each public network and unusual port a bench's user had never used, after a 7-day learning period; <code>
        bench_new_outbound_usual
      </code>
      
       counts new ones on usual ports. See <a href="/security/detection#outbound-connections">
        Detection
      </a>
      
      .
    </td>
  </tr>
</tbody>
</table>

See [Detection](/security/detection).

## Optional sources

When present on the host, the agent also tails:

- **Suricata**'s EVE log (`/var/log/suricata/eve.json`): `network_ids_alert` events;
- **Wazuh**'s `alerts.json` on the manager: `hids_alert` events.

See [Wazuh and Suricata](/security/wazuh-suricata).

## Delivery guarantees

- Logs are read from the end on first start. Offsets are kept in
`/var/lib/wolf-agent/spool/tail-state.json`, so restarts and log rotation lose nothing.
- Failed pushes are spooled to `/var/lib/wolf-agent/spool/outbox/` (capped at 50 MB) and replayed in
order with exponential backoff.
- Events are [scrubbed](/agent/scrubbing) of e-mail addresses, credentials, card numbers and IBANs
before they are spooled.
