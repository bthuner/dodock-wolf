# Pilot benches

> Run the Wolf Agent on a Frappe Pilot host and turn Pilot tasks into deployment events.

[Pilot](https://github.com/frappe/pilot) is **Frappe's** server manager ("Frappe Server Manager"). It is not a Dokos tool: Dokos' public GitLab group has no Pilot repository. The Dokos documentation mentions Pilot only through the `pilot_endpoint` / `pilot_auth_token` site keys used by the Cloud Settings panel for Frappe Cloud v2 sites. These are the same keys Pilot writes into `site_config.json`.

Everything on this page was checked on a live Pilot host: **Pilot v1.0.0-rc.1**, and again on **v1.0.0-rc.2** (which changes only Pilot's release CI), in production mode (systemd user units, nginx, the Admin), a Frappe 16 bench and a site running the Wolf App. The repository's [`dev/pilot`](https://github.com/bthuner/dodock-wolf/tree/main/dev/pilot) sets the same host up in a container.

## Install

Install the agent as on any host ([Wolf Agent](/install/wolf-agent)). It runs as its own `wolf-agent` user, out of the bench's reach: code that takes over a Frappe site cannot read its config, its integrity key or its state, nor stop it.

Pilot keeps a bench's `bench.toml`, its `tasks/` and its site configs readable by the bench user only, and runs the bench as that user's systemd user units, which another user cannot list. So on a Pilot host the installer also sets up **wolf-pilot-export**, a root helper run by `wolf-pilot-export.timer` every 20 seconds. It writes `/var/lib/wolf-pilot-export/<bench>.json` (`root:wolf-agent`, mode `0640`, in a folder root owns) with:

- the latest 100 tasks: command, status, times, exit code, failure code and message, and of the arguments only the site;
- the state of the bench's `<bench>-*.service` user units.

It reads the bench's files as the bench user, in a child process with a time limit: a link that user plants there gives access to nothing more than they could already read. It takes a bench only when its `[bench] name` is its folder's name and the folder belongs to the user whose home holds it. It copies nothing else: not `bench.toml` (its Admin secret), not the site configs (their database passwords). Registration runs as root, so discovery still reads `bench.toml` and the site configs once, for the bench's name, sites, domains and ports.

What this costs on Pilot: the [MariaDB checks](/agent/collected), which need a site's database password.

To remove Wolf from a Pilot host, run `systemctl disable --now wolf-pilot-export.timer` before deleting the `wolf-agent` user: the helper's unit runs with that group, and fails at every run without it.

<steps level="3">

### Check what Wolf finds

```bash
sudo wolf-agent discover
```

### Check what would be sent

```bash
sudo -u wolf-agent wolf-agent --config /etc/wolf-agent/config.json check
```

`check` collects once and prints the JSON payload. Nothing is sent. See [Commands](/agent/commands).

</steps>

<warning>

Worker log names are globbed at registration. Re-run `wolf-agent register` after changing `[[workers]]` in `bench.toml`.

</warning>

### Configuration

Deployment events from Pilot tasks are on by default. The `pilot` section of `/etc/wolf-agent/config.json`:

```json [config.json]
{
  "pilot": {
    "deployments": true,
    "api_url": null,
    "token": null,
    "jwt_secret": null
  }
}
```

<field-group>
<field name="pilot.deployments" type="boolean">

Poll Pilot tasks and turn them into events. `false` turns task polling off. Default `true`.

</field>

<field name="pilot.api_url" type="string | null">

Overrides the per-bench Admin API address `http://127.0.0.1:<admin.port+1>`. It applies to every Pilot bench on the host, so set it only on single-bench hosts.

</field>

<field name="pilot.token" type="string | null">

A bench-scoped Admin API token, used only without `wolf-pilot-export`'s copy.

</field>

<field name="pilot.jwt_secret" type="string | null">

The bench's `[admin] jwt_secret`, to mint a one-hour token, only without `wolf-pilot-export`'s copy.

</field>
</field-group>

With `wolf-pilot-export`, Wolf needs neither. The full config is on [Configuration](/agent/configuration).

## What Wolf does on a Pilot bench

<table>
<thead>
  <tr>
    <th>
      Area
    </th>
    
    <th>
      What Wolf does
    </th>
    
    <th>
      On v1.0.0-rc.1 and rc.2
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Discovery
    </td>
    
    <td>
      Searches <code>
        /home/*/pilot/benches/*
      </code>
      
      . A <code>
        bench.toml
      </code>
      
       with <code>
        [bench] name
      </code>
      
       and <code>
        python
      </code>
      
       is a Pilot bench, read with its real keys
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Sites
    </td>
    
    <td>
      Reads <code>
        sites/*/site_config.json
      </code>
      
      , plus <code>
        domains
      </code>
      
       (plain strings or <code>
        {"domain": …, "route": …}
      </code>
      
      ) for host → site mapping
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Process logs
    </td>
    
    <td>
      Tails <code>
        web
      </code>
      
       and its stderr file, and the worker and schedule logs of a bench out of lite mode. On a sandboxed bench, Frappe's own logs in <code>
        logs/workload/
      </code>
    </td>
    
    <td>
      checked (lite mode); <code>
        logs/workload/
      </code>
      
       unit tested
    </td>
  </tr>
  
  <tr>
    <td>
      nginx
    </td>
    
    <td>
      Tails <code>
        <bench>/logs/nginx-access.log
      </code>
      
      , in the <code>
        pilot_access
      </code>
      
       format
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Redis queue
    </td>
    
    <td>
      Queue length, RQ registries, workers and Redis memory from <code>
        [redis] queue_port
      </code>
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      MariaDB
    </td>
    
    <td>
      Not on Pilot: the site's database password stays readable by the bench user only
    </td>
    
    <td>
      —
    </td>
  </tr>
  
  <tr>
    <td>
      Processes
    </td>
    
    <td>
      The bench user's systemd <strong>
        user
      </strong>
      
       units, <code>
        <bench>-<process>.service
      </code>
      
      , as <code>
        wolf-pilot-export
      </code>
      
       copies them (<code>
        bench_processes_down
      </code>
      
      ). The Admin is socket-activated: inactive until its first request is not down
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Deployments
    </td>
    
    <td>
      A <code>
        deployment
      </code>
      
       event (category <code>
        pilot
      </code>
      
      ) when a task such as update, migrate or app install <strong>
        starts
      </strong>
      
      , and an <code>
        error
      </code>
      
       event (<code>
        pilot_task_failed
      </code>
      
      ) when one fails, from <code>
        wolf-pilot-export
      </code>
      
      's copy
    </td>
    
    <td>
      checked with a migrate run from the Admin
    </td>
  </tr>
  
  <tr>
    <td>
      "Enable Wolf for this bench" toggle in Pilot
    </td>
    
    <td>
      Needs a change in frappe/pilot
    </td>
    
    <td>
      <strong>
        not done
      </strong>
    </td>
  </tr>
</tbody>
</table>

The metrics themselves are described on [What is collected](/agent/collected).

## Bench layout

### Benches

Pilot's `install.sh` installs into `$HOME/pilot` as a non-root bench user (`frappe` by default). Benches live in `~/pilot/benches/<name>/`, each with `apps/`, `sites/`, `env/`, `logs/`, `config/`, `tasks/` and `bench.toml`.

### bench.toml

Mode `0600`, readable by the bench user only. Wolf reads it at registration, which runs as root:

<table>
<thead>
  <tr>
    <th>
      Key
    </th>
    
    <th>
      Use
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        [bench] name
      </code>
    </td>
    
    <td>
      Required, together with <code>
        python
      </code>
      
      . The bench name and the Pilot marker
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        [redis] queue_port
      </code>
    </td>
    
    <td>
      Queue Redis port. Default <code>
        11000
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        [admin] port
      </code>
    </td>
    
    <td>
      Default <code>
        7000
      </code>
      
      . The Admin backend listens on <code>
        127.0.0.1:<port + 1>
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        [admin] jwt_secret
      </code>
    </td>
    
    <td>
      Only when Wolf mints an Admin token, which needs <code>
        bench.toml
      </code>
      
       readable. Pilot writes it at the Admin's first session
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        [production] enabled
      </code>
    </td>
    
    <td>
      Kept for information
    </td>
  </tr>
</tbody>
</table>

### Processes and logs

Pilot runs a production bench as **systemd user units** of the bench user (`systemctl --user`), with linger on: `<bench>-web`, `<bench>-redis_cache`, `<bench>-redis_queue`, `<bench>-admin` (socket-activated, `<bench>-admin.socket`) and app processes. Pilot's MariaDB is the user unit `pilot-mariadb`.

**Lite mode**, on by default (`[lite_mode] enabled`), runs the web server, the job workers and the scheduler in one `web` process (`frappe.runner`). Its logs, Python's `logging` output included, go to `logs/web.log.error.log`. Out of lite mode there are worker and schedule processes, logged as `worker_<queue-slug>_<i>.log` and `schedule.log`, with stderr in `<log>.error.log`.

**The sandbox.** A new systemd bench runs its workload sandboxed, and Frappe's own logs (`frappe.log`, `scheduler.log`…) are then in `logs/workload/`. The sandbox needs unprivileged user namespaces, which Ubuntu 24.04 refuses by default (`kernel.apparmor_restrict_unprivileged_userns = 1`): `pilot setup production` then fails, and Pilot advises `sandbox = false` under `[production]`. Wolf reads both layouts.

### nginx

Each site vhost logs to `<bench>/logs/nginx-access.log`:

```nginx
log_format pilot_access '$pilot_client_addr [$time_local] "$request_method $uri" $status "$host" $request_time';
```

This format has **no query string** (`$uri`, not `$request_uri`) and **no User-Agent**. On a Pilot bench, Wolf's [web detection](/security/detection) sees probed paths (`/.env`, `/.git/`, CMS and appliance paths) but not injections or path traversal carried in a query string, nor scanners named by their User-Agent. [Suricata](/security/wazuh-suricata#suricata) sees the full requests.

### Tasks

Admin operations are tasks, stored as `<bench>/tasks/<YYYYMMDD-HHMMSS-hex>/`, mode `0700`:

- `meta.json`: `task_id`, `command`, `args`, `queued_at`, `started_at`, `finished_at` (UTC ISO-8601), `exit_code`, `failure`.
- `status`: `queued`, `running`, `success`, `failed` or `killed`.

## Deployment events from Pilot tasks

Wolf reports these task commands:

`update`, `retry-update`, `complete-migration`, `migrate`, `revert-migration`, `revert-apps`, `revert-site`, `switch-branch`, `get-and-install-app`, `install-app`, `uninstall-app`, `remove-app`, `build`, `restart-services`, `switch-lite-mode`, `setup-nginx`, `restore-site`, `reinstall-site`.

The site comes from the task's `site` / `sites` arguments; nothing else of the arguments is kept.

### Where tasks are read

1. **Task files**, `<bench>/tasks/*/meta.json` and `status`, when the agent can read them (an agent run as the bench user).
2. **wolf-pilot-export's copy**, `/var/lib/wolf-pilot-export/<bench>.json`, when it is less than 5 minutes old: the normal case.
3. **Admin API**, `GET http://127.0.0.1:<admin.port+1>/api/v1/tasks?limit=100`, only without the two others. It needs a bench-scoped token: `pilot.token`, or one Wolf mints from `pilot.jwt_secret` or `bench.toml`. Pilot lists every token it verifies among the Admin's active sessions, and a bench-scoped token can do everything the Admin can: the copy avoids both.

### How events are produced

- A `deployment` event is sent when the task starts, timestamped at `started_at`. An incident during a long migrate links to it, for example through the "502 spike after deployment" [preset](/alerts/presets).
- An `error` event is sent if the task ends `failed`. It carries `failure.code`, `failure.message` and `exit_code`.
- Reported task ids are kept for 3 days in `<spool_dir>/pilot-tasks.json`.
- The first poll skips history and only picks up queued or running tasks.

A migrate also records the site's own `deployment` event (source `frappe`), as on any bench: Pilot's says which task ran it.

## Wolf next to Pilot's own monitoring

From the Pilot docs:

- `pilot-monitor.service` collects host, database and bench metrics and pings production sites.
- `[resource_limits]` raises CPU, memory, disk and uptime alerts after 5 minutes. They go to Central (on Central-managed hosts), to `webhook_endpoints` and to mail.
- `[telemetry]` ships metrics and logs to a region's "Datum" endpoint with a Central-issued token.

Wolf reads the same local files and does not interfere with any of these. What it adds on a self-hosted Pilot host:

- Tracebacks, failed scheduled jobs and worker crashes as events.
- 5xx/502 per site.
- SSH signals.
- Incidents tied to the Pilot task that preceded them.

All of it is kept on your own Wolf site.

## The Wolf App on a Pilot bench

The Wolf App installs on a Pilot bench like any app (`pilot get-app`, `pilot install-app`). Pilot checks that every app an app requires in `hooks.py` is declared in its `pyproject.toml` `[tool.bench.frappe-dependencies]`, Frappe excepted: Frappe is implicit, and an app that lists it in `required_apps` is refused.

## What Pilot would need

1. **"Enable Wolf for this bench" toggle.** A `[wolf]` table in `bench.toml` (`enabled`, `url`) plus an Admin settings switch, which would install and register the agent. It belongs in frappe/pilot.
2. **A read-only machine token for the Admin API** (`tasks:read`, unit states), which would make the root helper unnecessary.
3. **The query string and User-Agent in pilot_access**, for web attack detection from the access log.
