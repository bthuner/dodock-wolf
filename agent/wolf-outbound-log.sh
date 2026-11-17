#!/bin/sh
# wolf-outbound-log [UID...]: log every new outbound connection of the bench users, and of the
# containers behind a Docker, Podman or CNI bridge, to the kernel log, for the Wolf agent.
# wolf-outbound-log --off: remove it.
#
# Optional, and the only privileged step of the agent's outbound watch: without it the agent
# samples /proc every minute and misses a connection that opens and closes in between. Install it
# as root and allow the agent to run it, and nothing else, through sudo (agent/README.md):
#   install -m 0755 -o root -g root wolf-outbound-log.sh /usr/local/sbin/wolf-outbound-log
#   echo 'wolf-agent ALL=(root) NOPASSWD: /usr/local/sbin/wolf-outbound-log' > /etc/sudoers.d/wolf-outbound-log
# The agent runs it with the uids of the bench folders' owners when they change. Lines start with
# "wolf-out: " (a bench user, with UID=) or "wolf-fwd: " (a container, with SRC=). TCP only (a
# DNS or NTP query would use up the budget); private, loopback and link-local destinations are
# left out; every rule shares one limit, 50 new connections a second for the whole host, so the
# journal cannot be flooded. Matching on `ct state new` turns connection tracking on for the
# host's traffic. `nft list table inet wolf_outbound` shows the counters.
set -eu

if [ "${1:-}" = "--off" ]; then
	nft list table inet wolf_outbound >/dev/null 2>&1 && nft delete table inet wolf_outbound
	exit 0
fi

uids=""
for uid in "$@"; do
	case "$uid" in
	'' | *[!0-9]*)
		echo "usage: wolf-outbound-log [UID...] | --off (uids are numbers)" >&2
		exit 2
		;;
	esac
	if [ "$uid" -eq 0 ]; then
		echo "uid 0 is refused: everything root does would be logged" >&2
		exit 2
	fi
	uids="${uids:+$uids, }$uid"
done

limit='limit name "wolf_rate"'
if [ -n "$uids" ]; then
	elements="elements = { $uids }"
	out4="ct state new meta l4proto tcp meta skuid @bench_uids ip daddr != @private4 $limit counter log prefix \"wolf-out: \" level info flags skuid"
	out6="ct state new meta l4proto tcp meta skuid @bench_uids ip6 daddr != @private6 $limit counter log prefix \"wolf-out: \" level info flags skuid"
else
	elements=""
	out4=""
	out6=""
fi

fwd=""
for bridge in docker0 'br-*' 'podman*' 'cni*'; do
	fwd="$fwd
		ct state new meta l4proto tcp iifname \"$bridge\" ip daddr != @private4 $limit counter log prefix \"wolf-fwd: \" level info
		ct state new meta l4proto tcp iifname \"$bridge\" ip6 daddr != @private6 $limit counter log prefix \"wolf-fwd: \" level info"
done

# "add, then delete, then define" replaces the whole table in one transaction
nft -f - <<NFT
add table inet wolf_outbound
delete table inet wolf_outbound
table inet wolf_outbound {
	limit wolf_rate { rate 50/second burst 200 packets }
	set bench_uids { type uid; $elements }
	set private4 {
		type ipv4_addr; flags interval;
		elements = { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/3 }
	}
	set private6 {
		type ipv6_addr; flags interval;
		elements = { ::/127, fc00::/7, fe80::/10, ff00::/8 }
	}
	chain output {
		type filter hook output priority 0; policy accept;
		$out4
		$out6
	}
	chain forward {
		type filter hook forward priority 0; policy accept;$fwd
	}
}
NFT
