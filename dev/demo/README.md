# Local demo: the 2AM scenario from CLAUDE.md

One Dokos bench with `dodock_wolf` on the site `wolf.localhost`, plus:

- an nginx front that logs the site name;
- the Wolf agent, tailing the bench and nginx logs and Redis;
- a webhook sink that prints every alert.

Everything runs locally; nothing leaves your machine.

```bash
cd dev/demo
# Any Dokos image works as base; reusing a local one avoids a multi-GB pull.
WOLF_DEMO_BASE=registry.gitlab.com/dokos/dokos:latest docker compose up -d --build
docker compose logs -f agent          # wait for "wolf-agent 0.1.0 started"
python3 scenario.py                   # ~5 minutes
docker compose logs catcher           # the alerts Wolf sent
```

Wolf UI: <http://localhost:8099/wolf>, login `Administrator` / `admin`; Desk:
<http://localhost:8099/app/wolf-overview>. The Wolf UI says **Live** when Frappe's socket.io
server accepted it: `nginx.conf` rewrites `Host` and `Origin` for `/socket.io`, because that
server checks they match and calls the site back at `Origin` (here `frontend:8080`).

## What `scenario.py` does

1. Keeps the site time zone if it is already night there; otherwise switches to a real zone
   where it is between 01:00 and 04:00 (e.g. Asia/Shanghai). This moves the site clock "into
   the night" without faking the system clock. It picks a zone ahead of the current one when
   one is at night, so stored rows stay in the past. An empty time zone counts as Frappe's
   fallback, Asia/Kolkata: `create-site` skips the setup wizard, so a fresh site has none. When
   no zone ahead is at night, it moves back the least. Either way it then marks every Scheduled
   Job Type whose last run is in the future as just run: otherwise Frappe's scheduler, Wolf's
   rule evaluation included, finds no job due for hours (see Setup wizard below).
2. Adds a webhook channel (`http://catcher:9999/`) to the 502 and scheduler preset rules.
3. Marks a deployment with `wolf-agent mark-deployment`.
4. Stops the backend for 60 s while sending traffic, so nginx answers 502. nginx resolves
   `backend` at each request: a stopped container no longer resolves, so each request gets its
   502 at once, as from a bench whose gunicorn is down.
5. Starts the backend again and reloads nginx.
6. Adds a Server Script scheduled job that fails every minute ("Nightly ledger sync"), lets it
   fail, then disables it.
7. Prints the incidents.

Expected:

- **502 spike after deployment**: critical, linked to the deployment of step 3 (the migrate
  of step 5 comes after the 502s began, so it is not the preceding change). **5xx spike**
  opens too, from the same responses.
- **Nightly cron failure (01:00-04:00)**: critical. It is reported by the site itself, through
  Wolf's `Scheduled Job Type` override. The agent's `scheduler.log` parser stays quiet here:
  Frappe logs "Scheduled Job Failed" at INFO, below the default logger level.
- One webhook per new incident.

Presets like **Disk almost full** may fire too, because the agent measures the machine
running Docker. **Security score low** (a fresh site without two-factor authentication) and
**Server Script can run new code** (step 6 adds one) are real findings on the demo site. **Agent silent** fires once as an artefact of step 1: `last_seen` was stored
in the old time zone, so the agent looks hours stale for one check.

![Incident timeline after the scenario](incident-timeline.jpg)

## Live demos

Three profiles add a simulated server each, watched by an agent of its own through the real code
path for its platform. They can run together, next to the 2AM scenario:

```bash
WOLF_DEMO_BASE=registry.gitlab.com/dokos/dokos:latest docker compose --profile press --profile multi --profile single up -d --build
docker compose --profile multi logs -f multi-demo   # "history written up to ...", then live
docker compose logs catcher                         # the alerts
```

| Profile | Host | Server | Deployments |
|---|---|---|---|
| `press` | `f1-demo-press` | Press app server: 3 benches, 8 sites, `jobs.sqlite3`, nginx `main` format | Press jobs |
| `multi` | `dokos-multi-1` | plain benches: 2 benches, 6 sites, nginx with `$host` first | deployment endpoint |
| `single` | `dokos-single-1` | one bench, one site | deployment endpoint |

- `<kind>-agent` runs `demo-agent-init.sh <kind> <host>`: it registers the host without benches
  (`--bench` names the empty demo root), then `wolf-agent demo <kind> --configure` points it at the
  `demo-<kind>` volume with the checks that have nothing behind them off (TLS, MariaDB, backups...).
- `<kind>-demo` runs `bench --site wolf.localhost generate-demo-<kind> --webhook http://catcher:9999/`.
  It lays out the server with empty logs, waits until the agent tracks them, writes 7 days of
  history (the agent reads it from the start; past host metrics go through its spool), then live
  traffic with an incident cycle every 30 minutes: a deployment and 4 minutes of 502s, a traceback,
  a failed scheduled job, a killed worker, an SSH brute force, a web attack scan and, every other
  cycle, a failed bench operation. The code is in `agent/wolf_agent/demo/`.
- Incidents open for live cycles only: rules look at the last minutes. Restarting `<kind>-demo`
  fills the gap since it stopped, then goes live again.
- Reset one demo: `docker compose --profile <kind> rm -sf <kind>-agent <kind>-demo &&
  docker volume rm wolfdemo_demo-<kind>`. Its host and data stay on the site until the full reset,
  which needs every profile: `docker compose --profile press --profile multi --profile single down -v`.

## Suricata and Wazuh

The `ids` profile runs a real Suricata and a real Wazuh manager next to the bench, and
`ids_scenario.py` sends one attacker at it: nginx, Suricata and Wazuh each see the attack, and Wolf
puts the three in one incident.

```bash
docker compose --profile ids up -d --build   # Suricata pulls ET Open on its first start
python3 ids_scenario.py                      # a few minutes: Suricata's rules, Wazuh's first alert
```

- `suricata` (`jasonish/suricata:7.0`) shares the frontend's network and sniffs its interface, with
  ET Open (kept in the `suricata-rules` volume). It writes `eve.json` to the `suricata-logs` volume,
  which the bench's agent mounts at `/var/log/suricata`: the agent finds it by itself.
- `wazuh-manager` (`wazuh/wazuh-manager:4.9.2`, without indexer or dashboard) reads the attacker
  port's log in the standard `combined` format (`wazuh-wolf.sh` adds it to `ossec.conf`).
- `wazuh-wolf-agent` is the Wolf agent on the manager's host (`wazuh-agent-init.sh`): it reads
  `alerts.json` and nothing else, in the `wazuh` group as on a real manager.
- The client address. Wolf groups by public address only, and every address inside Docker is
  private. So the attacks come from inside the stack (the `catcher` container) to nginx's port
  8081, which is not published. There, as behind a load balancer, `X-Forwarded-For` names the
  client, and Suricata reads it too (`xff` in `compose.yaml`): the scenario attacks as
  `45.33.32.156` (scanme.nmap.org). Port 8080 (the site, published as 8099) trusts no header.
  Demo only: never trust `X-Forwarded-For` from clients who can set it.
- Suricata listens to the frontend's ports only, so nginx's calls to the backend do not count each
  attack twice, with `EXTERNAL_NET` set to `any`: in Docker the attacker's address is private too.
- The scenario waits for Suricata's rules and Wazuh's first alert, restarts the two agents so they
  read `eve.json` and `alerts.json` at once (they re-check every 5 minutes otherwise), turns on and
  routes the IDS and HIDS presets, sends log4j, Shellshock, sqlmap, the Fortinet VPN traversal and
  secret file probes, then prints the events of each detector and the incident that holds them.
- `scenario.py` (the 2AM scenario) reloads nginx instead of restarting the frontend: Suricata
  shares the frontend's network and would be left on an interface that no longer exists.
- Another port: `WOLF_DEMO_URL=http://localhost:8199 python3 ids_scenario.py`, with the
  frontend's port changed in a compose override.

## Setup wizard

`create-site` marks setup as complete, so Desk opens directly. To go through Dodock's wizard
instead (language, country, time zone, currency, first user), reset the flags and open
<http://localhost:8099/app>:

```bash
docker compose exec backend bash -c "cd ~/frappe-bench && \
  bench --site wolf.localhost execute frappe.db.set_single_value --args '[\"System Settings\", \"setup_complete\", 0]' && \
  bench --site wolf.localhost execute frappe.db.set_value --args '[\"Installed Application\", {\"app_name\": \"frappe\"}, \"is_setup_complete\", 0]' && \
  bench --site wolf.localhost execute frappe.db.set_default --args '[\"desktop:home_page\", \"setup-wizard\"]' && \
  bench --site wolf.localhost clear-cache"
```

Two things to watch:

- **Browser autofill.** Chrome may fill and submit the account step with your own name,
  email and saved password. Turn autofill off for localhost, or check the fields before the
  wizard moves on.
- **Time zone.** The wizard replaces the time zone that `scenario.py` set. Rows recorded
  under the night zone are then stamped hours in the future and skew rule windows until real
  time catches up. Frappe's own scheduler stalls the same way: every Scheduled Job Type's
  `last_execution` is in the future, so no job is due. Delete the future rows and set those
  `last_execution` values to now, or reset the stack.

## Email and Raven channels

```bash
WOLF_DEMO_RAVEN=1 docker compose up -d --build     # adds Raven (backend only) to the image
docker compose exec backend bench --site wolf.localhost install-app raven
python3 channels.py
```

`channels.py` sets up the following on the **Scheduler failure** rule, then makes a job fail:

- an outgoing Email Account pointed at Mailpit;
- a Raven workspace and a `wolf-alerts` channel;
- Email, Raven and Webhook channels on the rule.

Mail shows up at <http://localhost:8025> within one email-queue flush, a few minutes at most.
Raven is installed without `blurhash-python`, which has no Python 3.14 wheel; that only
affects image previews.

## Database portability check

[`ci/db_smoke.py`](../../ci/db_smoke.py) (mounted at `/etc/wolf/db_smoke.py`, also run by CI) runs every Wolf SQL path on a site: ingest, dedupe, all rule kinds, correlation,
timeline, charts, purge and auto-resolve. It works the same on MariaDB and on Postgres:

```bash
docker compose exec backend bash -c 'cd sites && ../env/bin/python /etc/wolf/db_smoke.py wolf.localhost'
WOLF_DEMO_PG_IMAGE=postgres:16 docker compose --profile postgres up -d pgdb
docker compose exec backend bench new-site pg.localhost --db-type postgres --db-host pgdb \
  --db-root-username postgres --db-root-password admin --admin-password admin --install-app dodock_wolf
docker compose exec backend bash -c 'cd sites && ../env/bin/python /etc/wolf/db_smoke.py pg.localhost'
```

Reset: `docker compose --profile press --profile multi --profile single down -v` (the profiles you used, so their containers and volumes go too).
