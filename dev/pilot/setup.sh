#!/usr/bin/env bash
# Set up Frappe Pilot in production mode with Wolf, inside the `pilot` container (dev/pilot/README.md).
# Run from dev/pilot:  docker compose up -d --build && ./setup.sh
# Each step is skipped when already done, so it can be run again after a failure.
set -euo pipefail
cd "$(dirname "$0")"

BENCH="${WOLF_PILOT_BENCH:-wolf}"
SITE="${WOLF_PILOT_SITE:-wolf.localhost}"
BRANCH="${WOLF_PILOT_FRAPPE_BRANCH:-version-16}"
PILOT_REF="${WOLF_PILOT_REF:-}"  # a Pilot release tag (v1.0.0-rc.1...); empty: the latest release
# Pilot's Admin wants 8+ characters with upper and lower case, a digit and a symbol
ADMIN_PASSWORD="${WOLF_PILOT_ADMIN_PASSWORD:-Wolf-pilot-1}"

# Pilot's installer, pinned with the release when WOLF_PILOT_REF names one
INSTALL_URL="https://raw.githubusercontent.com/frappe/pilot/${PILOT_REF:-develop}/install.sh"
root() { docker compose exec -T pilot bash -c "$1"; }
# a login shell of the bench user, as an operator would type: Pilot's PATH and the user's systemd
# (USER and LOGNAME too, as a login sets them: mariadb-install-db grants socket access to $USER)
as_frappe() {
	docker compose exec -T -u frappe -w /home/frappe -e USER=frappe -e LOGNAME=frappe -e HOME=/home/frappe \
		-e "XDG_RUNTIME_DIR=/run/user/$FRAPPE_UID" pilot bash -lc "$1"
}
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "systemd is up"
for _ in $(seq 60); do
	root 'systemctl is-system-running 2>/dev/null | grep -qE "running|degraded"' && break
	sleep 2
done
root 'systemctl is-system-running 2>/dev/null | grep -qE "running|degraded"' || { echo "systemd did not start in the container" >&2; exit 1; }

step "Pilot install.sh, root pass: packages and the bench user"
root "id frappe >/dev/null 2>&1 || curl -fsSL $INSTALL_URL | sh"
FRAPPE_UID=$(root 'id -u frappe' | tr -d '[:space:]')
# the bench's units are systemd user units: they run without a login session
root "loginctl enable-linger frappe && until [ -d /run/user/$FRAPPE_UID ]; do sleep 1; done"

step "Pilot install.sh, bench user pass"
as_frappe "[ -x ~/pilot/bin/pilot ] || curl -fsSL $INSTALL_URL | sh -s -- ${PILOT_REF:+--version $PILOT_REF}"
as_frappe 'pilot --version 2>/dev/null || ~/pilot/bin/pilot --version'

step "Bench $BENCH ($BRANCH)"
as_frappe "[ -f ~/pilot/benches/$BENCH/bench.toml ] || pilot new $BENCH --frappe-branch $BRANCH --admin-password '$ADMIN_PASSWORD'"
as_frappe "[ -d ~/pilot/benches/$BENCH/apps/frappe ] || pilot -b $BENCH init --no-dev"

step "dodock_wolf from this checkout (a snapshot: Pilot clones apps from git)"
as_frappe "rm -rf /tmp/dodock_wolf && mkdir /tmp/dodock_wolf && tar -C /src --exclude .git --exclude node_modules \
  --exclude docs-site --exclude dev -cf - . | tar -C /tmp/dodock_wolf -xf - && cd /tmp/dodock_wolf && git init -q -b main \
  && git add -A && git -c user.email=wolf@localhost -c user.name=wolf commit -qm snapshot"
as_frappe "[ -d ~/pilot/benches/$BENCH/apps/dodock_wolf ] || pilot -b $BENCH get-app file:///tmp/dodock_wolf --branch main"

step "Site $SITE with dodock_wolf"
as_frappe "[ -d ~/pilot/benches/$BENCH/sites/$SITE ] || pilot -b $BENCH new-site $SITE --admin-password admin"
as_frappe "pilot -b $BENCH frappe --site $SITE list-apps 2>/dev/null | grep -q dodock_wolf || pilot -b $BENCH install-app $SITE dodock_wolf"

step "Production: systemd user units, nginx, the Admin"
production="pilot -b $BENCH setup production --admin-domain ${WOLF_PILOT_ADMIN_DOMAIN:-admin.localhost}"
if ! out=$(as_frappe "$production" 2>&1); then
	echo "$out"
	# Pilot's sandbox needs unprivileged user namespaces, which a host with AppArmor's
	# restriction (Ubuntu 24.04's default) refuses: run the bench without it, as Pilot advises
	grep -q "cannot run sandboxed units" <<<"$out" || exit 1
	echo "The host refuses the sandbox: production without it (sandbox = false)"
	as_frappe "pilot -b $BENCH set-bench-config production_sandbox false"
	as_frappe "$production"
else
	echo "$out"
fi
as_frappe "pilot -b $BENCH processes ls"

step "The Wolf agent, with agent/install.sh from this checkout"
# the site's name resolves here, as a real one would through DNS
root "grep -q ' $SITE' /etc/hosts || echo '127.0.0.1 $SITE ${WOLF_PILOT_ADMIN_DOMAIN:-admin.localhost}' >> /etc/hosts"
token=$(as_frappe "pilot -b $BENCH frappe --site $SITE execute frappe.utils.password.get_decrypted_password \
  --args '[\"Wolf Settings\", \"Wolf Settings\", \"registration_token\"]'" | tail -1 | tr -d '"[:space:]')
root "apt-get install -y -qq python3-venv >/dev/null && rm -rf /tmp/wolf-agent-src && cp -r /src/agent /tmp/wolf-agent-src \
  && WOLF_AGENT_SRC=/tmp/wolf-agent-src WOLF_URL=http://$SITE WOLF_TOKEN=$token bash /tmp/wolf-agent-src/install.sh"
root "systemctl is-active wolf-agent && systemctl show wolf-agent -p User -p SupplementaryGroups -p Environment"
echo "Done. Site: http://$SITE:${WOLF_PILOT_HTTP:-8380} (add it to /etc/hosts or use curl -H 'Host: $SITE')"
