# Press app server with Wolf

A Press app server as Press builds one, to check what Wolf reads on it
(docs/press.md, docs-site `install/press`):

- **`server`**: Ubuntu 22.04 with systemd, provisioned by **Press's own Ansible roles**
  (frappe/press, pinned): the `frappe` user, nginx with the VTS module, the **Press agent**
  (frappe/agent, pinned) under supervisor with its `jobs.sqlite3`, and Docker running the benches.
- **`db`**: MariaDB 10.6, Press's database server, at its private address `172.30.80.10`.
- A **bench** created through the Press agent's HTTP API, as Press creates one (`New Bench`), from a
  Press-style image in a registry on the server, and a **site** with the Wolf App (`New Site`).
- The **Wolf agent** on the server, installed with `agent/install.sh` from this checkout and
  registered with that site.

```bash
cd dev/press
docker compose up -d --build
./setup.sh        # 20-30 min the first time; each step is skipped when already done
```

Site: <http://wolf.localhost:8480> (`Administrator` / `admin`; `WOLF_PRESS_HTTP` changes the port).

## What is real and what is not

| Part | Here |
|---|---|
| Server layout, users, groups, modes | Press's roles `essentials`, `user`, `nginx`, `agent`, `bench`, `docker` and `statsd_exporter` (the benches' gunicorn sends it metrics) from `press/playbooks/server.yml`. Hardening, other exporters, backups and volume mounts are left out |
| Press agent | frappe/agent at the pinned commit: `agent setup config/database/nginx/supervisor`, gunicorn and RQ workers under supervisor, its nginx vhost on 443 |
| Jobs | Real Press agent jobs, called over `https://<server>/agent/` with the bearer password and an `X-Agent-Job-Id`, as `press/agent.py` does (`press_api.py`) |
| Bench image | `frappe/erpnext:v16.5.0` (frappe_docker), finished as Press's image template finishes one: supervisord as the command, Press's `supervisord.conf`, Redis configs and `common_site_config.json`, plus dodock_wolf. Press renders its own Dockerfile per deploy; what Wolf reads is on the host |
| Proxy | None: the site is served on port 80 as on an app server behind Press's proxy, but requests come straight from the client |

## Press agent jobs

`press-api` on the server sends any Press agent job and waits for it:

```bash
docker compose exec server press-api jobs
docker compose exec server press-api job "Migrate Site" benches/bench-0001-000001-f1-press/sites/wolf.localhost/migrate '{"skip_failing_patches": false, "activate": true}'
docker compose exec server press-api job "Bench Restart" benches/bench-0001-000001-f1-press/restart '{"web_only": false}'
docker compose exec server press-api new-bench bench-0001-000002-f1-press 1   # a second bench, port offset 1
docker compose exec server press-api job "Update Site Migrate" benches/bench-0001-000001-f1-press/sites/wolf.localhost/update/migrate \
  '{"target": "bench-0001-000002-f1-press", "activate": true, "skip_failing_patches": false, "skip_backups": true, "before_migrate_scripts": null, "skip_search_index": true}'
```

`setup.sh` finds the site on whichever bench serves it, so it can run again after a deploy moved
it, and upgrades the Wolf agent in place from this checkout (its config kept, as on a real host).

## Reset

`docker compose down -v` removes the server, its Docker volume (benches, images) and the database.
