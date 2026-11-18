# Frappe Pilot test host

A real [Frappe Pilot](https://github.com/frappe/pilot) host in a container, in production mode,
with a Wolf site on its bench and the Wolf agent installed by `agent/install.sh`: the bench.toml,
systemd user units, logs and tasks that Wolf reads on Pilot.

```bash
docker compose up -d --build   # a Debian host with systemd as PID 1 (privileged container)
./setup.sh                     # ~15 minutes the first time; each step is skipped once done
```

`setup.sh`:

1. runs Pilot's `install.sh` twice, as root (packages, the `frappe` bench user) and as `frappe`;
2. `pilot new wolf` and `pilot init` (Frappe `version-16`);
3. `pilot get-app` of a snapshot of this checkout, `pilot new-site wolf.localhost`,
   `pilot install-app wolf.localhost dodock_wolf`;
4. `pilot setup production --admin-domain admin.localhost`. When the host refuses Pilot's sandbox
   (unprivileged user namespaces, refused by Ubuntu 24.04's AppArmor default, which a container
   shares with its host), it sets `sandbox = false`, as Pilot advises;
5. `agent/install.sh` with the site's registration token: the agent runs as `wolf-agent`, and the
   installer adds `wolf-pilot-export`, the root timer that copies the bench's task and unit states
   to `/var/lib/wolf-pilot-export/`.

| Variable | Default |
|---|---|
| `WOLF_PILOT_HTTP` | `8380`: nginx's port on the machine (`curl -H 'Host: wolf.localhost' localhost:8380`) |
| `WOLF_PILOT_BENCH`, `WOLF_PILOT_SITE` | `wolf`, `wolf.localhost` |
| `WOLF_PILOT_FRAPPE_BRANCH` | `version-16` |
| `WOLF_PILOT_REF` | the latest Pilot release; a tag such as `v1.0.0-rc.1` pins one |
| `WOLF_PILOT_ADMIN_PASSWORD` | `Wolf-pilot-1` (Pilot wants 8+ characters, mixed case, a digit and a symbol) |
| `WOLF_PILOT_ADMIN_DOMAIN` | `admin.localhost` |

Inside the host:

```bash
docker compose exec -u frappe -e USER=frappe -e XDG_RUNTIME_DIR=/run/user/1000 pilot bash -l
pilot -b wolf processes ls
systemctl --user list-units 'wolf-*'
journalctl -u wolf-agent -f      # as root: the Wolf agent
cat /var/lib/wolf-pilot-export/wolf.json   # as root: what wolf-pilot-export copied
```

A Pilot task, as the Admin runs it (a deployment event on the Wolf site):

```bash
docker compose exec pilot bash -c 'A=http://127.0.0.1:7001/api/v1
curl -s -c /tmp/j -H "Content-Type: application/json" -d "{\"password\":\"Wolf-pilot-1\"}" $A/auth/session
curl -s -b /tmp/j -X POST -H "Content-Type: application/json" -d "{}" $A/sites/wolf.localhost/actions/migrate'
```

Commands run in the container need `USER` and `LOGNAME` set, as a login sets them:
`mariadb-install-db` gives the database's socket login to `$USER`, which `docker exec` leaves
empty.

Reset: `docker compose down -v`.
