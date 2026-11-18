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
        refresh
      </code>
    </td>
    
    <td>
      As root: read again what the agent's user cannot (a Press server's benches folder and proxy; a Press proxy's access log) and save it in the config, without registering again. <code>
        install.sh
      </code>
      
       runs it on every upgrade.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        discover [--bench PATH] [--platform auto|press|generic]
      </code>
    </td>
    
    <td>
      Show what bench discovery finds.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        check [--from-start] [--status] [--platform …]
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
      Check what this host gives the agent and what to fix: registration and the Wolf site, each log, bench, queue Redis and nginx log, the Press job database or Pilot export, the auth log or journal, response actions, the daemon. Read-only. Exits 1 when a check fails. See <a href="#check-a-host">
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
  
  <tr>
    <td>
      <code>
        demo press|multi|single [--root DIR] [--days N] [--no-live] [--cycle MIN] [--configure]
      </code>
    </td>
    
    <td>
      Write a simulated server for this agent to read: days of history, then live traffic and incidents. For demos and tests only.
    </td>
  </tr>
</tbody>
</table>

## Mark a deployment

```bash [deploy.sh]
sudo -u wolf-agent wolf-agent mark-deployment --bench frappe-bench --site erp.example.com \
  --note "ERPNext v15.42 + custom app 2.3" --silence 15m
```

The marker is a `deployment` event. Rules with **Require recent deployment** only fire after one,
and incidents link to the latest deployment of their scope. Text passed with `--note` is sent as is,
without [scrubbing](/agent/scrubbing).

Press and Pilot tasks, and `bench migrate` on sites running the Wolf App, are marked by themselves.

## Run a demo

`demo KIND` lays out a simulated server under `--root` (default `/home/frappe/demo-KIND`). Sites are
names only: nothing runs behind them.

<table>
<thead>
  <tr>
    <th>
      Kind
    </th>
    
    <th>
      Server
    </th>
    
    <th>
      Deployments
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        press
      </code>
    </td>
    
    <td>
      a Press app server: 3 benches, 8 sites (two with a custom domain), the Press agent's <code>
        jobs.sqlite3
      </code>
      
      , nginx in Press's format
    </td>
    
    <td>
      Press jobs, read by the agent
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        multi
      </code>
    </td>
    
    <td>
      plain benches: 2 benches, 6 sites (two with a custom domain), one nginx log with <code>
        $host
      </code>
      
       first
    </td>
    
    <td>
      marked through the deployment endpoint, as <code>
        mark-deployment
      </code>
      
       does
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        single
      </code>
    </td>
    
    <td>
      one bench, one site
    </td>
    
    <td>
      same as <code>
        multi
      </code>
    </td>
  </tr>
</tbody>
</table>

Every kind has an auth.log too. Use a host or container of its own, registered under a name of its own:

```bash [demo host]
wolf-agent register --url https://wolf.example.com --token TOKEN --hostname dokos-multi-1 --bench /home/frappe/demo-multi
wolf-agent demo multi --configure   # points the agent at the demo; checks with nothing behind them off
wolf-agent run &                    # the agent runs first: it must open the files while they are empty
wolf-agent demo multi               # 7 days of history, then an incident cycle every 30 minutes
```

`--bench` names a directory that is not a bench yet, so the host registers without benches; the
demo's benches reach Wolf with its telemetry. For `press`, also pass `--platform press`.

The demo waits until the agent tracks every file, then writes the history, which reaches Wolf
through the agent's own discovery, tailers and parsers. Past host metrics, which the agent samples
live, go through its spool. Each cycle has a deployment followed by 4 minutes of 502s, a request
traceback, a failed scheduled job, a killed worker, an SSH brute force (every third one succeeds),
a web attack scan and, every other cycle, a failed bench operation (a Press Patch App job, or a
`bench update` traceback).

Rules look at the last minutes, so incidents open for the live cycles, not for the history.
`bench --site SITE generate-demo-press` (or `-multi`, `-single`) with `--agent-config PATH` does the
same from a bench that has the agent installed, and `--webhook URL` also sends the demo's alerts
there. The [development page](/reference/development) runs it all in Docker.

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
 FAIL  Press: /home/frappe/agent/jobs.sqlite3-wal is not the Press agent's: its jobs fail to write
        fix: stop the Press agent (supervisorctl stop 'agent:'), delete ...-wal and -shm, start it
```

It checks the files the daemon would tail and the benches it works from (on Press, the ones it rediscovers), not only the config. `--json` prints the checks as a list, `--offline` skips the call to the Wolf site. Nothing is written, and it exits 1 when a check fails, so it can gate an install script.

## See the payload

```bash [host]
sudo -u wolf-agent wolf-agent check --from-start | jq '.events[] | {type, category, title}'
```

`--from-start` reads the logs from the beginning instead of the saved offsets, which is useful to
test a parser on an existing file. `check` never sends anything and never moves the offsets.
