# Commands

> The wolf-agent command line.

Run commands as the `wolf-agent` user, which owns the config:
`sudo -u wolf-agent wolf-agent <command>`.

Global options: `--config PATH` (or `$WOLF_AGENT_CONFIG`), `-v`.

<table>
<thead>
  <tr>
    <th>
      Command
    </th>
    
    <th>
      What it does
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        register --url URL --token TOKEN [--bench PATH]...
      </code>
    </td>
    
    <td>
      Register the host, discover benches, write the config.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        run
      </code>
    </td>
    
    <td>
      The daemon loop. This is what systemd runs.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        discover [--bench PATH]
      </code>
    </td>
    
    <td>
      Show what bench discovery finds.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        check [--from-start] [--status] [--bench PATH]
      </code>
    </td>
    
    <td>
      Collect once and print the JSON payload. Nothing is sent. The watchdog state goes to stderr. <code>
        --status
      </code>
      
       also asks the site for its health.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        doctor [--json] [--offline]
      </code>
    </td>
    
    <td>
      Check what this host gives the agent and what to fix: registration and the Wolf site, each log, bench, queue Redis and nginx log, the Pilot export, the auth log or journal, response actions, the daemon. Read-only. Exits 1 when a check fails. See <a href="#check-a-host">
        Check a host
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        mark-deployment --bench NAME [--site S] [--note TEXT] [--silence 15m]
      </code>
    </td>
    
    <td>
      Put a deployment marker on the Wolf timeline. <code>
        --silence
      </code>
      
       also opens a maintenance window that mutes notifications for that bench or site.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        test-fallback
      </code>
    </td>
    
    <td>
      Send a test message through the <a href="/agent/watchdog">
        watchdog
      </a>
      
       fallback channels.
    </td>
  </tr>
</tbody>
</table>

### Deprecated

Press v1 support and the host resource metrics were removed in 0.2. Their options are still
accepted, so old scripts, units and configs keep working: each prints `removed in 0.2: ignored`
to stderr and does nothing.

<table>
<thead>
  <tr>
    <th>
      Option or command
    </th>
    
    <th>
      Since 0.2
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        --platform
      </code>
      
       on <code>
        register
      </code>
      
      , <code>
        discover
      </code>
      
       and <code>
        check
      </code>
    </td>
    
    <td>
      Ignored: benches are discovered as usual.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        mark-deployment --source press
      </code>
    </td>
    
    <td>
      Recorded as <code>
        manual
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        refresh
      </code>
    </td>
    
    <td>
      Does nothing and exits 0.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        collect_host_metrics
      </code>
      
       in the config
    </td>
    
    <td>
      Ignored: the agent no longer measures host resources. <code>
        run
      </code>
      
       logs the warning, <code>
        check
      </code>
      
       prints it to stderr, <code>
        doctor
      </code>
      
       lists it, <code>
        register
      </code>
      
       drops the key.
    </td>
  </tr>
</tbody>
</table>

A host still on Press v1 stays on [v0.1.0](/getting-started#staying-on-v010).

## Mark a deployment

```bash [deploy.sh]
sudo -u wolf-agent wolf-agent mark-deployment --bench frappe-bench --site erp.example.com \
  --note "ERPNext v15.42 + custom app 2.3" --silence 15m
```

The marker is a `deployment` event. Rules with **Require recent deployment** only fire after one,
and incidents link to the latest deployment of their scope. Text passed with `--note` is sent as is,
without [scrubbing](/agent/scrubbing).

Pilot tasks, and `bench migrate` on sites running the Wolf App, are marked by themselves.

## Check a host

```bash [host]
sudo -u wolf-agent wolf-agent doctor
```

Run it as the agent's user: root can read what the daemon cannot, and would hide problems. Each line is **ok**, **WARN**, **FAIL** or `--` (for information), with the fix after a warning or a failure:

```text
logs
  ok   18 log file(s) readable
  --   9 not written yet (read once they appear): bench-1/frappe.web.log ...

platform
 FAIL  Pilot wolf: cannot read /var/lib/wolf-pilot-export/wolf.json
        fix: systemctl restart wolf-pilot-export.service (it sets the wolf-agent group)
```

It checks the files the daemon would tail and the benches it works from, not only the config. `--json` prints the checks as a list, `--offline` skips the call to the Wolf site. Nothing is written, and it exits 1 when a check fails, so it can gate an install script.

The daemon runs the same checks every hour (`setup_checks`) and sends them with a push: the Wolf UI's **Monitoring** page shows each host's setup, its problems and their fixes, and the *Host setup problem* preset opens an incident while a check fails.

## See the payload

```bash [host]
sudo -u wolf-agent wolf-agent check --from-start | jq '.events[] | {type, category, title}'
```

`--from-start` reads the logs from the beginning instead of the saved offsets, which is useful to
test a parser on an existing file. `check` never sends anything and never moves the offsets.
