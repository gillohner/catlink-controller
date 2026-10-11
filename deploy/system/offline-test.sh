#!/bin/bash
# Supervised offline test: can the box reach the local controller without the cloud?
#
#   offline-test.sh /path/to/private.env [minutes]
#
# 1. Turns on DNS query logging for the hotspot dnsmasq (kept afterwards: it shows
#    which vendor hosts the box looks up, private data stays in the system journal).
# 2. Blocks every forwarded packet from the box to the internet, logging each attempt
#    (DNS to the gateway and MQTT to the local controller still work).
# 3. Drops the box's current MQTT session so it must reconnect without the cloud.
# 4. Waits; the owner may power-cycle the box during the window for a cold-start test.
# 5. Removes the block on exit (also on Ctrl-C) and prints what the box tried to reach.
set -euo pipefail
ENV_FILE=${1:?usage: offline-test.sh private.env [minutes]}
MINUTES=${2:-20}
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${DEVICE_IP:?}" "${AP_IFACE:?}"
GATEWAY_IP=${GATEWAY_IP:-10.42.0.1}
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
STARTED=$(date '+%Y-%m-%d %H:%M:%S')

if ! grep -qx 'log-queries' /etc/catlink/dnsmasq.conf; then
  echo 'log-queries' >> /etc/catlink/dnsmasq.conf
  systemctl restart catlink-dnsmasq.service
  echo "== DNS query logging enabled"
fi

restore() {
  nft destroy table inet catlink_offline_test 2>/dev/null || true
  echo
  echo "== internet block removed ($(date +%H:%M:%S)); the box may now reach the cloud again"
  echo "== hosts the box looked up since $STARTED:"
  journalctl -u catlink-dnsmasq --since "$STARTED" --no-pager -o cat \
    | grep -E "query\[[A-Z]+\] .* from $DEVICE_IP" | awk '{print $2, $3}' | sort | uniq -c || true
  echo "== blocked connection attempts (destination, port):"
  journalctl -k --since "$STARTED" --no-pager -o cat | grep 'catlink-offline ' \
    | grep -oE 'DST=[0-9.]+ .*DPT=[0-9]+' | sed -E 's/DST=([0-9.]+).*DPT=([0-9]+)/\1 \2/' \
    | sort | uniq -c | sort -rn | head -20 || true
}
trap restore EXIT

nft -f - <<EOF
table inet catlink_offline_test {
  chain forward {
    type filter hook forward priority -10; policy accept;
    iifname "$AP_IFACE" ip saddr $DEVICE_IP limit rate 20/minute log prefix "catlink-offline " level info
    iifname "$AP_IFACE" ip saddr $DEVICE_IP drop
  }
}
EOF
echo "== $(date +%H:%M:%S) box internet blocked (DNS and local MQTT still allowed)"

# Force a reconnect: close the controller side of the box's MQTT session.
ss -K dst "$DEVICE_IP" sport = :"${CONTROLLER_PORT:-18830}" >/dev/null 2>&1 || true
echo "== $(date +%H:%M:%S) box MQTT session dropped; watching for $MINUTES min"
echo "   Optional cold-start test: after ~5 min, unplug the box for 10 s and plug it back in."
echo "   Press Ctrl-C to end early."

for ((i = 0; i < MINUTES * 6; i++)); do
  if ss -Htn state established "( sport = :${CONTROLLER_PORT:-18830} )" dst "$DEVICE_IP" | grep -q .; then
    state="CONNECTED to local controller"
  else
    state="not connected"
  fi
  printf '\r   %s  box: %-32s' "$(date +%H:%M:%S)" "$state"
  sleep 10
done
