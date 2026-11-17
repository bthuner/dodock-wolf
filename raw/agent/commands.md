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
        demo press [--root DIR] [--days N] [--no-live] [--cycle MIN] [--configure]
      </code>
    </td>
    
    <td>
      Write a simulated Press app server for this agent to read: days of history, then live traffic and incidents. For demos and tests only.
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

`demo press` lays out a Press app server under `--root` (default `/home/frappe/demo-press`):
3 benches, 8 sites with two custom domains, the Press agent's `jobs.sqlite3`, an nginx access log in
Press's format and an auth.log. Sites are names only: nothing runs behind them. Use a host or
container of its own, registered under a name of its own.

```bash [demo host]
wolf-agent register --url https://wolf.example.com --token TOKEN --hostname f1-demo-press --platform press
wolf-agent demo press --configure   # Press mode on the demo layout; checks with nothing behind them off
wolf-agent run &                    # the agent runs first: it must open the files while they are empty
wolf-agent demo press               # 7 days of history, then an incident cycle every 30 minutes
```

It waits until the agent tracks every file, then writes the history, which reaches Wolf through the
agent's own discovery, tailers and parsers. Past host metrics, which the agent samples live, go
through its spool. Each cycle has a Press migrate followed by 4 minutes of 502s, a request
traceback, a failed scheduled job, a killed worker, an SSH brute force (every third one succeeds),
a web attack scan and, every other cycle, a failed Patch App job.

Rules look at the last minutes, so incidents open for the live cycles, not for the history.
`bench --site SITE generate-demo-press --agent-config PATH` does the same from a bench that has
the agent installed, and `--webhook URL` also sends the demo's alerts there. The
[development page](/reference/development) runs it all in Docker.

## See the payload

```bash [host]
sudo -u wolf-agent wolf-agent check --from-start | jq '.events[] | {type, category, title}'
```

`--from-start` reads the logs from the beginning instead of the saved offsets, which is useful to
test a parser on an existing file. `check` never sends anything and never moves the offsets.
