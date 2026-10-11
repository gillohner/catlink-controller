# CATLINK C08 local controller — experimental

This is an independent implementation of the MQTT and binary framing observed
on one owned CATLINK Scooper C08. It is **not yet a complete local replacement**.

Verified on hardware through the packaged controller, on two different laptops:
receiving raw heartbeat frames, setting the clock with a matching device
acknowledgement, and live entry/exit events delivered to an Android phone through
the self-hosted ntfy bridge. Cleaning, pause, cancellation, settings, additional
telemetry field meanings, and cloud-free cold startup remain unverified.
No movement command is exposed. An optional Home Assistant webhook adapter is included but not verified on HA.

Two labelled physical visits produced entry/exit transitions and completed-visit
reports. The provisional completed weights were 3.84 kg and 4.81 kg,
consistent with the owner's confirmation of their relative weights. Absolute weight
calibration and long-term reliability still need verification. The decoder keeps
live occupancy separate from completed visits: brief re-entry can produce several
occupancy transitions and only one completed report. Cat identity is not assigned
automatically from these two samples.

`catlink-ctl watch` streams new entry, exit, and completed-visit events as JSON
through the private Unix socket. This is the interface for notification consumers.
The ntfy push bridge supports Android delivery; end-to-end lock-screen delivery
still needs verification. An optional Home Assistant webhook adapter is included but not verified on HA.
On a Linux desktop with `notify-send`, run `catlink-notify` as the logged-in
user to display entry and completed-weight notifications. It reconnects if the
controller restarts. Notifications missed while the consumer is stopped are
not replayed.
Events include `provisional: true`; completed reports include `weight_kg` and an
unverified `duration_seconds_candidate`. `catlink-history --config push.json`
lists completed visits from the event log with per-cat totals. An optional
private `cats` list in the push config (`[{"name", "min_kg", "max_kg"}]`) adds
"Probably NAME" to completed-visit notifications when exactly one band matches;
entry alerts never name a cat because the box reports no usable weight at entry. The stream does not replay history;
`status` includes the most recent 100 events held in memory. Slow subscribers
can lose older events; this is not a durable notification queue.

## Run the experimental endpoint

Requires Python 3.11 or later, Linux, and a network path that redirects the box's
outbound MQTT connection to this service. A laptop merely sharing the same Wi-Fi
does not provide that redirection.

```sh
python3 -m venv .venv
.venv/bin/pip install .
cp config.example.json config.json
# Edit config.json with your own observed device identity and network addresses.
.venv/bin/catlink-local --config config.json
```

The configured Unix administration socket is accessible only to the service user.
Use `.venv/bin/catlink-ctl status` to read connection status and the most recent raw
heartbeat. `.venv/bin/catlink-ctl sync_clock` reports success only after receiving
the matching C08 clock acknowledgement, and refuses to send before the box has
subscribed to its command topic.

The MQTT listener restricts clients by configured source IP and MQTT username.
It does not authenticate a cloud password and must be isolated to the box's
network. It neither logs nor stores MQTT passwords. Administration does not
provide arbitrary packet injection.

## Current network requirements

The deployed setup uses a hostapd 2.4 GHz hotspot on a virtual AP interface,
a dedicated dnsmasq for DHCP/DNS with a persistent reservation, and a
device-specific nftables DNAT rule for outbound TCP port 1883 plus masquerade.
`deploy/system/install-system.sh` provisions all of it on an Arch/Omarchy host
from a private env file; see [docs/network.md](docs/network.md) for why a
NetworkManager AP profile does not work on single-radio Intel adapters. The box also contacts an Alibaba HTTPS
authentication endpoint during startup. That bootstrap has not been replaced;
an offline reconnection attempt was inconclusive. Do not treat this service as
fully offline until a cold startup with internet blocked has been demonstrated.

For continuous operation, the host must remain awake and keep the network and
service running. Systemd units, a root-side installer and deployment guides are
included.

## Protocol evidence

Frames start with `FC`, contain a big-endian length equal to total frame length
minus four, a two-byte sequence, six-byte device MAC, message kind, subsystem,
two-byte command field, body, and XOR checksum. The checksum covers all bytes
after `FC` and before the checksum. These field names describe the observed
layout; not every field's vendor meaning has been established.

Observed commands: heartbeat `kind=3, subsystem=1, command=0x035a`; time request
`kind=3, subsystem=0x5a, command=0x2a5a`; clock set
`kind=1, subsystem=0x5a, command=0x0d5a`. The clock body contains zero, year minus
2000, month, day, ISO weekday, hour, minute, second. The successful clock reply is
`kind=2, subsystem=0x5a, command=0x0d5a, body=0000` on the same concrete RRPC topic.

The fixture MAC has been replaced and checksums recomputed. Captures, app APKs,
vendor code, private logs, and credentials are excluded from this project.

## Validate

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests exercise observed frames, corruption and truncation rejection, MQTT 3.1
sessions, clock acknowledgements, and rejection of an unexpected device identity.

## Deployment guides

- [Network and host migration](docs/network.md)
- [Android notifications](docs/notifications.md)
- [Continuous operation](docs/services.md)
- [Optional Home Assistant adapter](docs/homeassistant.md)
- [Setup prompt for another laptop](docs/agent-handoff.md)

## Protocol research workflow

Manual cleaning and other settings remain under investigation. They will only
be exposed after their C08 commands and acknowledgements are verified. While the
box is redirected to this controller, the vendor app cannot reach it, so the
vendor's command frames can only be observed by letting the box talk to its
broker for a supervised window:

```sh
# as root, owner present, box empty if a motor action will be triggered
deploy/system/capture-vendor-session.sh /private/system.env /private/captures 300
# then, as the service user:
PYTHONPATH=src python3 -m catlink_local.pcap_frames /private/captures/vendor-*.pcap
```

The helper removes only the DNAT rule (the box keeps internet), records the
plaintext MQTT session, and restores the redirection on exit. The decoder prints
frames per direction with the device MAC masked; captures stay private.
