# Android notifications

The controller writes entry, exit, and completed-visit events to `event_log`.
`catlink-push` reads that file and POSTs entry and completed-weight messages to
an ntfy server. The controller remains independent of notification outages.

Install ntfy from its official release, verify the published checksum, and use
`deploy/ntfy-server.example.yml` as a starting point. Use absolute private state
paths and an HTTP address reachable from your phone. Start the server once to
initialize its authentication database, then create a restricted account:

```sh
ntfy serve --config /path/to/server.yml
# In another terminal (password is prompted, never commit it):
ntfy user --config /path/to/server.yml add catlink
ntfy access --config /path/to/server.yml catlink catlink-visits rw
```

Install the official ntfy Android app. Add your own server URL, enter the account
credentials, and subscribe to `catlink-visits`. Allow notifications and enable
instant delivery/background operation as offered by the app. The self-hosted
Android connection does not require Firebase. Android battery restrictions and
loss of connectivity can delay delivery; verify with the screen locked.

Copy `deploy/push.example.json` to a private config file (mode 600). Match
`event_log` to the controller configuration. Run:

```sh
catlink-push --config /path/to/push.json
```

The first launch starts at the end of existing history, so historical visits do
not generate training alerts. Later launches resume from the persisted cursor.
Failed HTTP deliveries retry after five seconds. A crash between server acceptance
and cursor persistence can duplicate a notification: delivery is at least once.
Do not rotate or replace the event file while running this experimental consumer.
The server's cache is useful for phone reconnections but is not a confirmation
that Android displayed an alert. Keep the visit history independently.

Local HTTP is intended for the private hotspot. For alerts away from home, use a
VPN or a properly authenticated HTTPS deployment. Do not expose this HTTP port
through the internet router. A VPN must let the phone reach the configured server;
test on mobile data. No remote access has been verified by this project yet.

Official references: [installation](https://docs.ntfy.sh/install/),
[Android and self-hosting configuration](https://docs.ntfy.sh/config/),
[publishing](https://docs.ntfy.sh/publish/).
