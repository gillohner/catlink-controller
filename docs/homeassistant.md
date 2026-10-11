# Optional Home Assistant bridge

Home Assistant is optional. The custom controller still handles the C08's MQTT
and binary protocol; HA consumes decoded events through a local webhook. This
adapter has HTTP delivery tests but has not been verified against a running HA
instance. No motor control button is provided until that command is verified.

Create helpers named `input_boolean.catlink_occupied` and
`input_number.catlink_last_weight` (range 0–20, step 0.01, unit kg) in Home
Assistant. Add the following automation, replacing the webhook ID with a long
random private value. Keep it secret; it authorizes event submission.

```yaml
alias: CATLINK local visit events
mode: queued
triggers:
  - trigger: webhook
    webhook_id: REPLACE_WITH_RANDOM_PRIVATE_ID
    allowed_methods: [POST]
    local_only: true
conditions: []
actions:
  - choose:
      - conditions: "{{ trigger.json.type == 'cat_entered' }}"
        sequence:
          - action: input_boolean.turn_on
            target:
              entity_id: input_boolean.catlink_occupied
      - conditions: "{{ trigger.json.type == 'cat_left' }}"
        sequence:
          - action: input_boolean.turn_off
            target:
              entity_id: input_boolean.catlink_occupied
      - conditions: "{{ trigger.json.type == 'visit_completed' }}"
        sequence:
          - action: input_number.set_value
            target:
              entity_id: input_number.catlink_last_weight
            data:
              value: "{{ trigger.json.weight_kg }}"
```

Copy `deploy/homeassistant.example.json` to a private config (mode 600), enter
HA's reachable LAN address and the matching webhook ID, and match the controller's
event-log path. Run a second bridge process with its own cursor:

```sh
catlink-push --config /path/to/homeassistant.json
```

Use the same service pattern as `catlink-push.service`, but a different service
name and config path. Never share a cursor between destinations. Add helper cards
to your dashboard and automations for your existing HA notification service if
desired. Both helper values are provisional; initial occupancy is unknown until
an observed transition and can become stale while the controller is disconnected.
They must not be used as motor safety interlocks.

Official reference: [Home Assistant webhook triggers and JSON payloads](https://www.home-assistant.io/docs/automation/trigger/#webhook-trigger).
