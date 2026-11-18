# Press servers

> Run the Wolf Agent on a self-hosted Press app server and get deploy-correlated incidents from its benches.

[Press](https://github.com/frappe/press) is the Frappe app behind Frappe Cloud. It manages servers through the **Press agent** ([frappe/agent](https://github.com/frappe/agent)), a Flask + RQ service on each server. This page covers the Wolf Agent on an *app server* managed that way.

<note>

This is for **self-hosted Press** deployments, where you control the server. Frappe Cloud's hosted servers are not open to customers.

</note>

Everything on this page was checked on a Press app server set up by **Press's own Ansible roles** (frappe/press [`7ce25f2`](https://github.com/frappe/press/tree/7ce25f221378cb4558cd3993f3283d75cc8fe7d7), frappe/agent [`6bbd199`](https://github.com/frappe/agent/tree/6bbd199c13e90f48950e2a06401ca98738455aaf), November 2026), with benches and sites created through the Press agent's API as Press creates them, and real deploys: New Bench, Update Site Migrate, Bench Restart, Archive Bench and failed jobs. The repository's [`dev/press`](https://github.com/bthuner/dodock-wolf/tree/main/dev/press) sets the same server up in a container.

<tip>

No Press server at hand? `dev/press` above, or the [Press demo](/reference/development), which simulates one for the Wolf Agent to read.

</tip>

## Install

Install the agent as on any host ([Wolf Agent](/install/wolf-agent)). Press mode needs no extra step and no Press credentials: everything is read from local files.

<steps level="3">

### Let detection run

The agent switches to Press mode when `/home/frappe/agent/config.json` exists with a `benches_directory` key. The daemon's own user cannot read that file (mode `0600`): there, the file and `jobs.sqlite3` being present is enough. Registration runs as root and also saves `"platform": "press"` and the benches folder in Wolf's config. In Press mode, the `benches` list in the config is refreshed from disk at start and on every rediscovery.

### Check what Wolf finds

```bash
wolf-agent discover --platform press
```

`discover` shows what bench discovery finds. `wolf-agent register --platform press` records the Press layout in the config.

### Check what would be sent

```bash
wolf-agent check --platform press
```

`check` collects once and prints the JSON payload. Nothing is sent. See [Commands](/agent/commands).

</steps>

### Configuration

Press mode is auto-detected. To force it, or to change the paths, edit `/etc/wolf-agent/config.json`:

```json [config.json]
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

<field-group>
<field name="platform" type="string | null">

`null` auto-detects Press, `"press"` forces it, `"generic"` disables Press handling.

</field>

<field name="press.agent_dir" type="string">

Press agent directory. Default `/home/frappe/agent`.

</field>

<field name="press.benches_directory" type="string | null">

The Press agent's `benches_directory`, saved by registration, which reads it as root. Used when the daemon cannot read the Press agent's config. Default `/home/frappe/benches`.

</field>

<field name="press.nginx_access_log" type="string">

Shared nginx access log. Default `/var/log/nginx/access.log`.

</field>

<field name="press.rediscover_interval" type="number">

Seconds between bench rescans. Default `60`.

</field>

<field name="press.deployments" type="boolean">

Turn Press agent jobs into `deployment` events. Default `true`.

</field>

<field name="backups.press" type="boolean">

Backup age checks on Press benches. Default `false`.

</field>
</field-group>

The full config is on [Configuration](/agent/configuration).

### Permissions

`install.sh` adds the `wolf-agent` user to the `frappe` and `adm` groups. On a server set up by Press's roles, that gives it:

<table>
<thead>
  <tr>
    <th>
      File
    </th>
    
    <th>
      Mode
    </th>
    
    <th>
      <code>
        wolf-agent
      </code>
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        /home/frappe
      </code>
    </td>
    
    <td>
      <code>
        0750 frappe:frappe
      </code>
    </td>
    
    <td>
      enters (group)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        <bench>/logs/*
      </code>
    </td>
    
    <td>
      <code>
        0644
      </code>
    </td>
    
    <td>
      reads
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        jobs.sqlite3
      </code>
      
      , <code>
        -wal
      </code>
      
      , <code>
        -shm
      </code>
    </td>
    
    <td>
      <code>
        0644
      </code>
    </td>
    
    <td>
      reads, with <code>
        mode=ro
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /var/log/nginx/access.log
      </code>
    </td>
    
    <td>
      <code>
        0640 www-data:adm
      </code>
    </td>
    
    <td>
      reads (group <code>
        adm
      </code>
      
      )
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        <bench>/docker-compose.yml
      </code>
      
      , <code>
        <bench>/nginx.conf
      </code>
    </td>
    
    <td>
      <code>
        0644
      </code>
    </td>
    
    <td>
      reads
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        /home/frappe/agent/config.json
      </code>
    </td>
    
    <td>
      <code>
        0600
      </code>
    </td>
    
    <td>
      no
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        <bench>/config.json
      </code>
    </td>
    
    <td>
      <code>
        0600
      </code>
    </td>
    
    <td>
      no
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sites/common_site_config.json
      </code>
      
      , <code>
        sites/<site>/site_config.json
      </code>
    </td>
    
    <td>
      <code>
        0600
      </code>
    </td>
    
    <td>
      no
    </td>
  </tr>
</tbody>
</table>

The Press agent writes its configs `0600`, so the daemon reads them only through registration, which runs as root. At run time a new bench is found from the files it can read: its image from `docker-compose.yml`; its web port, sites and custom domains from its `nginx.conf`; and its `rq_port` from that web port, since Press gives a bench one offset for all its ports (`web_port` 18000 + offset, `rq_port` 11000 + offset).

## What Wolf does on a Press server

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
      Detection
    </td>
    
    <td>
      Press mode turns on when <code>
        /home/frappe/agent/config.json
      </code>
      
       has a <code>
        benches_directory
      </code>
      
       key, when it is there next to <code>
        jobs.sqlite3
      </code>
      
       (unreadable), or when <code>
        "platform": "press"
      </code>
      
       is set
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Benches
    </td>
    
    <td>
      Lists <code>
        <benches_directory>/*
      </code>
      
       that have a <code>
        sites/
      </code>
      
       directory and <code>
        config.json
      </code>
      
       with a <code>
        docker_image
      </code>
      
      , or, unreadable, <code>
        config.json
      </code>
      
       next to a <code>
        docker-compose.yml
      </code>
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Rediscovery
    </td>
    
    <td>
      Rescans every <code>
        press.rediscover_interval
      </code>
      
       seconds (default 60), because each deploy creates a new bench directory
    </td>
    
    <td>
      checked: a new bench is tailed within a minute
    </td>
  </tr>
  
  <tr>
    <td>
      Bench logs
    </td>
    
    <td>
      Tails <code>
        <bench>/logs/*
      </code>
      
       (bind-mounted from the container) and <code>
        sites/<site>/logs/*
      </code>
      
      , with the same parsers as other benches
    </td>
    
    <td>
      done
    </td>
  </tr>
  
  <tr>
    <td>
      nginx
    </td>
    
    <td>
      Tails <code>
        /var/log/nginx/access.log
      </code>
      
       (Press's <code>
        main
      </code>
      
       format, which logs <code>
        $host
      </code>
      
      ) and maps custom domains to sites
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
        redis://127.0.0.1:<rq_port>
      </code>
      
       (bench <code>
        config.json
      </code>
      
      , or 11000 + the bench's port offset)
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      TLS expiry
    </td>
    
    <td>
      Checks every site and custom domain like on other benches. Certificates live on the proxy server, so the public handshake measures what customers see
    </td>
    
    <td>
      done (generic)
    </td>
  </tr>
  
  <tr>
    <td>
      Backups
    </td>
    
    <td>
      <strong>
        Skipped
      </strong>
      
       by default (<code>
        backups.press: false
      </code>
      
      ). Press takes backups through its agent and uploads them offsite
    </td>
    
    <td>
      off
    </td>
  </tr>
  
  <tr>
    <td>
      Processes
    </td>
    
    <td>
      <strong>
        Skipped
      </strong>
      
      : supervisor runs inside each bench container and Wolf never runs <code>
        docker
      </code>
    </td>
    
    <td>
      —
    </td>
  </tr>
  
  <tr>
    <td>
      MariaDB
    </td>
    
    <td>
      Not on Press: the site's database password is in its <code>
        site_config.json
      </code>
      
      , readable by <code>
        frappe
      </code>
      
       only
    </td>
    
    <td>
      —
    </td>
  </tr>
  
  <tr>
    <td>
      Site config risks
    </td>
    
    <td>
      <code>
        developer_mode
      </code>
      
      , <code>
        allow_tests
      </code>
      
      … need the <code>
        0600
      </code>
      
       site configs: no sample, shown as unknown
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Exposed services
    </td>
    
    <td>
      The Press agent publishes each bench's queue and cache Redis on all interfaces (<code>
        -p 0.0.0.0:<rq_port>:11000
      </code>
      
      , <code>
        <rq_cache_port>:13000
      </code>
      
      ), for secondary servers. Wolf reports them as <code>
        service_exposed
      </code>
      
      : Press relies on the server's firewall to keep them private
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Deploy correlation
    </td>
    
    <td>
      A <code>
        deployment
      </code>
      
       event for each deploy, update or migrate job in the Press agent's <code>
        jobs.sqlite3
      </code>
      
      , and an <code>
        error
      </code>
      
       event when one fails
    </td>
    
    <td>
      checked
    </td>
  </tr>
  
  <tr>
    <td>
      Site events
    </td>
    
    <td>
      The Wolf App on a Press bench names its bench and server as the agent does: the container's hostname is the bench (<code>
        docker run --hostname <bench>
      </code>
      
      ), and Press's <code>
        supervisor.conf
      </code>
      
       names the server (<code>
        <server>-gunicorn.access.log
      </code>
      
      , its name in Press). Registration names the agent's host the same way, from the Press agent's config, unless <code>
        --hostname
      </code>
      
       is given or the agent was registered before
    </td>
    
    <td>
      checked (the test server's hostname is its Press name)
    </td>
  </tr>
  
  <tr>
    <td>
      Fallback
    </td>
    
    <td>
      If <code>
        jobs.sqlite3
      </code>
      
       cannot be read, a <code>
        deployment
      </code>
      
       event when a new bench appears or a site moves to another bench
    </td>
    
    <td>
      done, unit tested
    </td>
  </tr>
</tbody>
</table>

The metrics themselves are described on [What is collected](/agent/collected).

## Server layout

### Press agent directory

Ansible clones the Press agent into `/home/frappe/agent/repo`, creates a venv at `/home/frappe/agent/env`, and runs `agent setup config` and `agent setup database` from `/home/frappe/agent`. `agent setup config` writes `config.json` with `benches_directory: /home/<user>/benches`, `nginx_directory: /home/<user>/agent/nginx`, `redis_port: 25025`, `web_port: 25052`, and other keys. Wolf detects Press through this file and its `benches_directory` key.

### Benches

Each bench is `<benches_directory>/<name>/` with `logs/`, `sites/`, `config/` and a bench `config.json`. Bench names follow the pattern `bench-<candidate>-<server>`. Wolf uses the directory name.

The apps live **inside the Docker image**. There is no `apps/frappe` on the host, so Wolf's generic check (`sites/` + `apps/frappe`) misses Press benches. A Press bench is identified by `config.json` with a `docker_image` key.

Bench config keys come from Press's `Bench` doctype: `docker_image`, `web_port` (18000 + offset), `socketio_port`, `rq_port` (11000 + offset), `rq_cache_port`, `single_container: true`, and others.

The bench containers bind-mount `<bench>/sites` and `<bench>/logs`, whether the bench runs as a single container or through `docker stack deploy`. The bench logs are ordinary files on the host. Wolf never runs `docker`.

### Sites and custom domains

Sites are `sites/<site>/` directories with a `site_config.json`. A site's custom domains are listed in its `site_config.json` under `domains`, and the bench nginx config maps them back to the site. Wolf reads the same key, so a 502 logged for `erp.customer.com` is counted against the right site.

### Logs

Inside the container, supervisor writes these files into `logs/`:

- `web.log`, `web.error.log`
- `schedule.log`, `schedule.error.log`
- `worker.log`, `worker.error.log`

Frappe's own loggers write `frappe.web.log`, `scheduler.log` and the other files there as on any bench. Wolf also tails `schedule.error.log` for tracebacks, on every bench. Where nothing writes it, the file is simply absent.

### Redis queue

`sites/common_site_config.json` holds the **in-container** address `redis://localhost:11000`. From the host, the queue Redis is reachable on the published `rq_port`, which is where the Press agent's own RQ exporter connects. Wolf uses `redis://127.0.0.1:<rq_port>`. When a bench has no `rq_port`, Wolf skips its queue metrics.

### nginx

The root `nginx.conf` is rendered to `/home/frappe/agent/nginx/nginx.conf`, symlinked to `/etc/nginx/nginx.conf`, and includes every `<benches_directory>/*/nginx.conf`. Every vhost uses one log:

```nginx
log_format main '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" "$http_x_forwarded_for" "$host" $request_time';
access_log /var/log/nginx/access.log main;
```

The site name, or a custom domain, is the last quoted field `"$host"`. Wolf's nginx parser reads trailing quoted fields, and Press mode adds the domain → site map. The bench templates set no per-bench `access_log`. Behind a Press proxy, `$remote_addr` is the proxy.

<tip>

Proxy servers (`n*` hosts) use the same root template but have no benches. To count 5xx there, add the log as an `extra_logs` entry:

```json [config.json]
{
  "extra_logs": [{"path": "/var/log/nginx/access.log", "parser": "nginx"}]
}
```

</tip>

## Deployment events

### Job history

Every Press agent job is stored in the SQLite database `jobs.sqlite3`, in the agent's working directory (`/home/frappe/agent`). It runs in WAL mode. Two tables matter:

- `jobmodel(id, name, status ∈ Pending/Running/Success/Failure, agent_job_id, data, enqueue, start, end, duration)`
- `stepmodel(id, name, job_id, status, data, start, end, duration)`

`agent_job_id` is the name of the **Agent Job** document in Press. Wolf copies it into the event payload, so you can open the same job in the Press dashboard.

At enqueue time, `data` is `{"function", "args", "kwargs"}`. When the job ends, it is overwritten with the result or `{"traceback": …}`. Step `data` keeps each step's command result, including the `docker exec … <bench> bench --site <site> …` command line.

Timestamps are naive server local time. Wolf converts them to UTC as local time.

### Jobs treated as deployments

<table>
<thead>
  <tr>
    <th>
      Press agent job
    </th>
    
    <th>
      Bench / site taken from
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      New Bench
    </td>
    
    <td>
      <code>
        args[0]
      </code>
      
       (bench)
    </td>
  </tr>
  
  <tr>
    <td>
      Update Site Pull, Update Site Migrate
    </td>
    
    <td>
      <code>
        args[0]
      </code>
      
       site, <code>
        args[2]
      </code>
      
       target bench
    </td>
  </tr>
  
  <tr>
    <td>
      Recover Failed Site Migrate, Recover Failed Site Pull, Move Site to Bench
    </td>
    
    <td>
      <code>
        args[0]
      </code>
      
       site, <code>
        args[2]
      </code>
      
       target bench
    </td>
  </tr>
  
  <tr>
    <td>
      Recover Failed Site Update
    </td>
    
    <td>
      <code>
        args[0]
      </code>
      
       site, <code>
        args[1]
      </code>
      
       bench
    </td>
  </tr>
  
  <tr>
    <td>
      Update Bench In Place
    </td>
    
    <td>
      <code>
        args[0]
      </code>
      
       sites; bench from steps
    </td>
  </tr>
  
  <tr>
    <td>
      Patch App, Bench Restart, Rebuild Bench Assets
    </td>
    
    <td>
      steps
    </td>
  </tr>
  
  <tr>
    <td>
      Migrate Site, Install App on Site, Uninstall App on Site
    </td>
    
    <td>
      steps
    </td>
  </tr>
</tbody>
</table>

`Bench` and `Site` methods carry no bench or site name in their arguments. For those jobs, Wolf searches the job and step `data` for a known bench name and for `--site <name>`.

### How events are produced

- **Read-only access.** Wolf opens `jobs.sqlite3` with `file:…?mode=ro`, which needs the agent's `-wal` and `-shm` files to be readable. If that fails, it retries with `immutable=1`. Wolf never writes to the database.
- **One deployment event per job**, sent as soon as the job has started. Its timestamp is the job's `start`, so the "502 spike after deployment" [preset](/alerts/presets) links incidents that happen during a long migrate. If the bench cannot be determined yet, the event waits up to 2 minutes for a step to name it, then ships host-scoped. Incident correlation also matches host-scoped deployments. Fields: `category: "press"`, `source: "press-agent"`, and `payload.press_job`, `agent_job_id`, `local_job_id`, `sites`.
- **One error event** (`category: "press_job_failed"`, warning) when such a job ends in `Failure`. Its payload holds the failed step names and the tail of the traceback or output.
- **Deduplication.** Emitted job ids and a floor id are saved in `<spool_dir>/press-jobs.json`, so restarts never emit an event twice. On the first run, history is skipped and only jobs still Pending or Running are picked up. A job stuck in Pending or Running for more than 24 h (for example, a crashed RQ worker) is dropped, so it cannot block progress.
- **Fallback without database access.** `<spool_dir>/press-benches.json` keeps a bench → site snapshot. A new bench directory, or a site whose directory moved to another bench, produces a `deployment` event stamped with the time it was noticed.

Rediscovery rebuilds the log sources when the set of benches or sites changes. Logs of a bench created while Wolf runs are read from the start, because they are new files. A moved site's logs move with its directory, so they are read from the end to avoid replaying them.

Event fields are described in the [protocol](/reference/protocol).

## Wolf next to Press's own monitoring

Press already ships a monitoring stack. Wolf does not replace it and does not touch it.

- **Monitor server** (`monitor.yml`): Prometheus, Alertmanager, Blackbox exporter and Grafana. Prometheus probes sites, domains and TLS with blackbox `http_2xx` and scrapes the Press-managed servers. Press pushes alert rules and routes to it through the agent's `Monitor` class, from Press doctypes such as *Prometheus Alert Rule*. The Alertmanager webhook lands in *Alertmanager Webhook Log*. Press's *Incident* doctype escalates outages by phone (Twilio) to Frappe staff and customers.
- **App servers** (`server.yml`): node_exporter, cAdvisor, statsd_exporter (the bench config sets `statsd_host`), filebeat and fail2ban, among other roles. Filebeat ships `/var/log/*.log`, the nginx module and each bench's `logs/monitor.json.log` to a central Elasticsearch/Kibana log server. The Press agent also moves `monitor.json.log` aside for Press's analytics. Wolf does not tail that file.
- The Press agent exposes RQ metrics per bench at `/benches/metrics`.

What Wolf adds on a self-hosted Press install:

- Frappe-level tracebacks, failed scheduled jobs and worker crashes read from bench logs.
- 5xx/502 per site.
- SSH signals.
- Incidents correlated with the Press job that caused them.

All of it lives on your own Wolf site, without access to the Press monitor server.

The two stacks overlap on host metrics (node_exporter vs Wolf's `/proc` sampling) and on queue lengths. Wolf's are light. Turn host metrics off with `collect_host_metrics: false`.

## Limitations and unverified points

### Limitations

- Only app servers with benches are supported directly. Proxy and database servers have no bench: add their logs through `extra_logs`.
- When a job ends, the Press agent replaces its arguments with its result. A job Wolf first sees finished takes the bench its last step ran in (a site move ends on its target) and the site from `--site` in a step command. A job without any such step is reported host-scoped.
- The filesystem fallback cannot tell a deploy from a manual move, and it has no failure signal.
- A bench found after registration shows the image it was created with (its `docker-compose.yml`): Update Bench In Place changes only its `0600` config.
- Jobs are matched by display name. If Press renames a job, it is no longer recognised. Add the new name to `DEPLOY_JOBS` in [`agent/wolf_agent/press.py`](https://github.com/bthuner/dodock-wolf/blob/main/agent/wolf_agent/press.py).
- Shared-FS benches (`Run Benches on Shared FS`) change `benches_directory`. Wolf rereads it from the Press agent config on every rediscovery, but this path has not been tested.
- Whether local backup copies stay in `sites/<site>/private/backups` has not been checked, which is why backups are off by default.

### Checked on a Press server

1. **Modes.** `jobs.sqlite3` and its `-wal` and `-shm` files are `0644`, and `mode=ro` works for a member of the `frappe` group. The configs are `0600`: see [Permissions](#permissions).
2. **Job data.** Job names match `DEPLOY_JOBS`. A finished job's `data` is `null`, and its steps keep their command and `directory`, for example `docker exec … bench-0001-000002-f1 bench --site <site> migrate` for a migrate.
3. **$host.** Every site request carries the site in `"$host"`. The Press agent's own vhost on 443 logs the server's name there, which is no site: Wolf leaves those lines out.
4. **rq_port.** Press sets it on every new bench and publishes it. A bench whose config has none (an older one) gets no queue metrics: the daemon keeps what registration read in it rather than derive a port from the web port.

Not checked: a site behind a Press proxy server (here requests reach the app server directly), shared-FS benches, and local backup copies.

<collapsible>

Sources were read at frappe/agent [`64b9812`](https://github.com/frappe/agent/tree/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a) (2026-10-27) and frappe/press [`aedd7d1`](https://github.com/frappe/press/tree/aedd7d1237e49153e4852a7ca693b3a50c6028b2) (2026-10-29). Every link is pinned to these commits. The full write-up is [`docs/press.md`](https://github.com/bthuner/dodock-wolf/blob/main/docs/press.md).

**Press agent directory and config**

- Agent install: [`press/playbooks/roles/agent/tasks/main.yml#L1-L33`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/agent/tasks/main.yml#L1-L33)
- `agent setup config`: [`agent/cli.py#L70-L101`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/cli.py#L70-L101); keys read by `Server`: [`agent/server.py#L70-L79`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L70-L79)
- `/home/frappe/benches` created by [`press/playbooks/roles/bench/tasks/main.yml#L1-L7`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/bench/tasks/main.yml#L1-L7)

**Benches and sites**

- `Server.bench_init`: [`agent/server.py#L116-L148`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L116-L148)
- `Server.benches`: [`agent/server.py#L889-L894`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L889-L894); `Bench` requirements: [`agent/bench.py#L45-L69`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L45-L69)
- Bench names: [`press/press/doctype/bench/bench.py#L222-L236`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/press/doctype/bench/bench.py#L222-L236); bench config keys: [`#L347-L384`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/press/doctype/bench/bench.py#L347-L384)
- `Bench.start` (single container, `-p 0.0.0.0:<rq_port>:11000`): [`agent/bench.py#L839-L882`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L839-L882); stack deploy template: [`agent/templates/bench/docker-compose.yml.jinja2`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/bench/docker-compose.yml.jinja2)
- Custom domains: [`agent/bench.py#L1442-L1447`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L1442-L1447), [`agent/templates/bench/nginx.conf.jinja2#L9-L15`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/bench/nginx.conf.jinja2#L9-L15)
- Supervisor log files: [`agent/build_configs/config/supervisor.conf#L7-L29`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/build_configs/config/supervisor.conf#L7-L29)

**Redis and nginx**

- In-container Redis address: [`agent/build_configs/common_site_config.json#L1-L9`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/build_configs/common_site_config.json#L1-L9)
- RQ exporter (`/benches/metrics`): [`agent/web.py#L405-L431`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/web.py#L405-L431), [`agent/exporter.py#L8-L11`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/exporter.py#L8-L11)
- Root nginx config: [`agent/server.py#L1229-L1244`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L1229-L1244), symlink: [`press/playbooks/roles/agent/tasks/main.yml#L85-L97`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/agent/tasks/main.yml#L85-L97)
- `log_format main`: [`agent/templates/nginx/nginx.conf.jinja2#L45-L48`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/nginx/nginx.conf.jinja2#L45-L48); `set_real_ip_from` at L59-L62 of the same file
- Bench nginx template: [`agent/templates/bench/nginx.conf.jinja2`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/bench/nginx.conf.jinja2)

**Job history**

- `jobs.sqlite3` and WAL mode: [`agent/job.py#L45-L54`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L45-L54), [`agent/templates/agent/supervisor.conf.jinja2#L1-L36`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/templates/agent/supervisor.conf.jinja2#L1-L36)
- Peewee models: [`agent/job.py#L301-L344`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L301-L344), created by `agent setup database`: [`agent/cli.py#L171-L175`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/cli.py#L171-L175)
- `X-Agent-Job-Id`: [`press/agent.py#L960-L966`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/agent.py#L960-L966)
- Job `data` at enqueue: [`agent/job.py#L124-L138`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L124-L138); overwritten at the end: [`#L78-L91`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/job.py#L78-L91)
- Step command lines: [`agent/base.py#L65-L111`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/base.py#L65-L111), [`agent/bench.py#L177-L200`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L177-L200), [`agent/site.py#L61-L62`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/site.py#L61-L62)

**Jobs treated as deployments**

- New Bench: [`agent/server.py#L157-L174`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L157-L174)
- Update Site Pull / Migrate: [`agent/server.py#L558-L600`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L558-L600)
- Recover Failed Site Migrate / Pull, Move Site to Bench: [`agent/server.py#L658-L705`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L658-L705)
- Recover Failed Site Update: [`agent/server.py#L729-L733`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L729-L733)
- `Server.move_site`: [`agent/server.py#L735-L750`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L735-L750)
- Update Bench In Place: [`agent/bench.py#L1086-L1092`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L1086-L1092)
- Patch App, Bench Restart, Rebuild Bench Assets: [`agent/bench.py#L592-L602`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L592-L602), [`#L1026-L1032`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L1026-L1032)
- Migrate Site, Install / Uninstall App on Site: [`agent/site.py#L282-L322`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/site.py#L282-L322)
- Shared-FS benches: [`agent/server.py#L312-L370`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/server.py#L312-L370)
- Host-scoped deployment matching: `scope_clause` in [`dodock_wolf/wolf/events.py`](https://github.com/bthuner/dodock-wolf/blob/main/dodock_wolf/wolf/events.py)

**Press monitoring**

- [`press/playbooks/monitor.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/monitor.yml), [`press/playbooks/roles/prometheus/templates/prometheus.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/prometheus/templates/prometheus.yml)
- `Monitor` class: [`agent/monitor.py#L11-L40`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/monitor.py#L11-L40)
- Incident doctype: [`press/press/doctype/incident/incident.py`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/press/doctype/incident/incident.py)
- [`press/playbooks/server.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/server.yml), filebeat inputs: [`monitor.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/filebeat/templates/inputs.d/monitor.yml), [`nginx.yml`](https://github.com/frappe/press/blob/aedd7d1237e49153e4852a7ca693b3a50c6028b2/press/playbooks/roles/filebeat/templates/modules.d/nginx.yml)
- `Bench.fetch_monitor_data`: [`agent/bench.py#L300-L330`](https://github.com/frappe/agent/blob/64b9812a8e4dc82188d3cbf3053dd4f2eb5f4f4a/agent/bench.py#L300-L330)

</collapsible>
