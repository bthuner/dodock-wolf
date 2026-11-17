# Pilot benches

> Run the Wolf Agent on a Frappe Pilot host and turn Pilot tasks into deployment events.

[Pilot](https://github.com/frappe/pilot) is **Frappe's** server manager ("Frappe Server Manager"). It is not a Dokos tool: Dokos' public GitLab group has no Pilot repository. The Dokos documentation mentions Pilot only through the `pilot_endpoint` / `pilot_auth_token` site keys used by the Cloud Settings panel for Frappe Cloud v2 sites. These are the same keys Pilot writes into `site_config.json`.

## Install

Install the agent as on any host ([Wolf Agent](/install/wolf-agent)). Pilot benches need no extra step to be found.

<steps level="3">

### Let discovery run

Discovery searches `/home/*/pilot/benches/*`, in addition to the usual bench locations. A `bench.toml` with `[bench] name` and `python` marks a Pilot bench, and Wolf reads it with Pilot's real keys.

### Check what Wolf finds

```bash
wolf-agent discover
```

`discover` shows what bench discovery finds.

### Check what would be sent

```bash
wolf-agent check
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

A bench-scoped Admin API token. When set, Wolf uses it as is.

</field>

<field name="pilot.jwt_secret" type="string | null">

The bench's `[admin] jwt_secret`. Wolf mints its own one-hour token from it.

</field>
</field-group>

`token` or `jwt_secret` is needed unless the `wolf-agent` user can read `bench.toml`. Pilot's own file modes for `bench.toml` were not checked. The agent config file is written with mode 0600.

The full config is on [Configuration](/agent/configuration).

<caution>

`jwt_secret` signs Pilot Admin sessions. Anyone who holds it can mint bench-scoped tokens. Wolf reads `[admin] jwt_secret` from `bench.toml` at runtime only and never writes it to the Wolf config.

</caution>

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
      Status
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
      
       in addition to the old globs. A <code>
        bench.toml
      </code>
      
       with <code>
        [bench] name
      </code>
      
       and <code>
        python
      </code>
      
       is treated as a Pilot bench and read with its real keys
    </td>
    
    <td>
      done, unit tested
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
      done, unit tested
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
      
      , <code>
        schedule
      </code>
      
      , <code>
        worker_<queues>_<i>
      </code>
      
       and their stderr files, for both the systemd and the supervisor naming
    </td>
    
    <td>
      done, unit tested
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
      done, unit tested
    </td>
  </tr>
  
  <tr>
    <td>
      Redis queue
    </td>
    
    <td>
      Reads <code>
        queue_length
      </code>
      
      , the RQ failed/started registries, live workers and Redis memory/evictions from <code>
        redis://127.0.0.1:<[redis] queue_port>
      </code>
      
      . <code>
        redis_queue
      </code>
      
       in <code>
        common_site_config.json
      </code>
      
       takes precedence when present
    </td>
    
    <td>
      done
    </td>
  </tr>
  
  <tr>
    <td>
      Backups, TLS, MariaDB
    </td>
    
    <td>
      Same as on any bench: <code>
        sites/<site>/private/backups/
      </code>
      
      , each site and <code>
        domains
      </code>
      
       entry, the site's database credentials
    </td>
    
    <td>
      done (generic)
    </td>
  </tr>
  
  <tr>
    <td>
      Processes
    </td>
    
    <td>
      <code>
        supervisorctl status
      </code>
      
      , else systemd units whose name contains the bench name (<code>
        bench_processes_down
      </code>
      
      ). If Pilot's unit or program names do not contain the <code>
        [bench] name
      </code>
      
      , nothing is reported
    </td>
    
    <td>
      unverified
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
      
      ) when an update, migrate, branch switch, app install, build, restart or restore task <strong>
        starts
      </strong>
      
      , and an <code>
        error
      </code>
      
       event (<code>
        pilot_task_failed
      </code>
      
      ) when one fails. Read from the Admin API, or from the task files
    </td>
    
    <td>
      done, unit tested
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
  
  <tr>
    <td>
      Real Pilot host
    </td>
    
    <td>
      <strong>
        Not tested yet
      </strong>
    </td>
    
    <td>
      —
    </td>
  </tr>
</tbody>
</table>

The metrics themselves are described on [What is collected](/agent/collected).

## Bench layout

### Benches

Pilot's `install.sh` installs into `$HOME/pilot`. Benches live in `~/pilot/benches/<name>/` by default. On a root-only VPS, the installer creates a non-root bench user, hence the `/home/*/pilot/benches/*` glob.

Each bench holds `apps/`, `sites/`, `env/`, `logs/`, `config/`, `pids/` and `bench.toml`.

### bench.toml

Wolf reads these keys:

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
      
      . The Admin backend binds <code>
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
      Read at runtime only, never written to the Wolf config
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

`bench.toml` has **no** nginx or logs keys: "Nginx uses compiled-in defaults; it has no `[nginx]` table". `[monitor]` only names Pilot's own metric log. A `bench.toml` that is not Pilot's (no `[bench] python`) still goes through the old defensive parser.

### Process logs

Process logs go to `<bench>/logs/`:

- `web.log`
- `worker_<queue-slug>_<i>.log`. The slug is the queue list with every non-alphanumeric run replaced by `_`.
- `schedule.log`

stderr goes to `<log>.error.log` under systemd (for example `web.log.error.log`) and to `<name>.error.log` under supervisor. Wolf tails both spellings. Missing files cost nothing.

Frappe's own `frappe.web.log`, `scheduler.log` and `worker.log` are tailed as on every bench.

### nginx

Each site vhost logs `location /` to `<bench>/logs/nginx-access.log` in this format:

```nginx
log_format pilot_access '$pilot_client_addr [$time_local] "$request_method $uri" $status "$host" $request_time';
```

This is not the combined format: it has no ident or user, no byte count and no protocol. Wolf's nginx parser accepts it. Pilot's own access-log reader uses the same shape. `$host` is the site or one of its `domains`.

### Tasks

Long operations are tasks, stored as `<bench>/tasks/<YYYYMMDD-HHMMSS-hex>/`:

- `meta.json`: `task_id`, `command`, `args`, `queued_at`, `started_at`, `finished_at` (UTC ISO-8601), `exit_code`, `failure`.
- `status`: `queued`, `running`, `success`, `failed` or `killed`.

The directories are created with mode `0700`, so only the bench user can read them.

## Deployment events from Pilot tasks

Wolf reports these task commands:

`update`, `retry-update`, `complete-migration`, `migrate`, `revert-migration`, `revert-apps`, `revert-site`, `switch-branch`, `get-and-install-app`, `install-app`, `uninstall-app`, `remove-app`, `build`, `restart-services`, `switch-lite-mode`, `setup-nginx`, `restore-site`, `reinstall-site`.

The site comes from the task's `site` / `sites` arguments. The bench is the Pilot bench itself, since tasks are per bench.

### Where tasks are read

Wolf tries two sources, in this order.

1. **Admin API**: `GET http://127.0.0.1:<admin.port+1>/api/v1/tasks?limit=100`. It returns `TaskInfo.as_dict()` rows. The endpoint needs a **bench-scoped** session: `Authorization: Bearer <JWT>`. Pilot signs these tokens locally with HS256 over `{"sub": "admin", "iat", "exp", "scope": "bench", "jti"}` using `[admin] jwt_secret`, and verifies them with `require: ["exp"]`. Wolf uses `pilot.token` when you set one. Otherwise it mints a one-hour token with the same claim shape, from `pilot.jwt_secret` or from `bench.toml` when Wolf can read it. Each minted token has a `wolf-…` jti, so it appears in Pilot's active sessions and can be revoked.
2. **Task files**: `<bench>/tasks/*/meta.json` and `status`. This only works when the Wolf Agent runs as the bench user, because of the `0700` mode.

### How events are produced

Both sources follow the same rules as on [Press servers](/install/press).

- A `deployment` event is sent when the task starts, timestamped at `started_at`. An incident during a long migrate links to it, for example through the "502 spike after deployment" [preset](/alerts/presets).
- An `error` event is sent if the task ends `failed`. It carries `failure.code`, `failure.message` and `exit_code`.
- Reported task ids are kept for 3 days in `<spool_dir>/pilot-tasks.json`.
- The first poll skips history and only picks up queued or running tasks.

This replaces manual `wolf-agent mark-deployment --source pilot` markers on Pilot benches. Event fields are described in the [protocol](/reference/protocol).

## Wolf next to Pilot's own monitoring

From the Pilot docs:

- `pilot-monitor.service` collects host, database and bench metrics every 10 s and pings production sites every 5 s. Its logs go to `system/logs/`.
- `[resource_limits]` raises CPU, memory, disk and uptime alerts after 5 minutes. They go to Central (on Central-managed hosts), to `webhook_endpoints` (POST with a Bearer header) and to mail.
- `[telemetry]` ships metrics and logs (Fluent Bit tails `benches/*/logs/*.log`) to a region's "Datum" endpoint with a Central-issued token.

Wolf reads the same local files and does not interfere with any of these. What it adds on a self-hosted Pilot host:

- Tracebacks, failed scheduled jobs and worker crashes as events.
- 5xx/502 per site.
- SSH signals.
- Incidents tied to the Pilot task that preceded them.

All of it is kept on your own Wolf site.

<note>

Pilot's resource alerts could be pointed at Wolf through `webhook_endpoints`, but their payload is not documented, so Wolf does not accept them yet.

</note>

## Limitations and unverified points

### What Pilot would need

These items from issue #17 need changes or answers from the Pilot maintainers:

1. **"Enable Wolf for this bench" toggle.** A `[wolf]` table in `bench.toml` (`enabled`, `url`) plus an Admin settings switch, which would install and register the agent with the bench's paths. It belongs in frappe/pilot, and nothing like it exists there today.
2. **A machine token for the Admin API.** Today a bench-scoped session is a 24 h password session, or a JWT signed with `jwt_secret` or issued by the configured JWKS. A long-lived, read-only `tasks:read` token would avoid sharing `jwt_secret` with Wolf.
3. **A task event feed** (webhook or SSE across tasks) instead of polling `/tasks`.
4. **File modes.** Confirmation that `bench.toml` and `logs/` stay readable for a monitoring group, since tasks are `0700` by design.

### Unverified

These points come from reading the sources and running unit tests against fixtures built from them. Nothing has been run against a live Pilot host. In particular, these are untested:

- The minted token against a real Admin backend.
- `/api/v1/tasks` through Pilot's rate limits.
- File permissions for a non-bench user, including Pilot's modes for `bench.toml`.
- The exact worker queue-slug spelling on a running bench.
- Pilot's exact systemd unit and supervisor program names, which process checks depend on.

<collapsible>

Everything on this page is read from frappe/pilot at commit [`34613ea`](https://github.com/frappe/pilot/tree/34613eade8008a15a9ae61d28fca2627db52e7b9) (2026-10-29). Every link is pinned to it. The full write-up is [`docs/pilot.md`](https://github.com/bthuner/dodock-wolf/blob/main/docs/pilot.md); the Wolf side is [`agent/wolf_agent/pilot.py`](https://github.com/bthuner/dodock-wolf/blob/main/agent/wolf_agent/pilot.py).

**Which Pilot**

- Dokos documentation, Cloud Settings: [`content/2.next/3.dodock/configuration-cloud.md`](https://gitlab.com/dokos/documentation/-/blob/main/content/2.next/3.dodock/configuration-cloud.md)

**Layout**

- `PILOT_DIR="$HOME/pilot"`: [install.sh#L18](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/install.sh#L18)
- `cli_root()/benches`: [pilot/utils.py#L63-L70](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/utils.py#L63-L70)
- Bench state layout: [docs/architecture.md#state-layout](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/architecture.md#state-layout)

**bench.toml**

- Schema: [docs/configuration.md](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/configuration.md), [pilot/config/](https://github.com/frappe/pilot/tree/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/config)
- `[redis] queue_port`: [pilot/config/redis.py#L11-L15](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/config/redis.py#L11-L15)
- `[admin] port` + 1: [pilot/config/admin.py#L77-L79](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/config/admin.py#L77-L79), [pilot/managers/gunicorn/**init**.py#L35](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/gunicorn/__init__.py#L35)
- No `[nginx]` table: [docs/configuration.md#L178](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/configuration.md#L178)

**Process logs**

- Names: [pilot/managers/processes/definitions.py#L200-L370](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/processes/definitions.py#L200-L370); queue slug: [#L69-L71](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/processes/definitions.py#L69-L71)
- systemd stderr: [systemd_render.py#L65-L66](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/processes/systemd_render.py#L65-L66); supervisor stderr: [supervisor.py#L77-L78](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/processes/supervisor.py#L77-L78)

**nginx**

- [server.conf.template#L15](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/nginx/templates/server.conf.template#L15), [bench.conf.template#L349](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/nginx/templates/bench.conf.template#L349)
- Pilot's access-log reader: [admin/backend/providers/site_access_log.py#L14-L18](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/admin/backend/providers/site_access_log.py#L14-L18)

**Tasks**

- [pilot/internal/tasks/store.py#L33-L37](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/internal/tasks/store.py#L33-L37), [files.py#L55-L66](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/internal/tasks/files.py#L55-L66), [pilot/managers/task/reader.py#L210-L245](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/task/reader.py#L210-L245), [pilot/internal/tasks/models.py#L9-L14](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/internal/tasks/models.py#L9-L14)
- `0700` mode: [pilot/utils.py#L18](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/utils.py#L18), [#L47-L52](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/utils.py#L47-L52)
- Task commands: [pilot/tasks/](https://github.com/frappe/pilot/tree/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/tasks)

**Admin API**

- `/api/v1/tasks`: [admin/backend/api/v1/tasks.py#L43-L75](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/admin/backend/api/v1/tasks.py#L43-L75), mounted in [admin/backend/app.py#L86](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/admin/backend/app.py#L86)
- `TaskInfo.as_dict()`: [pilot/managers/task/models.py#L45-L62](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/pilot/managers/task/models.py#L45-L62)
- Bench-scoped session: [admin/backend/middleware.py#L35-L46](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/admin/backend/middleware.py#L35-L46), [#L95-L101](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/admin/backend/middleware.py#L95-L101)
- JWT signing and verification: [admin/backend/internal/session.py#L336-L354](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/admin/backend/internal/session.py#L336-L354)

**Pilot monitoring**

- [docs/production.md#monitoring](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/production.md#monitoring)
- [docs/configuration.md#alert-delivery](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/configuration.md#alert-delivery), [docs/configuration.md#telemetry](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/configuration.md#telemetry), [docs/architecture.md#integration-points](https://github.com/frappe/pilot/blob/34613eade8008a15a9ae61d28fca2627db52e7b9/docs/architecture.md#integration-points)

</collapsible>
