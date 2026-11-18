# Wolf on Pilot benches

User documentation: [docs-site `2.install/5.pilot.md`](../docs-site/content/en/2.install/5.pilot.md)
(the site's *Pilot benches* page). This file records what was checked and against which Pilot.

## Checked on a live host

[Frappe Pilot](https://github.com/frappe/pilot) **v1.0.0-rc.1**
([`30c876a`](https://github.com/frappe/pilot/tree/30c876a0f5bcb506158b78ea25b4f4f0fed93737)),
installed with its own `install.sh` on Debian 12, in production mode (`pilot setup production`:
systemd user units, nginx, the Admin), with a Frappe `version-16` bench and a site running the
Wolf App, and the Wolf agent installed with `agent/install.sh`. `dev/pilot/` sets this host up
in a container (see its README).

| What | Seen | Wolf |
|---|---|---|
| `bench.toml`, `tasks/`, `sites/*/site_config.json`, `common_site_config.json` | mode `0600` / `0700`, owned by the bench user | the agent stays `wolf-agent`, out of the bench's reach; `wolf-pilot-export` (root, a timer every 20 s) copies the tasks (site argument only) and unit states to `/var/lib/wolf-pilot-export/<bench>.json`, `root:wolf-agent 0640`; registration (root) reads `bench.toml` and the site configs once |
| Processes | systemd **user** units of the bench user: `<bench>-web`, `-redis_cache`, `-redis_queue`, `-admin` (+ `.socket`), app processes; `pilot-mariadb`, `pilot-monitor` | from the export (root lists them with `systemctl --user -M <user>@`); a socket-activated `inactive` Admin is not down |
| Lite mode (default) | one `web` process (`frappe.runner`) serves requests, workers and the scheduler; logs in `logs/web.log.error.log` | tailed as before |
| Sandbox (default for a new systemd bench) | Frappe's own logs in `logs/workload/`; needs unprivileged user namespaces, refused by Ubuntu 24.04's AppArmor default, then `pilot setup production` fails and advises `sandbox = false` | `logs/workload/` tailed (unit tested; this host ran without the sandbox for that reason) |
| nginx | `logs/nginx-access.log`, `pilot_access`: `$pilot_client_addr [$time_local] "$request_method $uri" $status "$host" $request_time` | parsed as before; no query string and no User-Agent, so no query-string injections and no scanner User-Agents from this log (documented) |
| Tasks | `tasks/<id>/meta.json` + `status`, as before; a migrate run from the Admin API gave `command: migrate`, `args: {operation_id, site}` | the files when readable, else the export, the Admin API last: a minted token would show among Pilot's active sessions |
| Admin API | `127.0.0.1:<admin.port + 1>` (7001); tokens HS256 with `[admin] jwt_secret`, written at the Admin's first session; bench management (restart…) off by default | fallback only |
| MariaDB | Pilot's own, a user unit on `127.0.0.1:3310` | not checked on Pilot: the site's password stays the bench user's |
| App install | `get-app` refuses an app whose `hooks.py` `required_apps` lists `frappe` (implicit) | `dodock_wolf` no longer lists it |

## What Pilot would need

1. An "enable Wolf for this bench" toggle: a `[wolf]` table in `bench.toml` and an Admin switch
   that installs and registers the agent.
2. A read-only machine token for the Admin API (`tasks:read`, unit states), which would make the
   root helper unnecessary.
3. The query string and User-Agent in `pilot_access`.
