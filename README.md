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
reports with box readings of 3.84 kg and 4.81 kg, consistent with the owner's
confirmation of their relative weights. Two known-weight tests on the second host
(3.238 kg and 1.524 kg objects) read 2.46 kg and 1.33 kg: the box's scale reads
low and not by a constant factor, so absolute weights need a per-box linear
calibration (`calibration: {slope, intercept}` in the push config) and more
points before they can be trusted. The completed report's bytes 2-3 are the
visit duration in seconds from the first entry to the final exit; a brief
entry that produces no report keeps its start time for the next report. The decoder keeps
live occupancy separate from completed visits: brief re-entry can produce several
occupancy transitions and only one completed report. Cat identity is not assigned
automatically from these two samples.

`catlink-ctl watch` streams entry, exit, completed-visit, deposit-estimate and
cleaning events as JSON through the private Unix socket. This is the interface for notification consumers.
The ntfy push bridge supports Android delivery; end-to-end lock-screen delivery
still needs verification. An optional Home Assistant webhook adapter is included but not verified on HA.
On a Linux desktop with `notify-send`, run `catlink-notify` as the logged-in
user to display entry and completed-weight notifications. It reconnects if the
controller restarts. Notifications missed while the consumer is stopped are
not replayed.
Events include `provisional: true`; completed reports include `weight_kg` and an
unverified `duration_seconds_candidate`. `catlink-history --config push.json`
lists completed visits with calibrated weight, raw box reading, duration and the
tare-relative scale residual after the cat left; `catlink-history label --cat NAME
--deposit pee|poop|both|none` records what the owner observed so the cat bands and
any deposit heuristic can be scored against reality (`cat guess vs label`). An optional
private `cats` list in the push config (`[{"name", "min_kg", "max_kg"}]`) adds
"Probably NAME" to completed-visit notifications when exactly one band matches
the (calibrated, if configured) weight;
entry alerts never name a cat because the box reports no usable weight at entry. The stream does not replay history;
`status` includes the most recent 100 events held in memory. Slow subscribers
can lose older events; this is not a durable notification queue.

`catlink-health` (own user unit) polls the controller and sends a high-priority
ntfy alert when no heartbeat has arrived for five minutes or the controller is
unreachable for longer than a grace period, a recovery message afterwards, and an
optional daily digest (visits per cat, cleaning cycles, weight range). Both were
exercised on the deployed host by stopping the controller.

## Self-tuning and watchdogs

`catlink-health` re-learns hourly from the logs and writes `learned.json`, which
the push bridge, history and label services overlay on the private config:

- Cats: the configured cats are the whole household, so every visit is named. A
  one-dimensional k-means over all visits (owner labels pinned, unlabelled visits
  included) learns each cat's typical weight; bands become contiguous at the
  midpoints. Config bands are only the starting prior.
- Deposits: the scale noise floor is learned from quiet empty heartbeats; the
  pee/poop split from labelled visits once at least three of each exist.
- Missed clean: in sensor mode a visit with no cleaning cycle ~12 minutes later
  means the box paused itself (full or missing bin, weight protection): alert.
- Unknown status change: a heartbeat byte that never varied takes a new value on
  two consecutive heartbeats: alert, and the bytes are kept in `alerts.jsonl` so
  the warning field (e.g. bin full) can be decoded when it first happens.
- Bin: replying "emptied" or "full" on the phone records bin events; cleaning cycles
  since emptying are counted, the capacity is learned from "full" reports, and a
  warning goes out at 85 %.

The digest adds bin fill, guess accuracy and >= 5 % weight changes per cat (7-day
median vs the previous 30 days). Weight calibration is not learnable from
unlabelled data; it still needs known weights.

In the box's automatic ("cat") mode a cleaning cycle follows each exit after a
~5.5 minute delay. The heartbeat emitted at that moment carries body byte 2 = 1 and
an `0x0b5a` frame follows about 80 s later; the decoder emits `cleaning_started`
and `cleaning_finished` events (provisional, two cycles observed). Set
`notify_cleaning` in the push config to be told about finished cycles.

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
authentication endpoint during startup. A supervised test
(`deploy/system/offline-test.sh`) blocked only the box's internet for 20 minutes
after dropping its MQTT session: it resolved its MQTT host and reached the local
controller, then retried `iot-auth-global.aliyuncs.com:443` and reassociated with
the hotspot about every 40 s, sending no heartbeats until the block was lifted.
Reconnection therefore needs the HTTPS bootstrap; the service is not cloud-free.
Whether the bootstrap could be served locally depends on whether the box validates
that server's TLS certificate, which has not been tested.

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
`kind=1, subsystem=0x5a, command=0x0d5a`; completed-visit report
`kind=3, subsystem=0x5a, command=0x025a` (body `0003`, duration u16, weight kg, hundredths);
a device frame `command=0x0b5a` with body `0000` follows each automatic cleaning
cycle and is read as its completion. Heartbeat body byte 42 follows the entry sensor, byte 44 the weight-present
state, bytes 16-17 the live scale reading (same kg/hundredths encoding, relative to
the box's own tare: an empty box reads 0.00-0.07 kg and slowly re-zeroes), bytes
14-15 the box clock; byte 8 changes while occupied but does not track weight.
After each completed report the first empty heartbeat yields a `deposit_estimate`
event: the post-exit residual relative to the pre-entry baseline. The push bridge
turns it into "likely pee" (>= 40 g), "likely poop" (15-40 g) or "nothing detected";
these thresholds are a heuristic against ~30 g tare noise and must be scored with
`catlink-history label` before being trusted. Notification texts are deliberately
short: "Cat entered the box", "Joy 6.8 kg, 52 s", "Joy: likely pee (+50 g, 52 s)". The clock body contains zero, year minus
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
