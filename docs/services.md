# Continuous operation

Clone the repository to `~/catlink-controller` on the Linux host. Python 3.11+
is sufficient for the controller and push bridge; the supplied systemd units
run from source and do not require pip or a container engine.

Create private `~/.config/catlink-local/` and state directories (mode 700), copy
the example controller and push configs there, and set each config to mode 600.
Use the same event-log path in both. Set the correct device identity, IP, gateway,
and port in the controller config. Keep the clone at the documented path, or
edit the units' `PYTHONPATH`.

```sh
mkdir -p ~/.config/systemd/user
cp deploy/systemd/catlink-{controller,push}.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now catlink-controller.service catlink-push.service
systemctl --user status catlink-controller.service catlink-push.service
```

Stop any foreground research listener before starting the service on the same
port. After an abrupt kill, confirm the controller is stopped before removing
its stale Unix socket. Graceful shutdown normally removes it automatically.

The ntfy server also needs a persistent service; use its official installation
instructions with your private config. The Wi-Fi interface, NetworkManager
hotspot, DHCP reservation, firewall, and DNAT need boot persistence independently.
These user units do not create or repair the network.

For service operation before login, enable systemd user lingering for the service
user (`loginctl enable-linger USER`, as administrator). The laptop must stay awake;
closing its lid or suspending it stops notifications and the gateway. Configure
power management deliberately on the dedicated host. No power-management changes
are made by this repository.
