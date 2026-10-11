# Android notifications

The controller writes entry, exit, and completed-visit events to `event_log`.
`catlink-push` reads that file and POSTs entry and completed-weight messages to
an ntfy server. The controller remains independent of notification outages.

## Server

Install ntfy from its official release and verify the published checksum
(`checksums.txt` next to the release tarball), for example into `~/.local/bin`;
no root is needed. Use `deploy/ntfy-server.example.yml` as a starting point with
absolute private state paths. Run it as a user unit
(`deploy/systemd/catlink-ntfy.service`). Start the server once to initialize its
authentication database, then create two restricted accounts so the bridge
cannot read and the phone cannot publish:

```sh
ntfy user --config /path/to/server.yml add catlink-push   # password prompted
ntfy user --config /path/to/server.yml add phone
ntfy access --config /path/to/server.yml catlink-push catlink-visits wo
ntfy access --config /path/to/server.yml phone catlink-visits ro
ntfy access --config /path/to/server.yml                  # review
```

Quick checks from the host: anonymous publish must return 403, the bridge user
200, and `curl -u phone:... http://HOST:18081/catlink-visits/auth` 200.

## Phone

Install the official ntfy Android app. The verified sequence on the app:

1. Settings -> Manage users -> Add user: service URL exactly
   `http://LAPTOP_LAN_IP:18081` (no trailing slash, plain `http`), user `phone`.
2. Subscribe to topic `catlink-visits`, tick "Use another server", same URL.
3. Settings -> instant delivery on; allow notifications; set the app's battery
   usage to unrestricted.

A "not authorized" error at step 2 while the server shows 200 for the same
credentials means the saved user's URL does not match the subscription URL, or the
password was mistyped; the server log (`log-level: debug`) shows the request as
anonymous in that case. The self-hosted Android connection does not require
Firebase. Android battery restrictions and loss of connectivity can delay
delivery; verify with the screen locked.

## Labelling visits from the phone

Create a second topic the phone may write to and a read-only account for the
label service:

```sh
ntfy access --config /path/to/server.yml phone catlink-labels rw
ntfy user --config /path/to/server.yml add catlink-labeller
ntfy access --config /path/to/server.yml catlink-labeller catlink-labels ro
```

Typing into the visits topic itself is simpler: also grant `phone` write access
to `catlink-visits` and `catlink-labeller` read access, and list both topic URLs in
the `labels.url` array. Project notifications carry a title; untitled messages are
treated as owner input. Add a `labels` section to the push config
(`deploy/push.example.json`) and run `catlink-labels.service`. Messages such as `joy pee`,
`pua poop`, `none`, `joy both 2` (second-most-recent visit) label the completed
visit and are confirmed on the visits topic; a label typed while a visit is in
progress waits for its report. Labels land in `labels.jsonl` and are scored by
`catlink-history`.

## Bridge

Copy `deploy/push.example.json` to a private config file (mode 600). Match
`event_log` to the controller configuration. `url` may use `127.0.0.1` when the
bridge runs on the same host as the server. Run `catlink-push --config ...` or
the `catlink-push.service` user unit.

The first launch starts at the end of existing history, so historical visits do
not generate training alerts. Later launches resume from the persisted cursor.
Failed HTTP deliveries retry after five seconds. A crash between server acceptance
and cursor persistence can duplicate a notification: delivery is at least once.
Do not rotate or replace the event file while running this experimental consumer.
The server's cache is useful for phone reconnections but is not a confirmation
that Android displayed an alert. Keep the visit history independently.

Local HTTP is intended for the private hotspot and the home LAN behind the host
firewall. For alerts away from home, use a VPN or a properly authenticated HTTPS
deployment. Do not expose this HTTP port through the internet router. A VPN must
let the phone reach the configured server; test on mobile data. No remote access
has been verified by this project yet.

Official references: [installation](https://docs.ntfy.sh/install/),
[Android and self-hosting configuration](https://docs.ntfy.sh/config/),
[publishing](https://docs.ntfy.sh/publish/).
