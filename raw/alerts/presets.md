# Preset rules

> The rules installed with the app, what each one watches, and when it fires.

Presets are created on install and on each migrate. Edit or disable them freely: they are never
overwritten. They are flagged **Dokos preset** on the rule. Read each condition as the rule's
aggregation over its window, checked every minute.

<warning>

Presets have no channels. They open incidents but notify nobody until you add a
[channel](/alerts/channels).

</warning>

## Web and deployments

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      502 spike after deployment
    </td>
    
    <td>
      <code>
        sum(http_502)
      </code>
      
       >= 10 in 5 min, after a deployment
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      5xx spike
    </td>
    
    <td>
      <code>
        sum(http_5xx)
      </code>
      
       >= 25 in 5 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
</tbody>
</table>

## Cron, scheduler and workers

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Nightly cron failure (01:00-04:00)
    </td>
    
    <td>
      <code>
        cron_failure
      </code>
      
       events >= 1 in 15 min, 01:00–04:00
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Scheduler failure
    </td>
    
    <td>
      <code>
        cron_failure
      </code>
      
       events >= 1 in 15 min, 04:00–01:00
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Scheduler stalled
    </td>
    
    <td>
      <code>
        host_metric_alert
      </code>
      
       / <code>
        scheduler_stalled
      </code>
      
       events >= 1 in 15 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Worker crash
    </td>
    
    <td>
      <code>
        worker_failure
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        bench
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Worker queue backlog
    </td>
    
    <td>
      <code>
        min(queue_length)
      </code>
      
       > 500 in 10 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Background jobs failing
    </td>
    
    <td>
      <code>
        sum(rq_failed_jobs_added)
      </code>
      
       >= 5 in 10 min
    </td>
    
    <td>
      <code>
        bench
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Long-running background job
    </td>
    
    <td>
      <code>
        min(rq_long_running_jobs)
      </code>
      
       > 0 in 15 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      No background workers
    </td>
    
    <td>
      <code>
        max(rq_workers)
      </code>
      
       < 1 in 5 min
    </td>
    
    <td>
      <code>
        bench
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Queue Redis memory high
    </td>
    
    <td>
      <code>
        min(redis_used_memory_percent)
      </code>
      
       > 90 in 10 min
    </td>
    
    <td>
      <code>
        bench
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Queue Redis evicting keys
    </td>
    
    <td>
      <code>
        sum(redis_evicted_keys)
      </code>
      
       >= 1 in 10 min
    </td>
    
    <td>
      <code>
        bench
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Bench process down
    </td>
    
    <td>
      <code>
        min(bench_processes_down)
      </code>
      
       > 0 in 3 min
    </td>
    
    <td>
      <code>
        bench
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
</tbody>
</table>

## Hosts and agents

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Disk almost full
    </td>
    
    <td>
      <code>
        min(disk_used_percent)
      </code>
      
       > 90 in 5 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      High CPU
    </td>
    
    <td>
      <code>
        min(cpu_usage)
      </code>
      
       > 90 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      High memory
    </td>
    
    <td>
      <code>
        min(memory_used_percent)
      </code>
      
       > 90 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      High load
    </td>
    
    <td>
      <code>
        avg(load_per_core)
      </code>
      
       > 2 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Agent silent
    </td>
    
    <td>
      <code>
        host_metric_alert
      </code>
      
       / <code>
        agent_silent
      </code>
      
       events >= 1 in 15 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
</tbody>
</table>

## Backups, TLS, database and email

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      No backup for 26 h
    </td>
    
    <td>
      <code>
        last(backup_age_hours)
      </code>
      
       > 26 in 60 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Backup failed
    </td>
    
    <td>
      <code>
        error
      </code>
      
       / <code>
        backup_failed
      </code>
      
       events >= 1 in 60 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      TLS certificate expiring within 14 days
    </td>
    
    <td>
      <code>
        last(tls_days_left)
      </code>
      
       < 14 in 180 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      TLS certificate expiring within 3 days
    </td>
    
    <td>
      <code>
        last(tls_days_left)
      </code>
      
       < 3 in 180 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Database connections high
    </td>
    
    <td>
      <code>
        min(db_connections_used_percent)
      </code>
      
       > 85 in 5 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Slow queries
    </td>
    
    <td>
      <code>
        sum(db_slow_queries)
      </code>
      
       >= 20 in 10 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Replication lag
    </td>
    
    <td>
      <code>
        min(db_replication_lag_seconds)
      </code>
      
       > 300 in 10 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Replication stopped
    </td>
    
    <td>
      <code>
        max(db_replication_running)
      </code>
      
       < 1 in 5 min
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Email queue backlog
    </td>
    
    <td>
      <code>
        error
      </code>
      
       / <code>
        email_queue_backlog
      </code>
      
       events >= 1 in 15 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Email sending errors
    </td>
    
    <td>
      <code>
        error
      </code>
      
       / <code>
        email_queue_error
      </code>
      
       events >= 1 in 15 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
</tbody>
</table>

## Logins and accounts

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      SSH brute force
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        ssh_failed_login
      </code>
      
       events >= 20 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      SSH login after brute force
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        ssh_login_after_failures
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Repeated sudo failures
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        sudo_failure
      </code>
      
       events >= 3 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      New system account
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        account_created
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      User added to admin group
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        admin_group_change
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Repeated failed Frappe logins
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        frappe_failed_login
      </code>
      
       events >= 5 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Admin login from new IP
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        new_admin_ip
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Admin login from new country
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        admin_login_new_country
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Privileged role granted
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        privileged_user
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
</tbody>
</table>

## Attacks and intrusion

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Web attack scan
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        web_attack_probe
      </code>
      
       events >= 100 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Sensitive file served
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        web_sensitive_file_exposed
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Network IDS alert (critical)
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        network_ids_alert
      </code>
      
       events (critical) >= 1 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Host intrusion alert (critical)
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        hids_alert
      </code>
      
       events (critical) >= 1 in 10 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Honeytoken touched
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        honeytoken_triggered
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Bench service exposed
    </td>
    
    <td>
      <code>
        last(exposed_services)
      </code>
      
       > 0 in 30 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Development settings in production
    </td>
    
    <td>
      <code>
        last(site_config_risks)
      </code>
      
       > 0 in 30 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
</tbody>
</table>

## Application changes and posture

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Server Script can run new code
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        server_script_change
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Client Script can run new code
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        client_script_change
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      System Console used
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        console_execution
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Security settings weakened
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        security_settings_weakened
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      Permission rules changed
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        permission_change
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      API key generated
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        api_key_generated
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      API key used from a new IP
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        api_key_new_ip
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Webhook to a new host
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        webhook_external
      </code>
      
       events >= 1 in 10 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Unusual data export
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        data_exfiltration
      </code>
      
       events >= 1 in 60 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Security score low
    </td>
    
    <td>
      <code>
        last(security_score)
      </code>
      
       < 60 in 180 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ◐ warning
    </td>
  </tr>
  
  <tr>
    <td>
      Regulatory deadline
    </td>
    
    <td>
      <code>
        security
      </code>
      
       / <code>
        regulatory_deadline
      </code>
      
       events >= 1 in 15 min
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
</tbody>
</table>

## Sequences across sources

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
    
    <th>
      Per
    </th>
    
    <th>
      Severity
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Scan then login from the same IP
    </td>
    
    <td>
      one of <code>
        web_attack_probe
      </code>
      
      , <code>
        network_ids_alert
      </code>
      
      , then one of <code>
        ssh_login_after_failures
      </code>
      
      , <code>
        ssh_root_login
      </code>
      
      , <code>
        new_admin_ip
      </code>
      
      , <code>
        admin_login_new_country
      </code>
      
      , <code>
        api_key_new_ip
      </code>
      
       on the same <code>
        ip
      </code>
      
       within 60 min
    </td>
    
    <td>
      <code>
        ip
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      New-IP login then export or new key
    </td>
    
    <td>
      one of <code>
        new_admin_ip
      </code>
      
      , <code>
        admin_login_new_country
      </code>
      
      , <code>
        api_key_new_ip
      </code>
      
      , then one of <code>
        data_exfiltration
      </code>
      
      , <code>
        api_key_generated
      </code>
      
      , <code>
        webhook_external
      </code>
      
       on the same <code>
        user
      </code>
      
       within 120 min
    </td>
    
    <td>
      <code>
        user
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
  
  <tr>
    <td>
      IDS alert then risky change on the host
    </td>
    
    <td>
      one of <code>
        network_ids_alert
      </code>
      
      , <code>
        hids_alert
      </code>
      
       (critical), then one of <code>
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
        privileged_user
      </code>
      
      , <code>
        api_key_generated
      </code>
      
      , <code>
        webhook_external
      </code>
      
       on the same <code>
        host
      </code>
      
       within 60 min
    </td>
    
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      ● critical
    </td>
  </tr>
</tbody>
</table>

**Per** is the rule's **Group By**: one incident per site, bench, host or `host_label` (a disk mount,
a queue, a domain). For a [sequence rule](/alerts/rules#sequence-rules) it is the entity: one incident
per IP, user or host. The conditions are those of a fresh install, generated from
[`dodock_wolf/wolf/presets.py`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/presets.py)
by `docs-site/scripts/presets-table.py`. See [Security](/security) for the signals behind the
security presets.
