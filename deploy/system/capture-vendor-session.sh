#!/bin/bash
# Supervised protocol-research capture. Temporarily removes ONLY the device DNAT so the
# box reconnects to its vendor broker, records its plaintext MQTT on the hotspot interface,
# then restores the redirection. Run as root, with the owner present and the box empty if
# a motor command will be triggered from the vendor app.
#
#   capture-vendor-session.sh /path/to/private.env /private/output/dir [seconds]
#
# The capture contains the device identity and vendor traffic: keep it private, never commit it.
set -euo pipefail
ENV_FILE=${1:?usage: capture-vendor-session.sh private.env OUTDIR [seconds]}
OUTDIR=${2:?output directory}
SECONDS_TO_CAPTURE=${3:-300}
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${DEVICE_IP:?}" "${AP_IFACE:?}"
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
command -v tcpdump >/dev/null || { echo "tcpdump is not installed (pacman -S tcpdump)" >&2; exit 1; }

install -d -m 700 "$OUTDIR"
PCAP="$OUTDIR/vendor-$(date +%Y%m%d-%H%M%S).pcap"

restore() {
  echo "== restoring device DNAT"
  nft -f /etc/catlink/catlink.nft
  # Drop the box's current vendor session so it reconnects through the redirection.
  conntrack -D -s "$DEVICE_IP" -p tcp --dport 1883 >/dev/null 2>&1 || true
  echo "capture saved to $PCAP (private)"
}
trap restore EXIT

echo "== removing device DNAT (masquerade stays, the box keeps internet)"
nft flush chain ip catlink_local prerouting
conntrack -D -s "$DEVICE_IP" -p tcp --dport 1883 >/dev/null 2>&1 || true
echo "== capturing $SECONDS_TO_CAPTURE s of TCP 1883 traffic from $DEVICE_IP on $AP_IFACE"
echo "   trigger the vendor-app action(s) now; press Ctrl-C to stop early"
timeout "$SECONDS_TO_CAPTURE" tcpdump -ni "$AP_IFACE" -s0 -w "$PCAP" host "$DEVICE_IP" and tcp port 1883 || true
chmod 600 "$PCAP"
