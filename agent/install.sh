#!/usr/bin/env bash
# One-command Wolf Agent install.
#
#   sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<registration token> ./install.sh
#
# Optional env:
#   WOLF_AGENT_SRC  pip source (local dir or git+https URL); default: this script's directory,
#                   or the GitHub repository when the script is piped from curl.
#   WOLF_AGENT_REF  git ref used when installing from GitHub (default: main)
#   WOLF_BENCHES    space-separated bench paths (default: auto-discover)
#   WOLF_INSECURE=1 skip TLS verification during registration and pushes
#
# On a Frappe Pilot host it also installs wolf-pilot-export, a root timer that copies the bench
# tasks and process states the agent cannot read itself (docs-site: Pilot benches).
set -euo pipefail

PREFIX=/opt/wolf-agent
CONFIG_DIR=/etc/wolf-agent
CONFIG="$CONFIG_DIR/config.json"
STATE_DIR=/var/lib/wolf-agent
USER_NAME=wolf-agent
REPO=https://github.com/bthuner/dodock-wolf
REF="${WOLF_AGENT_REF:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
	SRC="${WOLF_AGENT_SRC:-$SCRIPT_DIR}"
else
	# Piped from curl: no checkout next to us.
	SRC="${WOLF_AGENT_SRC:-git+$REPO.git@$REF#subdirectory=agent}"
fi

if [[ $EUID -ne 0 ]]; then
	echo "install.sh must run as root" >&2
	exit 1
fi
if [[ ! -f "$SRC/pyproject.toml" && "$SRC" != git+* && "$SRC" != http* ]]; then
	echo "no wolf-agent source at $SRC; set WOLF_AGENT_SRC to a checkout or git+https URL" >&2
	exit 1
fi
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
if [[ "$SRC" == git+* ]]; then command -v git >/dev/null || { echo "git is required to install from $REPO" >&2; exit 1; }; fi

echo "==> installing wolf-agent into $PREFIX"
python3 -m venv "$PREFIX"
"$PREFIX/bin/pip" install --quiet --upgrade pip
"$PREFIX/bin/pip" install --quiet --upgrade "$SRC"
ln -sf "$PREFIX/bin/wolf-agent" /usr/local/bin/wolf-agent

echo "==> creating user $USER_NAME"
if ! id "$USER_NAME" >/dev/null 2>&1; then
	# a group left from an earlier install is reused
	group_opt=(--user-group)
	if getent group "$USER_NAME" >/dev/null; then group_opt=(--gid "$USER_NAME"); fi
	useradd --system --no-create-home --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "${group_opt[@]}" "$USER_NAME"
fi
for group in adm systemd-journal frappe proxy; do  # proxy: read Squid's access log
	if getent group "$group" >/dev/null; then
		usermod -aG "$group" "$USER_NAME"
	fi
done

install -d -m 0750 -o "$USER_NAME" -g "$USER_NAME" "$STATE_DIR" "$STATE_DIR/spool"
install -d -m 0750 -o root -g "$USER_NAME" "$CONFIG_DIR"

if [[ -n "${WOLF_URL:-}" && -n "${WOLF_TOKEN:-}" ]]; then
	echo "==> registering with $WOLF_URL"
	args=(--config "$CONFIG" register --url "$WOLF_URL" --token "$WOLF_TOKEN")
	for bench in ${WOLF_BENCHES:-}; do
		args+=(--bench "$bench")
	done
	if [[ "${WOLF_INSECURE:-0}" == 1 ]]; then args+=(--insecure); fi
	"$PREFIX/bin/wolf-agent" "${args[@]}"
fi
if [[ -f "$CONFIG" ]]; then
	chown "$USER_NAME:$USER_NAME" "$CONFIG"
	chmod 0600 "$CONFIG"
fi

echo "==> installing systemd unit"
if [[ -f "$SCRIPT_DIR/wolf-agent.service" ]]; then
	install -m 0644 "$SCRIPT_DIR/wolf-agent.service" /etc/systemd/system/wolf-agent.service
else
	curl -fsSL "https://raw.githubusercontent.com/bthuner/dodock-wolf/$REF/agent/wolf-agent.service" \
		-o /etc/systemd/system/wolf-agent.service
	chmod 0644 /etc/systemd/system/wolf-agent.service
fi

# Frappe Pilot keeps a bench's tasks private and runs it as the bench user's systemd user units:
# a root timer copies what the agent needs (task states, unit states, no secrets) for wolf-agent
PILOT=0
for toml in /home/*/pilot/benches/*/bench.toml; do
	if [[ -f "$toml" ]]; then PILOT=1; break; fi
done
if [[ "$PILOT" == 1 ]]; then
	echo "==> Frappe Pilot host: installing wolf-pilot-export (root, every 20 s)"
	fetched=$(mktemp -d)
	got=1
	for file in wolf-pilot-export wolf-pilot-export.service wolf-pilot-export.timer; do
		if [[ -f "$SCRIPT_DIR/pyproject.toml" && -f "$SCRIPT_DIR/$file" ]]; then  # a checkout, not the current folder
			cp "$SCRIPT_DIR/$file" "$fetched/$file"
		elif ! curl -fsSL "https://raw.githubusercontent.com/bthuner/dodock-wolf/$REF/agent/$file" -o "$fetched/$file"; then
			got=0
		fi
	done
	if [[ "$got" == 1 ]]; then
		install -m 0755 -o root -g root "$fetched/wolf-pilot-export" /usr/local/sbin/wolf-pilot-export
		install -m 0644 "$fetched/wolf-pilot-export.service" /etc/systemd/system/wolf-pilot-export.service
		install -m 0644 "$fetched/wolf-pilot-export.timer" /etc/systemd/system/wolf-pilot-export.timer
		/usr/local/sbin/wolf-pilot-export || echo "wolf-pilot-export failed: Pilot tasks and process states wait for its timer" >&2
	else
		echo "could not download wolf-pilot-export: Pilot tasks and process states are unavailable until install.sh runs again" >&2
		PILOT=0
	fi
	rm -r "$fetched"
fi

if ! command -v systemctl >/dev/null || [[ ! -d /run/systemd/system ]]; then
	if [[ "$PILOT" == 1 ]]; then
		echo "==> no timer without systemd: run /usr/local/sbin/wolf-pilot-export as root every 20 s (its copy older than 5 minutes is ignored)"
	fi
	echo "==> no systemd here (container?). Start the agent yourself, as $USER_NAME:"
	echo "    $PREFIX/bin/wolf-agent --config $CONFIG run"
	exit 0
fi
systemctl daemon-reload
if [[ "$PILOT" == 1 ]]; then systemctl enable --now wolf-pilot-export.timer; fi

if [[ -f "$CONFIG" ]]; then
	systemctl enable --now wolf-agent
	echo "==> wolf-agent is running: journalctl -u wolf-agent -f"
	echo "==> check the host: sudo -u $USER_NAME wolf-agent doctor"
else
	systemctl enable wolf-agent
	echo "==> installed but not registered. Run:"
	echo "    sudo wolf-agent --config $CONFIG register --url https://<wolf-site> --token <token>"
	echo "    sudo chown $USER_NAME: $CONFIG && sudo systemctl start wolf-agent"
fi
