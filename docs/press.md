# Wolf on Press (Frappe Cloud) servers

[Press](https://github.com/frappe/press) is the Frappe app behind Frappe Cloud. It
manages servers through the **Press agent** ([frappe/agent](https://github.com/frappe/agent)),
a Flask + RQ service that runs on each server. This page covers what the Wolf agent
does on an *app server* managed that way, which source files each behaviour relies on,
and what is still unverified.

Checked on a Press app server set up by Press's own Ansible roles (frappe/press `7ce25f2`,
frappe/agent `6bbd199`, 2026-11-18), with benches and sites created through the Press agent's API
and real deploys (New Bench, Update Site Migrate, Bench Restart, Archive Bench, failed jobs):
`dev/press/` sets it up. See "Checked on a Press server" at the end.

Sources were read at these commits. Every link below is pinned to them:

- frappe/agent [`64b9812`](https://github.com/frappe/agent/tree/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a) (2026-10-27)
- frappe/press [`aedd7d1`](https://github.com/frappe/press/tree/aedd7d1237e49153e4852a7ca693b3a50c6028b2) (2026-10-29)


## Summary

| Area | What Wolf does | Status |
|------|----------------|--------|
| Detection | Press mode turns on when `/home/frappe/agent/config.json` has a `benches_directory` key, when it is there next to `jobs.sqlite3` (the daemon cannot read it: 0600), or when `"platform": "press"` is set (registration saves it) | checked |
| Benches | Lists `<benches_directory>/*` that have `sites/` and `config.json` with a `docker_image`, or, unreadable, `config.json` next to a `docker-compose.yml` | checked |
| Rediscovery | Rescans every `press.rediscover_interval` seconds (default 60), because each deploy creates a new bench directory; a bench's image, web port and domains come from its readable `docker-compose.yml` and `nginx.conf` | checked |
| Bench logs | Tails `<bench>/logs/*` (bind-mounted from the container) and `sites/<site>/logs/*`, using the same parsers as other benches | done |
| nginx | Tails `/var/log/nginx/access.log` (Press's `main` format, which logs `$host`) and maps custom domains to sites | done, unit tested |
| Redis queue | Reads `queue_length`, the RQ failed/started registries, live workers and Redis memory/evictions from `redis://127.0.0.1:<rq_port>` (bench `config.json`, or 11000 + the bench's port offset) | checked |
| TLS expiry | Checks every site and custom domain like on other benches. On Press the certificates live on the proxy server, so the public handshake measures what customers see | done (generic) |
| Backups | From the Press agent's job history: `backup_age_hours` from each site's newest successful Backup Site job, `backup_failed` when one fails (offsite backups are deleted from the server after the upload, streamed ones never written); `backups.press: true` reads the folder instead | checked |
| Processes | **Skipped**: supervisor runs inside each bench container and Wolf never runs `docker` | — |
| MariaDB | Not on Press: the site's database password is in its `site_config.json`, mode 0600 for `frappe` | — |
| Site config risks | Need the 0600 site configs: no `site_config_risks` sample (unknown) | checked |
| Exposed services | Each bench's queue and cache Redis are published on all interfaces by the Press agent (for secondary servers): `service_exposed`, which the server's firewall must cover | checked |
| Deploy correlation | Emits a `deployment` event for each deploy, update or migrate job in the Press agent's `jobs.sqlite3`, and an `error` event when one fails | checked |
| Site events | The Wolf App on a Press bench (`frappe_cloud` in its config) names its bench from the container hostname and its server from Press's `supervisor.conf` (`<server>-gunicorn.access.log`, its name in Press); registration names the agent's host after the same Press name unless `--hostname` is given or it was registered before | checked (the test server's hostname is its Press name) |
| Fallback | If `jobs.sqlite3` cannot be read, emits a `deployment` event when a new bench appears or a site moves to another bench | done, unit tested |
| Press credentials | None are needed. Everything is read from local files. | — |
| Real Press server | **Not tested yet** (see [Unverified](#unverified)) | — |

## Server layout (from the sources)

### Press agent directory and config

- Ansible clones the agent into `/home/frappe/agent/repo`, creates a venv at
  `/home/frappe/agent/env`, and runs `agent setup config` / `agent setup database`
  from `/home/frappe/agent` ([`press/playbooks/roles/agent/tasks/main.yml#L1-L33`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/agent/tasks/main.yml#L1-L33)).
- `agent setup config` writes `config.json` with `benches_directory: /home/<user>/benches`,
  `nginx_directory: /home/<user>/agent/nginx`, `redis_port: 25025`, `web_port: 25052`, …
  ([`agent/cli.py#L70-L101`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/cli.py#L70-L101)). The `Server` class reads these keys
  ([`agent/server.py#L70-L79`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L70-L79)). Wolf detects Press through this file and its
  `benches_directory` key.
- The Press playbook also creates `/home/frappe/benches`
  ([`press/playbooks/roles/bench/tasks/main.yml#L1-L7`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/bench/tasks/main.yml#L1-L7)).

### Benches

- `Server.bench_init` creates `<benches_directory>/<name>/` with `logs/`, `sites/` and `config/`,
  writes the bench config to `<bench>/config.json`, renders `docker-compose.yml`, and copies
  `config/` and `sites/` out of the bench's Docker image ([`agent/server.py#L116-L148`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L116-L148)).
  The apps live **inside the image**. There is no `apps/frappe` on the host, so Wolf's
  generic check (`sites/` + `apps/frappe`) misses Press benches. A Press bench is identified
  by `config.json` with a `docker_image` key.
- `Server.benches` treats every entry of `benches_directory` as a bench
  ([`agent/server.py#L889-L894`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L889-L894)). A `Bench` requires `sites/`, `sites/common_site_config.json`
  and `config.json` ([`agent/bench.py#L45-L69`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L45-L69)).
- Bench names follow the pattern `bench-<candidate>-<server>`
  ([`press/press/doctype/bench/bench.py#L222-L236`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/press/doctype/bench/bench.py#L222-L236)). Wolf uses the directory name.
- Bench config keys come from Press's `Bench` doctype: `docker_image`, `web_port` (18000+offset),
  `socketio_port`, `rq_port` (11000+offset), `rq_cache_port`, `single_container: true`, …
  ([`press/press/doctype/bench/bench.py#L347-L384`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/press/doctype/bench/bench.py#L347-L384)).
- **Containers.** With `single_container`, `Bench.start` runs one container named after the bench.
  It mounts `<bench>/sites`, `<bench>/logs` and `<bench>/config` into
  `/home/frappe/frappe-bench/…` and publishes `-p 0.0.0.0:<rq_port>:11000`
  ([`agent/bench.py#L839-L882`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L839-L882)). Without `single_container`, the agent runs `docker stack deploy` with
  `templates/bench/docker-compose.yml.jinja2`, which bind-mounts the same `logs` and `sites`
  ([`agent/templates/bench/docker-compose.yml.jinja2`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/bench/docker-compose.yml.jinja2)). In both cases the bench logs are
  ordinary files on the host. Wolf never runs `docker`.
- **Sites** are `sites/<site>/` directories with a `site_config.json`. A site's custom domains
  are listed in its `site_config.json` under `domains`. The bench nginx config maps them back
  to the site ([`agent/bench.py#L1442-L1447`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L1442-L1447),
  [`agent/templates/bench/nginx.conf.jinja2#L9-L15`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/bench/nginx.conf.jinja2#L9-L15)). Wolf reads the same key, so a 502 logged
  for `erp.customer.com` is counted against the right site.
- Inside the container, supervisor writes `web.log`/`web.error.log`, `schedule.log`/`schedule.error.log`
  and `worker.log`/`worker.error.log` into `logs/`
  ([`agent/build_configs/config/supervisor.conf#L7-L29`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/build_configs/config/supervisor.conf#L7-L29)). Frappe's own loggers write
  `frappe.web.log`, `scheduler.log` and the other files there as on any bench. Wolf now also
  tails `schedule.error.log` for tracebacks, on every bench (the file is simply absent where
  nothing writes it).

### Redis (queue lengths)

`sites/common_site_config.json` holds the **in-container** address `redis://localhost:11000`
([`agent/build_configs/common_site_config.json#L1-L9`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/build_configs/common_site_config.json#L1-L9)). From the host, the queue Redis is
reachable on the published `rq_port`. The Press agent's own RQ exporter connects there
(`/benches/metrics`, [`agent/web.py#L405-L431`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/web.py#L405-L431) and [`agent/exporter.py#L8-L11`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/exporter.py#L8-L11)).
Wolf uses `redis://127.0.0.1:<rq_port>`. When a bench has no `rq_port`, Wolf skips its queue metrics.

### nginx

- The root `nginx.conf` is rendered to `/home/frappe/agent/nginx/nginx.conf`
  ([`agent/server.py#L1229-L1244`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L1229-L1244)) and symlinked to `/etc/nginx/nginx.conf`
  ([`press/playbooks/roles/agent/tasks/main.yml#L85-L97`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/agent/tasks/main.yml#L85-L97)). It includes every
  `<benches_directory>/*/nginx.conf`.
- Every vhost uses one log ([`agent/templates/nginx/nginx.conf.jinja2#L45-L48`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/nginx/nginx.conf.jinja2#L45-L48)):

  ```
  log_format main '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" "$http_x_forwarded_for" "$host" $request_time';
  access_log /var/log/nginx/access.log main;
  ```

  The site name (or a custom domain) **is** in the log, as the last quoted field `"$host"`.
  Wolf's nginx parser already reads trailing quoted fields. Press mode adds the
  domain→site map. The bench templates set no per-bench `access_log`
  ([`agent/templates/bench/nginx.conf.jinja2`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/bench/nginx.conf.jinja2)). Behind a Press proxy, `$remote_addr` is
  still the client: `set_real_ip_from <proxy_ip>` takes it from the proxy's `X-Real-IP` (same file
  L59-L62; checked on dev/press).
- Proxy servers (`n*` hosts) use the same root template, but they have no benches. Registration
  recognises one (`<agent_dir>/nginx/proxy.conf`) and adds `/var/log/nginx/access.log` to
  `extra_logs` with `"site_from_host": true`.

### Job history (deploys, updates, migrations)

- Every Press agent job is stored in the SQLite database `jobs.sqlite3`, relative to the
  agent's working directory (`/home/frappe/agent`, the supervisor `directory=`). It runs in
  WAL mode ([`agent/job.py#L45-L54`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L45-L54),
  [`agent/templates/agent/supervisor.conf.jinja2#L1-L36`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/agent/supervisor.conf.jinja2#L1-L36)). The tables come from
  peewee models ([`agent/job.py#L301-L344`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L301-L344), created by `agent setup database`,
  [`agent/cli.py#L171-L175`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/cli.py#L171-L175)):
  - `jobmodel(id, name, status ∈ Pending/Running/Success/Failure, agent_job_id, data, enqueue, start, end, duration)`
  - `stepmodel(id, name, job_id, status, data, start, end, duration)`
- `agent_job_id` is the `X-Agent-Job-Id` header Press sends, which is the name of the
  **Agent Job** document in Press ([`press/agent.py#L960-L966`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/agent.py#L960-L966)). Wolf copies it into the
  event payload so you can open the same job in the Press dashboard.
- At enqueue time, `data` is `{"function", "args", "kwargs"}` ([`agent/job.py#L124-L138`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L124-L138)).
  When the job ends, it is **overwritten** with the result or `{"traceback": …}`
  ([`agent/job.py#L78-L91`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L78-L91)). Step `data` keeps each step's command result, including the
  `docker exec … <bench> bench --site <site> …` command line
  ([`agent/base.py#L65-L111`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/base.py#L65-L111), [`agent/bench.py#L177-L200`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L177-L200), [`agent/site.py#L61-L62`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/site.py#L61-L62)).
- Timestamps are naive `datetime.now()`, i.e. server local time. Wolf converts them to UTC
  as local time.

Wolf treats these job names as deployments. The names and argument orders come from the
`@job` decorators:

| Press agent job | Source | bench / site taken from |
|-----------------|--------|--------------------------|
| New Bench | [`agent/server.py#L157-L174`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L157-L174) | `args[0]` (bench) |
| Update Site Pull, Update Site Migrate | [`agent/server.py#L558-L600`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L558-L600) | `args[0]` site, `args[2]` target bench |
| Recover Failed Site Migrate / Pull, Move Site to Bench | [`agent/server.py#L658-L705`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L658-L705) | same |
| Recover Failed Site Update | [`agent/server.py#L729-L733`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L729-L733) | `args[0]` site, `args[1]` bench |
| Update Bench In Place | [`agent/bench.py#L1086-L1092`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L1086-L1092) | `args[0]` sites; bench from steps |
| Patch App, Bench Restart, Rebuild Bench Assets | [`agent/bench.py#L592-L602`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L592-L602), [`agent/bench.py#L1026-L1032`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L1026-L1032) | steps |
| Migrate Site, Install / Uninstall App on Site | [`agent/site.py#L282-L322`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/site.py#L282-L322) | steps |

`Bench` and `Site` methods carry no bench or site name in their arguments, because `self`
is not stored. For those jobs, Wolf searches the job and step `data` for a known bench name
and for `--site <name>`.

## How deployment events are produced

- Wolf opens `jobs.sqlite3` with `file:…?mode=ro` while the agent's `-wal`/`-shm` files are there,
  else with `immutable=1`: a reader creates them when missing, and files owned by `wolf-agent` (the
  agent's folder is `frappe`-group writable) leave the Press agent unable to write its database
  (seen on dev/press after `sudo -u wolf-agent wolf-agent check`). Wolf never writes to it.
- **One `backup_failed` event per failed Backup Site job** (error, critical), read apart from the
  deployment jobs (own position, by `end`: queued backups never hold deployments back, and the first
  poll replays no old failure). Successful ones, local, offsite or streamed (the site from the
  result's file paths, else its `https://<site>/backups/` url), give `backup_age_hours`.
- **One `deployment` event per job**, sent as soon as the job has started. Its timestamp is
  the job's `start`, so Wolf's "502 spike after deployment" rule links incidents that happen
  *during* a long migrate. If the bench cannot be determined yet, the event waits up to
  2 minutes for a step to name it, then ships host-scoped. Wolf's incident correlation also
  matches host-scoped deployments (`scope_clause` in `dodock_wolf/wolf/events.py`).
  Fields: `category: "press"`, `source: "press-agent"`, and
  `payload.press_job / agent_job_id / local_job_id / sites`.
- **One `error` event (`category: "press_job_failed"`, warning)** when such a job ends in
  `Failure`. Its payload holds the failed step names and the tail of the traceback/output.
- **Deduplication.** Emitted job ids and a floor id are saved in
  `<spool_dir>/press-jobs.json`. Restarts never emit an event twice. On the first run,
  history is skipped and only jobs still Pending/Running are picked up. A job stuck in
  Pending/Running for more than 24 h (e.g. a crashed RQ worker) is dropped, so it cannot
  block progress.
- **Fallback without database access**: `<spool_dir>/press-benches.json` keeps a
  bench→site snapshot. A new bench directory, or a site whose directory moved to another
  bench (`Server.move_site`, [`agent/server.py#L735-L750`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L735-L750)), produces a `deployment` event
  stamped with the time it was noticed.

Rediscovery rebuilds the log sources when the set of benches or sites changes. Logs of a
bench created while Wolf runs are read from the start, because they are new files.
A moved site's logs move with its directory, so they are read from the end to avoid replaying them.

## Configuration

Press mode is auto-detected. To force it, or to change the paths:

```json
{
  "platform": "press",
  "press": {
    "agent_dir": "/home/frappe/agent",
    "nginx_access_log": "/var/log/nginx/access.log",
    "rediscover_interval": 60,
    "deployments": true
  }
}
```

`"platform": "generic"` disables Press handling. `wolf-agent discover --platform press` and
`wolf-agent register --platform press` show or record the Press layout. In Press mode the
`benches` list in the config is refreshed from disk at start and on every rediscovery.

Permissions: the `wolf-agent` user must be able to read `/home/frappe/benches/*/logs`,
`sites/*/site_config.json`, `/home/frappe/agent/config.json`, `jobs.sqlite3` (plus `-wal`/`-shm`)
and `/var/log/nginx/access.log`. `install.sh` already adds the user to the `frappe` and `adm`
groups. Whether Press's directory modes allow group read has **not been checked** on a real server.

## Wolf next to Press's own monitoring

Press already ships a monitoring stack. Wolf does not replace it and does not touch it:

- **Monitor server** (`monitor.yml`): Prometheus, Alertmanager, Blackbox exporter and Grafana
  ([`press/playbooks/monitor.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/monitor.yml)). Prometheus probes sites, domains and TLS with
  blackbox `http_2xx` and scrapes the Press-managed servers
  ([`press/playbooks/roles/prometheus/templates/prometheus.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/prometheus/templates/prometheus.yml)). Press pushes
  alert rules and routes to it through the agent's `Monitor` class
  ([`agent/monitor.py#L11-L40`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/monitor.py#L11-L40)). These come from Press doctypes such as *Prometheus Alert Rule*,
  and the Alertmanager webhook lands in *Alertmanager Webhook Log*.
  Press's *Incident* doctype ([`press/press/doctype/incident/incident.py`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/press/doctype/incident/incident.py)) escalates
  outages by phone (Twilio) to Frappe staff and customers.
- **App servers** (`server.yml`): node_exporter, cAdvisor, statsd_exporter (the bench
  config sets `statsd_host`), filebeat and fail2ban, among other roles
  ([`press/playbooks/server.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/server.yml)). Filebeat ships `/var/log/*.log`, the nginx module and
  each bench's `logs/monitor.json.log` (Frappe's request/job monitor, enabled through
  `"monitor": true`) to a central Elasticsearch/Kibana log server
  ([`press/playbooks/roles/filebeat/templates/inputs.d/monitor.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/filebeat/templates/inputs.d/monitor.yml),
  [`press/playbooks/roles/filebeat/templates/modules.d/nginx.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/filebeat/templates/modules.d/nginx.yml)).
  The agent also moves `monitor.json.log` aside for Press's analytics
  (`Bench.fetch_monitor_data`, [`agent/bench.py#L300-L330`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L300-L330)). Wolf does not tail that file.
- The agent exposes RQ metrics per bench at `/benches/metrics` ([`agent/web.py#L405-L431`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/web.py#L405-L431)).

Wolf adds what that stack does not provide on a self-hosted Press install: Frappe-level
tracebacks, failed scheduled jobs and worker crashes read from bench logs, 5xx/502 per
site, SSH signals, and **incidents correlated with the Press job that caused them**. All of
it lives on your own Wolf site, without access to the Press monitor server.
The two stacks overlap on host metrics (node_exporter vs Wolf's `/proc` sampling) and on
queue lengths. Wolf's are light, and you can turn them off with `collect_host_metrics: false`.

## Limitations

- Only app servers with benches are supported directly. Proxy and database servers have no
  bench, so add their logs through `extra_logs`.
- A finished job's `data` is its result, its arguments gone. A job Wolf first sees finished
  takes the bench its last step ran in (the step's `directory` under the benches folder, else a
  known bench named in it: a site move ends on its target) and the site from `--site`. A job
  without any such step is reported host-scoped.
- The filesystem fallback cannot tell a deploy from a manual move, and it has no failure
  signal.
- Jobs are matched by display name. If Press renames a job, it is no longer recognised;
  add the new name to `DEPLOY_JOBS` in `agent/wolf_agent/press.py`.
- Shared FS: checked on a primary server (item 7 below). An auto-scaling secondary app server runs
  the primary's benches from an NFS mount, its containers writing to the same bench logs: Wolf
  agents on both would read them twice. Not checked; tail bench logs on the primary only.
- Frappe Cloud's hosted servers are not open to customers. This is for **self-hosted Press**
  deployments, where you control the server.

## Checked on a Press server

On `dev/press` (Press's roles `essentials`, `user`, `nginx`, `agent`, `bench`, `docker`,
`statsd_exporter` on Ubuntu 22.04; the Wolf agent installed with `agent/install.sh`):

1. **Modes.** `/home/frappe` is 0750, the bench logs, `jobs.sqlite3`, `-wal` and `-shm` 0644:
   `mode=ro` works for a member of the `frappe` group. The Press agent writes its own
   `config.json`, each bench's `config.json` and every `site_config.json` /
   `common_site_config.json` 0600, so the daemon (`wolf-agent`) cannot read them: detection,
   rediscovery and site config checks read around them (see Summary).
2. **Job data.** Job names match `DEPLOY_JOBS`; `agent_job_id` is the `X-Agent-Job-Id`. A finished
   job's `data` is `null`; each step keeps `command` and `directory`, e.g. Update Site Migrate:
   `set-maintenance-mode on` in the source bench, then `docker exec … <target> bench --site <site>
   migrate` in the target.
3. **`$host`.** Site requests carry the site in the last quoted field. The Press agent's vhost on
   443 logs the server name there (`"f1-press"`), which is no site: those lines count for nothing.
4. **`rq_port`.** Set on every new bench and published `0.0.0.0:<rq_port>:11000`, with the cache
   on `<rq_cache_port>`: Wolf's exposure check reports both. For a bench registration read, the
   daemon keeps that `rq_port` and image (`press.keep_registered`); a bench found later gets
   `11000 + offset` and the image from its `docker-compose.yml`, which Update Bench In Place does
   not change.

5. **Behind a proxy server** (Press's `proxy` role, Add Upstream / Add Host / Add Site to Upstream):
   the app server's `$remote_addr` is the real client (`set_real_ip_from <proxy_ip>` and the
   proxy's `X-Real-IP`), in its access log and in the site's failed logins. A block applied on the
   app server stopped nothing; on the proxy it did. So the app server's agent reports its proxy
   (`behind_proxy` in every push, from the Press agent's `proxy_ip`, saved by registration or
   `wolf-agent refresh`); the Wolf site proposes blocks there for SSH events only and lists the
   others as held. The Wolf agent on the proxy (detected by `nginx/proxy.conf`) reads its access
   log, sites from `$host` and `nginx/hosts/*/map.json`, and proposes the blocks that work. The
   Press agent writes each site's TLS key 0644 there, readable by the `frappe` group.

6. **Backups.** A local-only Backup Site job keeps its files in `sites/<site>/private/backups` and
   lists them in its result (`data.backups.*.path`); an offsite one deletes them after the upload
   (`upload_offsite_backup`, agent/site.py) unless the server keeps them, a streamed one writes
   none. Wolf reads the job history: an age per site, and `backup_failed` for a failed job (checked
   with the database server stopped).

7. **Shared FS** (Run Benches on Shared FS, `agent/server.py`, on a primary): the
   `link_benches_to_nfs` role links `/home/frappe/shared` to `/home/frappe/benches`, the job sets
   `benches_directory` to it and restarts the benches. Wolf kept its benches through the saved
   folder, compares job folders with links resolved (a New Bench is scoped before a refresh), and
   `wolf-agent refresh` saved `/home/frappe/shared`.

Still unchecked: an auto-scaling secondary server, MariaDB on the database server.
