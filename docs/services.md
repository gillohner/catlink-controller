# Continuous operation

Clone the repository to `~/catlink-controller` on the Linux host. Python 3.11+
is sufficient for the controller and push bridge; the supplied systemd units
run from source and do not require pip or a container engine.

Create private `~/.config/catlink-local/` and `~/.local/state/catlink-local/`
(mode 700), copy the example controller and push configs there, and set each
config to mode 600. Use the same event-log path in both. Set the correct device
identity, IP, gateway, and port in the controller config. Keep the clone at the
documented path, or edit the units' `PYTHONPATH`.

```sh
mkdir -p ~/.config/systemd/user
cp deploy/systemd/catlink-{controller,push,health,labels,api}.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now catlink-controller.service catlink-push.service catlink-health.service catlink-labels.service
systemctl --user status catlink-controller.service catlink-push.service catlink-health.service catlink-labels.service
```

Stop any foreground research listener before starting the service on the same
port. The controller stops cleanly on SIGTERM, closes the box's session and removes
its admin socket; a socket left by a hard kill is replaced at start-up only if
nothing answers on it. A restart disconnects the box for 10-40 s; `catlink-health`
waits out a grace period before alerting.

## Root-side pieces

`deploy/system/install-system.sh` installs everything that needs root on an
Arch/Omarchy host: AP interface, hostapd, dnsmasq with the DHCP reservation,
nftables DNAT/NAT, ufw rules, a logind drop-in and user lingering. It reads a
private env file (`deploy/system/system.env.example`). See
[network.md](network.md) for what each piece does. The ntfy server runs as a user
unit (`deploy/systemd/catlink-ntfy.service`, binary in `~/.local/bin`).

Boot order on the verified host: `catlink-ap-interface` (before NetworkManager)
-> NetworkManager brings the 2.4 GHz upstream up -> `catlink-hostapd` and
`catlink-dnsmasq` -> `catlink-nft`; the user units start through lingering.

## Staying awake

The laptop must stay awake; suspending it stops notifications and the gateway.
The installer adds `/etc/systemd/logind.conf.d/50-catlink-lid.conf`
(`HandleLidSwitch*=ignore`, `IdleAction=ignore`) and reloads logind, so closing
the lid only locks the screen. On Omarchy also enable the shell's stay-awake
toggle (`omarchy toggle idle stay-awake`); the idle service otherwise only locks
and starts the screensaver, it does not suspend. Keep the laptop on mains power.
Verify with:

```sh
busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
  org.freedesktop.login1.Manager HandleLidSwitch
loginctl show-user "$USER" -p Linger
```

## Health checks

```sh
PYTHONPATH=src python3 -m catlink_local.client status   # connected/subscribed, last heartbeat
PYTHONPATH=src python3 -m catlink_local.client sync_clock  # must report acknowledged
iw dev gilshare0 station dump                           # the box should be associated
journalctl -u catlink-hostapd -f                        # repeated AP-STA-DISCONNECTED means no internet
```
