# Setup prompt for another Linux laptop

Copy this prompt to the coding agent on the new host. Supply the existing hotspot
password and device configuration privately; neither belongs in this repository.

```text
Set up the experimental CATLINK C08 local controller from
https://github.com/gillohner/catlink-controller on this laptop.

Read README.md and docs/ before making changes. On Omarchy, use the installed
Omarchy skill for system customization. Inspect the Wi-Fi hardware and current
network first. Prefer Ethernet upstream; otherwise verify concurrent AP/managed
support and match the 2.4 GHz upstream channel.

Preserve the existing hotspot SSID GilShare and obtain its existing password
privately. Keep gateway 10.42.0.1/24 if practical. Coordinate switching off the old
hotspot before bringing this one up. Create a persistent DHCP reservation for the
box and device-specific MQTT DNAT to the local controller. Merely putting the box
and laptop on the same ordinary Wi-Fi network will not redirect its vendor traffic.
Do not overwrite unrelated NetworkManager profiles or flush the firewall.

Obtain the previous controller's device identity/configuration through a private
transfer or capture it from this owned box's connection. Replace paths and IPs
for this host. Keep credentials, logs and real device identifiers out of Git.
Install the controller and persistent services, configure network boot persistence,
and verify device connection, fresh heartbeats and a matching clock acknowledgement.

Set up a private self-hosted ntfy server and Android subscription, immediate entry
alerts and completed-weight notifications. Test a clearly labelled setup message,
then a real visit, with the phone screen locked. Verify remote delivery separately
if requested. Do not claim an HTTP acceptance proves a displayed phone alert.

Keep visit history. Weight decoding is provisional and based on two labelled
visits; do not identify a cat from a partial entry reading. Calibrate and gather
more labelled samples before configuring identity bands. Optional Home Assistant
webhook integration is documented and still needs verification on a running HA.

Investigate manual cleaning and all other useful functions, but do not expose
unverified movement commands. Coordinate an empty-box test with the owner before
motor tests. Cloud-free cold startup remains unverified. Continue from the existing
protocol evidence rather than claiming the repository is a complete replacement.

Report verified features, remaining limitations, service/network persistence,
notification test results, and exact private config locations. Commit improvements
without private captures, device identities, Wi-Fi credentials or account tokens.
```
