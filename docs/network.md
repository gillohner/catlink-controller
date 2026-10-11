# Network topology and moving to another laptop

The working topology is:

```
Internet Wi-Fi (2.4 GHz) -> Linux laptop -> GilShare 2.4 GHz hotspot -> C08
                                        -> local controller
```

Keep the SSID `GilShare` and the existing password on the replacement host and
the box does not need new Wi-Fi provisioning: on the second host the box joined
the new hotspot on its own about a minute after the old one was switched off.
Configure the replacement with the same hotspot subnet and gateway. Turn off the
old hotspot before enabling the new one. Never run two hotspots with identical
credentials but different controller routing during migration.

Requirements: hostapd, dnsmasq, iw, nftables, NetworkManager for the upstream,
and an adapter that supports concurrent managed/AP operation. A single adapter
needs both interfaces on the same channel; the upstream must therefore be 2.4 GHz
and sit on the hotspot channel. Using two adapters or Ethernet upstream avoids
that hardware constraint.

## Why hostapd and not a NetworkManager AP profile

The first host ran the hotspot as a NetworkManager `shared` Wi-Fi profile. On the
second host (Intel iwlwifi, interface combinations `#{ managed } <= 1, #{ AP } <= 1`)
that fails: NetworkManager hands every Wi-Fi interface to wpa_supplicant, which
initialises it in station mode before switching to AP mode, and the second station
cannot come up (`Could not set interface 'gilshare0' UP: Device or resource busy`).
hostapd puts the virtual interface straight into AP mode, so the installer uses:

- `catlink-ap-interface.service`: `iw phy phyX interface add gilshare0 type __ap`
  with a locally administered MAC, before NetworkManager starts.
- `/etc/NetworkManager/conf.d/90-catlink-unmanaged.conf`: keeps NetworkManager
  (and wpa_supplicant) away from `gilshare0`.
- `catlink-hostapd.service`: WPA2-PSK/CCMP AP on the shared channel, assigns
  `10.42.0.1/24` to the interface.
- `catlink-dnsmasq.service`: a dedicated dnsmasq instance (`--conf-file`) for DHCP
  and DNS on the hotspot only, with the box's persistent reservation
  (`dhcp-host=MAC,IP,...,infinite`).
- `catlink-nft.service`: one nftables table with the device-specific DNAT and the
  hotspot masquerade; `/etc/sysctl.d/90-catlink-forward.conf` enables forwarding.
- ufw rules scoped to the hotspot interface (see below).

All of it is installed by `deploy/system/install-system.sh` from a private env
file (`deploy/system/system.env.example`). Run it as root; re-running is safe.
Read the script before running it; it only adds `catlink`-named files, one
logind drop-in and one sysctl, and never flushes the firewall or edits unrelated
NetworkManager profiles.

Upstream on the second host: NetworkManager profile for the 2.4 GHz SSID with
autoconnect enabled and the 5 GHz profile's autoconnect disabled, so a reboot
cannot land the station on a channel the AP cannot share. If the router moves the
2.4 GHz network to another channel, change `HOTSPOT_CHANNEL` and re-run the
installer; hostapd cannot start on a channel the station does not use.

## Firewall (ufw host)

Omarchy ships ufw with default deny incoming and deny forward. The installer adds:

- `in on gilshare0` UDP 67 (DHCP) and 53 (DNS)
- `in on gilshare0 from DEVICE_IP to 10.42.0.1 port CONTROLLER_PORT/tcp` (MQTT)
- `in on gilshare0 from 10.42.0.0/24 port 18081/tcp` (ntfy from the hotspot)
- optionally `in on UPSTREAM from NTFY_LAN_CIDR port 18081/tcp` (ntfy from the LAN)
- `route allow in on gilshare0 out on UPSTREAM` (hotspot forwarding)

The DNAT lives in nftables, not ufw:

```nft
table ip catlink_local {
  chain prerouting {
    type nat hook prerouting priority -110; policy accept;
    iifname "gilshare0" ip saddr DEVICE_IP tcp dport 1883 dnat to 10.42.0.1:CONTROLLER_PORT
  }
  chain postrouting {
    type nat hook postrouting priority 100; policy accept;
    oifname "UPSTREAM" ip saddr 10.42.0.0/24 masquerade
  }
}
```

Observed failure mode worth knowing: when the masquerade rule was missing the box
associated, completed the WPA handshake, then dropped the Wi-Fi link every ~40 s
and never attempted MQTT. The box needs working internet (its HTTPS bootstrap)
before it opens the MQTT connection that gets redirected. Do not block all
internet as part of installation; cloud-free cold startup is unverified.

Rollback: `systemctl disable --now catlink-nft` (destroys the table), then stop the
custom controller. The box returns to its vendor MQTT destination on its next
connection.

## Using the Yallo Wi-Fi directly

Putting the box on the ordinary 2.4 GHz home network does not automatically work
with this controller. The box opens an outbound connection to a vendor host;
a second laptop on that network cannot intercept it just by listening. That
requires router-level routing/DNAT, an equivalent gateway, or verified DNS
redirection. Keep the hotspot until such a topology is demonstrated.
