#!/bin/sh
# wolf-block IP SECONDS: drop traffic from IP for SECONDS (60 to 604800) with nftables.
#
# The only privileged step of Wolf's response actions. Install it as root and allow the agent
# to run it, and nothing else, through sudo (agent/README.md, "Response actions"):
#   install -m 0755 -o root -g root wolf-block.sh /usr/local/sbin/wolf-block
#   echo 'wolf-agent ALL=(root) NOPASSWD: /usr/local/sbin/wolf-block' > /etc/sudoers.d/wolf-block
# Entries expire by themselves (nftables set timeout). `nft list table inet wolf` shows them.
# Blocking an address that is already blocked keeps the longer of the two.
set -eu

if [ "$#" -ne 2 ]; then
	echo "usage: wolf-block IP SECONDS" >&2
	exit 2
fi
ip="$1"
seconds="$2"

case "$seconds" in
'' | *[!0-9]*)
	echo "seconds must be a whole number" >&2
	exit 2
	;;
esac
if [ "$seconds" -lt 60 ] || [ "$seconds" -gt 604800 ]; then
	echo "seconds must be between 60 and 604800" >&2
	exit 2
fi
# an address only, never a name nft would look up: digits and 3 dots, or hex, colons and dots
case "$ip" in
'' | *[!0-9a-fA-F:.]* | :*:*:*:*:*:*:*:*:*) ip_ok=no ;;
*:*:*) ip_ok=yes set_name=blocked6 ;;
*[!0-9.]* | *.*.*.*.* | *..* | .* | *.) ip_ok=no ;;
*.*.*.*) ip_ok=yes set_name=blocked4 ;;
*) ip_ok=no ;;
esac
if [ "$ip_ok" != yes ]; then
	echo "invalid address" >&2
	exit 2
fi

if ! nft list table inet wolf >/dev/null 2>&1; then
	nft -f - <<'NFT'
table inet wolf {
	set blocked4 { type ipv4_addr; flags timeout; }
	set blocked6 { type ipv6_addr; flags timeout; }
	chain input {
		type filter hook input priority -10; policy accept;
		ip saddr @blocked4 drop
		ip6 saddr @blocked6 drop
	}
}
NFT
fi
# Already blocked: the longer block wins. Kernels differ on `add` for an element that exists
# (some keep its timeout, newer ones reset it), so a shorter block is skipped here and a longer
# one replaces the element in one transaction (never unblocked in between).
left=$(nft get element inet wolf "$set_name" "{ $ip }" 2>/dev/null | awk '
	match($0, /expires [0-9dhms]+/) {
		s = substr($0, RSTART + 8, RLENGTH - 8); t = 0
		while (match(s, /^[0-9]+(ms|d|h|m|s)/)) {
			part = substr(s, 1, RLENGTH); n = part + 0; unit = part; sub(/^[0-9]+/, "", unit)
			if (unit == "d") t += n * 86400; else if (unit == "h") t += n * 3600
			else if (unit == "m") t += n * 60; else if (unit == "s") t += n
			s = substr(s, RLENGTH + 1)
		}
		print t; exit
	}') || left=""
if [ -n "$left" ] && [ "$left" -ge "$seconds" ]; then
	echo "$ip already blocked for ${left}s more (inet wolf $set_name): kept"
	exit 0
fi
if [ -n "$left" ]; then
	# the add first: an element that expired since the check would fail the delete, and the batch
	nft -f - <<NFT
add element inet wolf $set_name { $ip }
delete element inet wolf $set_name { $ip }
add element inet wolf $set_name { $ip timeout ${seconds}s }
NFT
else
	nft add element inet wolf "$set_name" "{ $ip timeout ${seconds}s }"
fi
echo "blocked $ip for ${seconds}s (inet wolf $set_name)"
