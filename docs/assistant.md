# Telegram alerts and an assistant agent (Hermes)

## Telegram

Add a `telegram` section to the push config with a bot token file (mode 600) and
the chat ID. Every alert the bridge, health and label services send then also goes
to Telegram, and the per-visit report arrives as a photo with the summary as caption.
Remove `url` to stop sending to ntfy. Use a bot dedicated to the litter box: with
`read_replies` the label service long-polls that bot and accepts replies ("joy pee",
"emptied") only from `allowed_chat_ids`. Delivery alone is send-only, so a bot shared
with a conversational agent also works for alerts, but then replies must be relayed
by the agent (two readers of one bot conflict).

## Assistant API

`catlink-api` serves an authenticated JSON API on 127.0.0.1:18090 (bearer token in
a mode-600 file): status, visits, behaviour records, graphs, events, learned values,
alerts, and two writes, owner labels and waste-bin reports. No box commands.

`catlink-assistant-tunnel` keeps `ssh -N -R 127.0.0.1:18090:127.0.0.1:18090 AGENT_HOST`
running, so the agent host reaches the API on its own localhost without any
inbound port on the home network. The agent host needs the token file at
`~/.config/catlink/api.token`.

`deploy/hermes/` holds a small CLI (`catlink.py`) and a Hermes skill describing the
API and how to treat replies such as "joy pee" or "bin emptied". The skill tells
the agent not to duplicate the laptop's real-time alerts.
