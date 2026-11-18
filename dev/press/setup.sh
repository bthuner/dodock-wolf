#!/usr/bin/env bash
# Set up a Press app server with Wolf (dev/press/README.md):
#   1. Press's own Ansible roles (frappe/press, pinned) provision the `server` container: the frappe
#      user, nginx, the Press agent (frappe/agent, pinned) under supervisor, Docker;
#   2. a Press-style bench image with dodock_wolf goes to a registry on the server;
#   3. the Press agent's API creates a bench and a site on the database server, as Press does;
#   4. the Wolf agent is installed with agent/install.sh from this checkout and registered with the site.
# Run from dev/press:  docker compose up -d --build && ./setup.sh
# Each step is skipped when already done, so it can be run again after a failure.
set -euo pipefail
cd "$(dirname "$0")"

PRESS_REF="${WOLF_PRESS_REF:-7ce25f221378cb4558cd3993f3283d75cc8fe7d7}"  # frappe/press, 2026-11-18
AGENT_REF="${WOLF_PRESS_AGENT_REF:-6bbd199c13e90f48950e2a06401ca98738455aaf}"  # frappe/agent, 2026-11-17
BASE="${WOLF_PRESS_BASE:-frappe/erpnext:v16.5.0}"
SERVER=f1-press  # the compose hostname, which Press would have named the server
BENCH="${WOLF_PRESS_BENCH:-bench-0001-000001-$SERVER}"
SITE="${WOLF_PRESS_SITE:-wolf.localhost}"
DB_PASSWORD="${WOLF_PRESS_DB_PASSWORD:-admin}"

PROXY=n1-press
SERVER_IP=172.30.80.2
PROXY_IP=172.30.80.3

on() { docker compose exec -T "$1" bash -c "$2"; }
root() { on server "$1"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# provision SERVICE NAME "ROLE..." [EXTRA_VARS]: Press's playbook roles on one container, run again
# when the roles or the variables change (the marker holds the playbook and vars that last ran)
provision() {
	local service=$1 name=$2 roles=$3 extra=${4:-}
	# shellcheck disable=SC2016  # expanded in the container
	on "$service" 'for _ in $(seq 60); do systemctl is-system-running 2>/dev/null | grep -qE "running|degraded" && exit 0; sleep 2; done; exit 1' \
		|| { echo "systemd did not start in $service" >&2; exit 1; }
	on "$service" "[ -d /opt/press/.git ] || { git clone -q --filter=blob:none --no-checkout https://github.com/frappe/press /opt/press \
	  && git -C /opt/press sparse-checkout set --no-cone /press/playbooks/; }; git -C /opt/press checkout -q $PRESS_REF"
	on "$service" "set -e; mkdir -p -m 0700 /root/wolf-press; cd /root/wolf-press
	  [ -s agent_password ] || head -c 24 /dev/urandom | base64 | tr -d '/+=' > agent_password
	  [ -s monitoring_password ] || head -c 24 /dev/urandom | base64 | tr -d '/+=' > monitoring_password
	  [ -s fullchain.pem ] || openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj /CN=$name \
	    -keyout privkey.pem -out fullchain.pem 2>/dev/null
	  cat > vars.yml <<YML
server: $name
workers: 2
agent_repository_url: https://github.com/frappe/agent
agent_branch: $AGENT_REF
agent_password: \"{{ lookup('file', '/root/wolf-press/agent_password') }}\"
monitoring_password: \"{{ lookup('file', '/root/wolf-press/monitoring_password') }}\"
certificate_private_key: \"{{ lookup('file', '/root/wolf-press/privkey.pem') }}\"
certificate_full_chain: \"{{ lookup('file', '/root/wolf-press/fullchain.pem') }}\"
certificate_intermediate_chain: \"{{ lookup('file', '/root/wolf-press/fullchain.pem') }}\"
$extra
YML
	  printf -- '- hosts: all\n  become: yes\n  become_user: root\n  gather_facts: yes\n  roles:\n' > server.yml
	  for r in $roles; do printf '    - role: %s\n' \$r >> server.yml; done
	  sum=\$(cat server.yml vars.yml | sha256sum)
	  [ \"\$sum\" = \"\$(cat provisioned 2>/dev/null)\" ] && exit 0
	  ANSIBLE_ROLES_PATH=/opt/press/press/playbooks/roles ANSIBLE_NOCOLOR=1 \
	    ansible-playbook -i localhost, -c local server.yml -e @vars.yml
	  echo \"\$sum\" > provisioned"
}

step "App server: Press's roles (frappe/press@${PRESS_REF:0:7}), as press/playbooks/server.yml without hardening, other exporters, backups or volume mounts"
# proxy_ip: the app server's nginx trusts X-Real-IP from Press's proxy (agent setup config --proxy-ip);
# the benches' gunicorn sends its metrics to <private_ip>:9125 (statsd_exporter)
provision server $SERVER "essentials user nginx agent bench docker statsd_exporter" "private_ip: $SERVER_IP
proxy_ip: $PROXY_IP"
# the agent's workers started (role agent) before frappe joined the docker group (role docker):
# restart them, as Press's restart_agent_workers role does
root "id -nG frappe | grep -qw docker && supervisorctl restart 'agent:' >/dev/null && supervisorctl status | grep '^agent:'"
root "docker info --format 'docker {{.ServerVersion}}'"

step "Proxy server: Press's roles, as press/playbooks/proxy.yml without monitoring and hardening"
provision proxy $PROXY "essentials user nginx agent proxy" "domain: $PROXY
press_url: http://press.invalid"
on proxy "supervisorctl start 'agent:' >/dev/null 2>&1; supervisorctl status | grep '^agent:'"

step "Bench image: $BASE, finished as Press's image template does, with dodock_wolf"
ctx=$(mktemp -d)
trap 'rm -rf "$ctx"' EXIT
cp bench/Dockerfile "$ctx/"
mkdir "$ctx/dodock_wolf"
# this checkout, with uncommitted changes to tracked files (git stash create leaves the working
# tree alone; untracked files are not in it: commit or `git add` them first)
tree=$(git -C ../.. stash create 2>/dev/null || true)
git -C ../.. archive "${tree:-HEAD}" -- . ':!docs-site' ':!dev' ':!docs' | tar -x -C "$ctx/dodock_wolf"
docker build -q --build-arg "BASE=$BASE" --build-arg "PRESS_REF=$PRESS_REF" -t wolf-press-bench:local "$ctx"
local_id=$(docker image inspect -f '{{.Id}}' wolf-press-bench:local)
root "docker ps -q -f name=^registry\$ | grep -q . || docker run -d --restart always --name registry -p 127.0.0.1:5000:5000 registry:2 >/dev/null"
if [ "$(root "docker image inspect -f '{{.Id}}' wolf-press-bench:local 2>/dev/null" || true)" != "$local_id" ]; then
	docker save wolf-press-bench:local | docker compose exec -T server docker load
fi
root "docker tag wolf-press-bench:local localhost:5000/wolf-press-bench:latest && docker push -q localhost:5000/wolf-press-bench:latest"

step "Database server"
for _ in $(seq 60); do
	[ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q db)")" = healthy ] && break
	sleep 2
done

step "Bench $BENCH and site $SITE through the Press agent's API"
docker compose cp press_api.py server:/usr/local/bin/press-api >/dev/null
root "chmod 0755 /usr/local/bin/press-api"
# a bench is there once its container is: a failed New Bench leaves a folder the next one refuses
root "docker container inspect $BENCH >/dev/null 2>&1 || { rm -rf /home/frappe/benches/$BENCH \
  && PRESS_DB_PASSWORD=$DB_PASSWORD press-api new-bench $BENCH 0; }"
# a deploy (Update Site Migrate) moves the site to another bench: look for it on all of them
root "ls -d /home/frappe/benches/*/sites/$SITE >/dev/null 2>&1 || PRESS_DB_PASSWORD=$DB_PASSWORD press-api new-site $BENCH $SITE frappe dodock_wolf"
# the bench whose nginx serves it (a failed New Site can leave a folder elsewhere)
SITE_BENCH=$(root "grep -lFw '$SITE' /home/frappe/benches/*/nginx.conf | head -1 | cut -d/ -f5" | tr -d '[:space:]')
[ -n "$SITE_BENCH" ] || { echo "no bench serves $SITE" >&2; exit 1; }
root "docker ps --format '{{.Names}} {{.Status}}' | grep bench-"

step "$SITE through the proxy: Press's Add Upstream to Proxy, Add Host to Proxy and Add Site to Upstream jobs"
docker compose cp press_api.py proxy:/usr/local/bin/press-api >/dev/null
on proxy "chmod 0755 /usr/local/bin/press-api; cd /root/wolf-press
  [ -s site-fullchain.pem ] || openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj /CN=$SITE \
    -addext subjectAltName=DNS:$SITE -keyout site-privkey.pem -out site-fullchain.pem 2>/dev/null
  python3 -c 'import json; r=lambda p: open(p).read(); print(json.dumps({\"name\": \"$SITE\", \"target\": \"$SITE\",
    \"certificate\": {\"privkey.pem\": r(\"site-privkey.pem\"), \"fullchain.pem\": r(\"site-fullchain.pem\"),
    \"chain.pem\": r(\"site-fullchain.pem\")}}))' > site-host.json"
api="PRESS_SERVER_NAME=$PROXY press-api"
on proxy "[ -d /home/frappe/agent/nginx/upstreams/$SERVER_IP ] || $api job 'Add Upstream to Proxy' proxy/upstreams '{\"name\": \"$SERVER_IP\"}'"
# a host maps to its site (press/agent.py new_host), which the upstreams map to the app server
on proxy "grep -q '\"$SITE\": \"$SITE\"' /home/frappe/agent/nginx/hosts/$SITE/map.json 2>/dev/null || $api job 'Add Host to Proxy' proxy/hosts \"\$(cat /root/wolf-press/site-host.json)\""
on proxy "[ -f /home/frappe/agent/nginx/upstreams/$SERVER_IP/$SITE ] || $api job 'Add Site to Upstream' proxy/upstreams/$SERVER_IP/sites '{\"name\": \"$SITE\"}'"
on proxy "curl -sk -o /dev/null -w 'through the proxy: %{http_code}\n' --resolve $SITE:443:127.0.0.1 https://$SITE/api/method/ping"

step "The Wolf agent, with agent/install.sh from this checkout"
# the site's name resolves here, as a real one would through DNS
root "grep -q ' $SITE' /etc/hosts || echo '127.0.0.1 $SITE' >> /etc/hosts"
token=$(root "docker exec -w /home/frappe/frappe-bench/sites $SITE_BENCH ../env/bin/python -c \"
import frappe; frappe.init('$SITE', sites_path='.'); frappe.connect()
from frappe.utils.password import get_decrypted_password
print(get_decrypted_password('Wolf Settings', 'Wolf Settings', 'registration_token'))\"" | tail -1 | tr -d '[:space:]')
[ -n "$token" ] || { echo "no registration token on $SITE" >&2; exit 1; }
# registered once; later runs upgrade it in place and keep its config, as on a real host
root "apt-get install -y -qq python3-venv >/dev/null && rm -rf /tmp/wolf-agent-src && cp -r /src/agent /tmp/wolf-agent-src \
  && if [ -f /etc/wolf-agent/config.json ]; then WOLF_AGENT_SRC=/tmp/wolf-agent-src bash /tmp/wolf-agent-src/install.sh \
       && systemctl restart wolf-agent; \
     else WOLF_AGENT_SRC=/tmp/wolf-agent-src WOLF_URL=http://$SITE WOLF_TOKEN=$token bash /tmp/wolf-agent-src/install.sh; fi"
root "systemctl is-active wolf-agent && systemctl show wolf-agent -p User -p SupplementaryGroups"

step "The Wolf agent on the proxy: it reads the proxy's access log, where web clients' blocks take effect"
on proxy "grep -q ' $SITE' /etc/hosts || echo '$SERVER_IP $SITE' >> /etc/hosts"
on proxy "apt-get install -y -qq python3-venv >/dev/null && rm -rf /tmp/wolf-agent-src && cp -r /src/agent /tmp/wolf-agent-src \
  && if [ -f /etc/wolf-agent/config.json ]; then WOLF_AGENT_SRC=/tmp/wolf-agent-src bash /tmp/wolf-agent-src/install.sh \
       && systemctl restart wolf-agent; \
     else WOLF_AGENT_SRC=/tmp/wolf-agent-src WOLF_URL=http://$SITE WOLF_TOKEN=$token bash /tmp/wolf-agent-src/install.sh; fi"
on proxy "systemctl is-active wolf-agent && python3 -c 'import json; print(json.load(open(\"/etc/wolf-agent/config.json\")).get(\"extra_logs\"))'"
echo "Done. Site: http://$SITE:${WOLF_PRESS_HTTP:-8480} (Administrator / admin)"
