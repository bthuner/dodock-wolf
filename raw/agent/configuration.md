# Configuration

> The agent's config.json, key by key.

`wolf-agent register` writes `/etc/wolf-agent/config.json` (mode 0600, owned by `wolf-agent`).
Edit it to add logs or override discovery, then restart the service:

```bash [host]
sudo systemctl restart wolf-agent
sudo -u wolf-agent wolf-agent check   # runs every check once, TLS included
```

Use another file with `--config PATH` or `$WOLF_AGENT_CONFIG`.

## Full example

```json [/etc/wolf-agent/config.json]
{
  "url": "https://wolf.example.com",
  "agent_id": "WAG-0001",
  "agent_secret": "…",
  "hostname": "bench-01",
  "push_interval": 30,
  "spool_dir": "/var/lib/wolf-agent/spool",
  "verify_tls": true,
  "auth_log": null,
  "collect_host_metrics": true,
  "platform": null,
  "press": {"agent_dir": "/home/frappe/agent", "nginx_access_log": "/var/log/nginx/access.log",
            "rediscover_interval": 60, "deployments": true},
  "pilot": {"deployments": true, "api_url": null, "token": null, "jwt_secret": null},
  "benches": [
    {"name": "frappe-bench", "path": "/home/frappe/frappe-bench", "sites": ["a.example.com"],
     "logs_dir": "/home/frappe/frappe-bench/logs", "nginx_access_log": "/var/log/nginx/access.log",
     "redis_queue": "redis://127.0.0.1:11000"}
  ],
  "extra_logs": [{"path": "/var/log/myapp/error.log", "parser": "traceback", "bench": null, "site": null}],
  "rq": {"long_job_minutes": 30},
  "backups": {"enabled": true, "interval": 600, "press": false, "dirs": {}},
  "tls": {"enabled": true, "interval": 3600, "port": 443, "timeout": 5, "connect_host": null,
          "domains": ["status.example.com"], "exclude": []},
  "mariadb": {"enabled": true, "cli": null, "host": null, "port": null, "user": null,
              "password": null, "defaults_file": null},
  "processes": {"enabled": true, "manager": "auto"},
  "versions": {"enabled": true, "interval": 3600},
  "site_settings": {"enabled": true, "interval": 3600},
  "suricata": {"enabled": true, "eve_log": null, "max_priority": 3},
  "wazuh": {"enabled": true, "alerts_log": null, "min_level": 7, "exclude_groups": ["sca"]},
  "scrub": {"enabled": true, "ips": false, "extra_patterns": [], "keep": []},
  "watchdog": {
    "enabled": true,
    "stale_minutes": 5,
    "webhook_url": "https://chat.example.com/hooks/xxxx",
    "smtp": {"host": "smtp.example.com", "port": 587, "starttls": true, "from": "wolf@example.com",
             "to": ["ops@example.com"], "user": "wolf", "password": "…"}
  }
}
```

## Connection

<field-group>
<field name="url" type="string">

The central Wolf site.

</field>

<field name="agent_id / agent_secret" type="string">

Written by `register`. The site keeps only a hash of the secret: to replace a lost one, use
**Rotate secret** on the Wolf Agent form.

</field>

<field name="push_interval" type="number">

Seconds between pushes. Default `30`.

</field>

<field name="verify_tls" type="boolean">

Verify the Wolf site's certificate. Default `true`.

</field>

<field name="spool_dir" type="string">

Tail offsets, the outbox of failed pushes (50 MB cap) and the watchdog state.

</field>
</field-group>

## Sources

<field-group>
<field name="platform" type="null | "press" | "generic"">

`null` auto-detects [Press](/install/press), `"press"` forces it, `"generic"` disables it.

</field>

<field name="benches" type="array">

Name, path, sites, `logs_dir`, `nginx_access_log` (a path or a list) and `redis_queue` per bench.
Filled by discovery; edit to override.

</field>

<field name="auth_log" type="null | string | "journal" | false">

`null` auto-detects, a path forces a file, `"journal"` forces journalctl, `false` disables.

</field>

<field name="collect_host_metrics" type="boolean">

CPU, memory, swap, load and disk. Default `true`.

</field>

<field name="extra_logs" type="array">

More files to tail: `path`, `parser` (`traceback`, `scheduler`, `worker`, `nginx`, `auth`), and
optional `bench` and `site`.

</field>

<field name="pilot" type="object">

`deployments`, `api_url`, `token`, `jwt_secret`. See [Pilot benches](/install/pilot).

</field>

<field name="press" type="object">

`agent_dir`, `nginx_access_log`, `rediscover_interval` (s), `deployments`. See
[Press servers](/install/press).

</field>
</field-group>

## Checks

Every key is optional; the defaults are those of the example. `"tls": false` (and the same for the
others) turns a check off.

<table>
<thead>
  <tr>
    <th>
      Key
    </th>
    
    <th>
      Settings
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        rq
      </code>
    </td>
    
    <td>
      <code>
        long_job_minutes
      </code>
      
       (30)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        backups
      </code>
    </td>
    
    <td>
      <code>
        enabled
      </code>
      
      , <code>
        interval
      </code>
      
       (600 s), <code>
        press
      </code>
      
       (skip Press benches), <code>
        dirs
      </code>
      
       (backup directory per site)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        tls
      </code>
    </td>
    
    <td>
      <code>
        interval
      </code>
      
       (3600 s), <code>
        port
      </code>
      
       (443), <code>
        timeout
      </code>
      
       (5 s), <code>
        connect_host
      </code>
      
       (for example <code>
        127.0.0.1
      </code>
      
       to check the local nginx), <code>
        domains
      </code>
      
       (add), <code>
        exclude
      </code>
      
       (drop)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        mariadb
      </code>
    </td>
    
    <td>
      <code>
        cli
      </code>
      
       (else <code>
        mariadb
      </code>
      
       / <code>
        mysql
      </code>
      
      ), <code>
        host
      </code>
      
      , <code>
        port
      </code>
      
      , <code>
        user
      </code>
      
      , <code>
        password
      </code>
      
      , <code>
        defaults_file
      </code>
      
      : a monitoring user for replication status
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        processes
      </code>
    </td>
    
    <td>
      <code>
        manager
      </code>
      
      : <code>
        auto
      </code>
      
      , <code>
        supervisor
      </code>
      
       or <code>
        systemd
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        versions
      </code>
    </td>
    
    <td>
      <code>
        interval
      </code>
      
       (3600 s)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        site_settings
      </code>
    </td>
    
    <td>
      <code>
        interval
      </code>
      
       (3600 s)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        exposure
      </code>
    </td>
    
    <td>
      <code>
        interval
      </code>
      
       (600 s), <code>
        ports
      </code>
      
       (more ports to count)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        integrity
      </code>
    </td>
    
    <td>
      <code>
        interval
      </code>
      
       (900 s), <code>
        full_scan_interval
      </code>
      
       (86400 s), <code>
        server_paths
      </code>
      
       (<code>
        null
      </code>
      
      : <code>
        /etc/nginx
      </code>
      
       and <code>
        /etc/supervisor
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        outbound
      </code>
    </td>
    
    <td>
      <code>
        interval
      </code>
      
       (60 s), <code>
        learn_days
      </code>
      
       (7), <code>
        include_private
      </code>
      
       (<code>
        false
      </code>
      
      ), <code>
        usual_ports
      </code>
      
       (ports only counted, added to the defaults), <code>
        report_usual_ports
      </code>
      
       (<code>
        false
      </code>
      
      ), <code>
        proxy_logs
      </code>
      
       (<code>
        null
      </code>
      
      : <code>
        /var/log/squid/access.log
      </code>
      
       when it exists; or <code>
        [{"path", "format": "squid"}]
      </code>
      
      ), <code>
        kernel_log
      </code>
      
       (<code>
        "auto"
      </code>
      
      : every new connection when <code>
        wolf-outbound-log
      </code>
      
       is installed; <code>
        false
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        suricata
      </code>
    </td>
    
    <td>
      <code>
        eve_log
      </code>
      
      , <code>
        max_priority
      </code>
      
       (3)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        wazuh
      </code>
    </td>
    
    <td>
      <code>
        alerts_log
      </code>
      
      , <code>
        min_level
      </code>
      
       (7), <code>
        exclude_groups
      </code>
      
       (<code>
        ["sca"]
      </code>
      
      )
    </td>
  </tr>
</tbody>
</table>

## Privacy and safety

<table>
<thead>
  <tr>
    <th>
      Key
    </th>
    
    <th>
      Page
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        scrub
      </code>
    </td>
    
    <td>
      <a href="/agent/scrubbing">
        Scrubbing
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        watchdog
      </code>
    </td>
    
    <td>
      <a href="/agent/watchdog">
        Watchdog
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        response
      </code>
    </td>
    
    <td>
      <a href="/agent/response-actions">
        Response actions
      </a>
    </td>
  </tr>
</tbody>
</table>
