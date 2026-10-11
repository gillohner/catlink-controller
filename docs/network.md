# Network topology and moving to another laptop

The working topology is:

```
Internet Wi-Fi -> Linux laptop -> GilShare 2.4 GHz hotspot -> C08
                              -> local controller
```

Keep the SSID `GilShare` and the existing password on the replacement host and
the box should not need new Wi-Fi provisioning. Configure the replacement with
the same hotspot subnet and gateway. Turn off the old hotspot before enabling
the new one. Never run two hotspots with identical credentials but different
controller routing during migration.

Requirements: NetworkManager shared IPv4, dnsmasq, iw, nftables, and an adapter
that supports concurrent managed/AP operation. The tested single adapter needs
both interfaces on the same channel; the upstream must therefore be 2.4 GHz.
Using two adapters or Ethernet upstream avoids that hardware constraint.

The current hotspot uses interface `gilshare0`, gateway `10.42.0.1/24`, and WPA2.
Create a separate AP-capable virtual interface on the upstream radio when needed:

```sh
# Inspect actual radio/interface names first; replace phy0 if needed.
iw dev
iw phy phy0 interface add gilshare0 type __ap
nmcli connection add type wifi ifname gilshare0 con-name GilShare ssid GilShare
nmcli connection modify GilShare 802-11-wireless.mode ap \
  802-11-wireless.band bg 802-11-wireless.channel 6 \
  wifi-sec.key-mgmt wpa-psk ipv4.method shared \
  ipv4.addresses 10.42.0.1/24 ipv6.method disabled
# Enter the existing WPA password privately; do not put it in version control.
nmcli connection edit GilShare
# At the editor: set wifi-sec.psk, then save persistent, then quit.
nmcli connection up GilShare
```

Run privileged network commands as root. Channel 6 is the tested upstream
channel, not a universal value; match your actual upstream channel. Configure a
DHCP reservation for the box's MAC before relying on a fixed interception IP.
The current research lease alone is not a reservation.

Redirect only this box's outbound TCP 1883 to the controller listener. Example
nftables batch, replacing DEVICE_IP and CONTROLLER_PORT with your private config:

```nft
table ip catlink_local {
  chain prerouting {
    type nat hook prerouting priority -110; policy accept;
    iifname "gilshare0" ip saddr DEVICE_IP tcp dport 1883 dnat to 10.42.0.1:CONTROLLER_PORT
  }
}
```

Save a reviewed batch and load it with `nft -f /path/to/catlink.nft`. Do not flush
existing firewall rules. Arrange persistence using the distribution's nftables
service or a dedicated unit after validating the rule. Permit DHCP UDP 67 and
DNS UDP/TCP 53 on the hotspot, device access to the MQTT listener, and forwarding
from hotspot to upstream. Permit the phone to reach ntfy TCP 18081. Restrict these
ports to the hotspot; the controller is not a general authenticated MQTT broker.

Rollback: `nft delete table ip catlink_local`, then stop the custom controller.
The box will return to its vendor MQTT destination on its next connection.

## Using the Yallo Wi-Fi directly

Putting the box on the ordinary Yallo 2.4 GHz network does not automatically work
with this controller. The box opens an outbound connection to a vendor host;
a second laptop on that network cannot intercept it just by listening. That
requires router-level routing/DNAT, an equivalent gateway, or verified DNS
redirection. Keep the hotspot until such a topology is demonstrated.

The box still has internet access in the tested arrangement. Cloud-free cold
startup has not been verified; do not block all internet as part of installation.
