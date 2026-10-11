#!/bin/bash
# Root-side installation for a dedicated CATLINK gateway laptop (Arch/Omarchy, ufw, NetworkManager
# upstream, hostapd hotspot). Idempotent: re-run after editing the env file.
#
# Usage (as root):  install-system.sh /path/to/private.env
#
# The env file is private (mode 600, outside Git) and must define:
#   DEVICE_IP        hotspot address reserved for the box          e.g. 10.42.0.17
#   DEVICE_WIFI_MAC  the box's Wi-Fi MAC                           e.g. aa:bb:cc:dd:ee:ff
#   CONTROLLER_PORT  local controller listener port                e.g. 18830
#   AP_IFACE         AP virtual interface name                     e.g. gilshare0
#   AP_PHY           radio that hosts the AP interface             e.g. phy0
#   AP_MAC           locally administered MAC for the AP interface e.g. e2:xx:xx:xx:xx:xx
#   UPSTREAM_IFACE   upstream interface for forwarding             e.g. wlp3s0
#   SERVICE_USER     unprivileged user running the user services   e.g. gil
#   HOTSPOT_SSID     existing hotspot SSID the box already knows
#   HOTSPOT_PSK      existing hotspot WPA2 passphrase
#   HOTSPOT_CHANNEL  2.4 GHz channel; must match the upstream station on one radio
#   COUNTRY_CODE     regulatory domain                             e.g. CH
# Optional:
#   NTFY_LAN_CIDR    LAN range allowed to reach ntfy via upstream  e.g. 192.168.1.0/24
#   GATEWAY_IP       default 10.42.0.1      HOTSPOT_CIDR  default 10.42.0.0/24
#   NTFY_PORT        default 18081
#
# Why hostapd instead of a NetworkManager AP profile: NetworkManager hands every Wi-Fi
# interface to wpa_supplicant, which initialises it in station mode. Radios whose
# interface combinations allow only one station (e.g. Intel iwlwifi: "#{ managed } <= 1")
# refuse to bring a second station up (EBUSY), so the AP never starts. hostapd puts the
# virtual interface straight into AP mode.
#
# The script only adds files named "catlink" plus one logind drop-in and one sysctl.
# It never flushes the firewall or touches unrelated NetworkManager profiles.
set -euo pipefail

ENV_FILE=${1:?usage: install-system.sh /path/to/private.env}
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${DEVICE_IP:?}" "${DEVICE_WIFI_MAC:?}" "${CONTROLLER_PORT:?}" "${AP_IFACE:?}" \
  "${AP_PHY:?}" "${AP_MAC:?}" "${UPSTREAM_IFACE:?}" "${SERVICE_USER:?}" \
  "${HOTSPOT_SSID:?}" "${HOTSPOT_PSK:?}" "${HOTSPOT_CHANNEL:?}" "${COUNTRY_CODE:?}"
GATEWAY_IP=${GATEWAY_IP:-10.42.0.1}
HOTSPOT_CIDR=${HOTSPOT_CIDR:-10.42.0.0/24}
NTFY_PORT=${NTFY_PORT:-18081}

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

# Substitute placeholders in a template. Private values never land in the repository.
render() {
  sed -e "s|AP_IFACE|$AP_IFACE|g" -e "s|AP_MAC|$AP_MAC|g" -e "s|AP_PHY|$AP_PHY|g" \
      -e "s|UPSTREAM_IFACE|$UPSTREAM_IFACE|g" -e "s|GATEWAY_IP|$GATEWAY_IP|g" \
      -e "s|HOTSPOT_CIDR|$HOTSPOT_CIDR|g" -e "s|DEVICE_IP|$DEVICE_IP|g" \
      -e "s|DEVICE_WIFI_MAC|$DEVICE_WIFI_MAC|g" -e "s|CONTROLLER_PORT|$CONTROLLER_PORT|g" \
      -e "s|HOTSPOT_SSID|$HOTSPOT_SSID|g" -e "s|HOTSPOT_PSK|$HOTSPOT_PSK|g" \
      -e "s|HOTSPOT_CHANNEL|$HOTSPOT_CHANNEL|g" -e "s|COUNTRY_CODE|$COUNTRY_CODE|g" \
      -e "s|gilshare0|$AP_IFACE|g" -e "s|phy0|$AP_PHY|g" -e "s|wlp3s0|$UPSTREAM_IFACE|g" \
      -e "s|e2:2b:e9:1a:6d:a7|$AP_MAC|g" "$1"
}

echo "== packages"
pacman -S --needed --noconfirm hostapd dnsmasq nftables iw >/dev/null

echo "== AP virtual interface unit"
render "$HERE/catlink-ap-interface.service" > /etc/systemd/system/catlink-ap-interface.service

echo "== keep NetworkManager off the AP interface"
install -d -m 755 /etc/NetworkManager/conf.d
render "$HERE/90-catlink-unmanaged.conf" > /etc/NetworkManager/conf.d/90-catlink-unmanaged.conf
# Left over from the NetworkManager shared-mode attempt; the dedicated dnsmasq owns the lease now.
rm -f /etc/NetworkManager/dnsmasq-shared.d/catlink.conf
nmcli general reload conf
if [[ -e /sys/class/net/$AP_IFACE ]]; then nmcli device set "$AP_IFACE" managed no || true; fi

echo "== hostapd and dnsmasq"
install -d -m 755 /etc/hostapd /etc/catlink /var/lib/catlink
(umask 077; render "$HERE/hostapd.conf.example" > /etc/hostapd/catlink.conf)
render "$HERE/dnsmasq.conf.example" > /etc/catlink/dnsmasq.conf
chmod 644 /etc/catlink/dnsmasq.conf
dnsmasq --test --conf-file=/etc/catlink/dnsmasq.conf
render "$HERE/catlink-hostapd.service" > /etc/systemd/system/catlink-hostapd.service
render "$HERE/catlink-dnsmasq.service" > /etc/systemd/system/catlink-dnsmasq.service

echo "== nftables DNAT/NAT table and unit"
render "$HERE/catlink.nft.example" > /etc/catlink/catlink.nft
chmod 644 /etc/catlink/catlink.nft
nft -c -f /etc/catlink/catlink.nft
install -m 644 "$HERE/catlink-nft.service" /etc/systemd/system/catlink-nft.service
install -m 644 "$HERE/90-catlink-forward.conf" /etc/sysctl.d/90-catlink-forward.conf
sysctl -q -p /etc/sysctl.d/90-catlink-forward.conf

echo "== ufw rules scoped to the hotspot"
ufw allow in on "$AP_IFACE" to any port 67 proto udp comment 'catlink hotspot DHCP'
ufw allow in on "$AP_IFACE" to any port 53 comment 'catlink hotspot DNS'
ufw allow in on "$AP_IFACE" from "$DEVICE_IP" to "$GATEWAY_IP" port "$CONTROLLER_PORT" proto tcp comment 'catlink C08 MQTT'
ufw allow in on "$AP_IFACE" from "$HOTSPOT_CIDR" to any port "$NTFY_PORT" proto tcp comment 'catlink ntfy (hotspot)'
if [[ -n ${NTFY_LAN_CIDR:-} ]]; then
  ufw allow in on "$UPSTREAM_IFACE" from "$NTFY_LAN_CIDR" to any port "$NTFY_PORT" proto tcp comment 'catlink ntfy (LAN)'
fi
ufw route allow in on "$AP_IFACE" out on "$UPSTREAM_IFACE" comment 'catlink hotspot forwarding'

echo "== keep the host awake"
install -d -m 755 /etc/systemd/logind.conf.d
install -m 644 "$HERE/50-catlink-lid.conf" /etc/systemd/logind.conf.d/50-catlink-lid.conf
systemctl kill -s HUP systemd-logind.service || true
loginctl enable-linger "$SERVICE_USER"

echo "== enable units"
systemctl daemon-reload
systemctl enable --now catlink-ap-interface.service
# Oneshot units stay "active"; restart so edited rules and configs are actually reloaded.
systemctl enable catlink-nft.service catlink-hostapd.service catlink-dnsmasq.service
systemctl restart catlink-nft.service
systemctl restart catlink-hostapd.service
systemctl restart catlink-dnsmasq.service

echo "== result"
sleep 2
systemctl --no-pager --quiet is-active catlink-hostapd catlink-dnsmasq catlink-nft && echo "hotspot services active"
iw dev "$AP_IFACE" info | grep -E 'ssid|type|channel' || true
ip -br addr show "$AP_IFACE"
nft list table ip catlink_local
ufw status | grep -i catlink || true
loginctl show-user "$SERVICE_USER" -p Linger
echo "done"
