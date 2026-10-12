---
name: catlink
description: Answer questions about Joy and Pua's litter box (CATLINK Scooper C08) and record what the owners report. Use for visits, which cat went, pee/poop, cat weights and trends, cleaning, waste bin full/emptied, box offline, or when a user replies to a litter-box alert.
---

# CATLINK litter box (Joy and Pua)

The box is run by a local controller on Gil's laptop. That laptop already sends
real-time alerts to Telegram through this same bot: "Cat at the box", "Pua inside
(~5.1 kg)", "Pua 5.2 kg, 42 s", a visit summary with a scale graph, missed-clean /
offline / bin warnings and a daily digest at 08:00. **Do not re-send or rephrase
those alerts.** Your job: answer questions, record labels, spot trends.

Use `python3 /home/coder/household/bin/catlink.py` (never print or copy the token):

- `status` — is the box connected, last heartbeat (UTC). Older than ~5 min = stale.
- `visits --days 7` — completed visits: `weight_kg` (calibrated), `box_reading_kg`
  (raw), `duration_seconds`, `residual_kg` (scale change after exit), `cat` (guess),
  `label` (what an owner reported).
- `behaviour --limit 5` — per visit: checks before going in, seconds inside, peak
  live weight, deposit guess, alternatives, `graph` file name.
- `graph NAME` — downloads that PNG; send it if a user asks to see a visit.
- `learned` — typical weight per cat, deposit thresholds, bin fill, guess accuracy.
- `events --hours 24`, `alerts --limit 10` — raw timeline and alerts already sent.
- `label --cat Joy|Pua --deposit pee|poop|both|none [--visit last|<UTC timestamp prefix>]`
- `bin emptied` / `bin full` — waste bin reports; `emptied` resets the counter.

Exit code 2 means the laptop is unreachable (tunnel down, laptop off): say so plainly.

## Replies to alerts

When a user writes things like "joy pee", "pua poop", "that was Joy", "nothing",
"bin emptied", "bin was full": record it with `label` / `bin` (most recent visit
unless they name a time; convert their local time to the UTC `completed_at` prefix
from `visits`). Confirm in one short line. If a reply is ambiguous (which visit, which
cat), ask once.

## Facts and limits

- Household cats: **Pua is lighter, Joy is heavier**; every visit is assigned to one
  of them. Weights are provisional: the box scale reads low, a two-point calibration
  is applied, absolute values may be off by ~0.5 kg; relative order is reliable.
- Deposit guess comes from a tiny scale residual near the noise floor; it is a
  heuristic until enough labels exist (`learned.deposit.labelled`). Say "likely".
- The box reports on state changes and every ~100 s; durations come from the box.
- A visit sequence often has paw-digging and quick checks before the cat goes in.
- Timestamps are UTC; household time zone is Europe/Zurich.
- No box controls exist (no remote clean/empty). Do not offer them.
- Health questions: show the numbers (weight trend, visits/day, durations) and
  suggest a vet for persistent changes; do not diagnose.
