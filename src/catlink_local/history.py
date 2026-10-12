"""Visit history from the persisted logs: weights, durations, scale residuals, labels.

`catlink-history` lists completed visits; `catlink-history label` records what the
owner observed (which cat, what was deposited) so the weight bands and any
deposit heuristics can be checked against reality instead of assumed.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .notify import calibrate, guess_cat
from .protocol import Frame
from .visits import EMPTY_MAX_KG, heartbeat_fields

STATE = Path('~/.local/state/catlink-local').expanduser()
DEPOSITS = ('pee', 'poop', 'both', 'none', 'unknown')


def visits(lines, cats=None, calibration=None):
    """Pair each completed report with the entry/exit transitions that preceded it.

    Brief re-entries produce several transitions and one completed report; the
    entry used is the earliest since the previous completed report, the exit the
    latest.
    """
    entered = left = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event['type'] == 'cat_entered':
            entered = entered or event['received_at']
        elif event['type'] == 'cat_left':
            left = event['received_at']
        elif event['type'] == 'visit_completed':
            kg = calibrate(event['weight_kg'], calibration)
            yield {'entered_at': entered, 'left_at': left, 'completed_at': event['received_at'],
                   'weight_kg': kg, 'box_reading_kg': event['weight_kg'],
                   'duration_seconds': event.get('duration_seconds',
                                                 event.get('duration_seconds_candidate')),
                   'cat': guess_cat(kg, cats)}
            entered = left = None


def scale_readings(telemetry_lines):
    """(timestamp, live weight, busy) from heartbeat frames in the telemetry log.

    `busy` is set when either the entry sensor or the weight-present flag is active,
    so readings taken while something is being placed or removed are not treated
    as empty-box baselines.
    """
    for line in telemetry_lines:
        line = line.strip()
        if not line:
            continue
        observation = json.loads(line)
        try:
            fields = heartbeat_fields(Frame.decode(bytes.fromhex(observation['frame_hex'])))
        except ValueError:
            continue
        if fields:
            yield (datetime.fromisoformat(observation['received_at']),
                   fields['live_weight_kg'], bool(fields['weight_present'] or fields['entry_sensor']
                                                  or fields['live_weight_kg'] >= EMPTY_MAX_KG))


def add_scale_context(rows, readings, window_seconds=360):
    """Attach the tare-relative scale readings around each visit.

    `baseline_kg` is the last empty reading before entry, `peak_kg` the largest
    reading while occupied, `residual_kg` the first empty reading after exit minus
    the baseline (a deposit candidate, near the ~50 g noise floor), `settled_kg`
    the last reading inside the window. All provisional.
    """
    readings = sorted(readings)
    for row in rows:
        if not row['entered_at'] or not row['left_at']:
            continue
        entered = datetime.fromisoformat(row['entered_at'])
        left = datetime.fromisoformat(row['left_at'])
        before = [w for t, w, busy in readings if t < entered and not busy]
        during = [w for t, w, _ in readings if entered <= t <= left]
        after = [w for t, w, busy in readings
                 if left < t <= left + timedelta(seconds=window_seconds) and not busy]
        row['baseline_kg'] = before[-1] if before else None
        row['peak_kg'] = max(during) if during else None
        if before and after:
            row['residual_kg'] = round(after[0] - before[-1], 2)
            row['settled_kg'] = round(after[-1] - before[-1], 2)
    return rows


def load_labels(path):
    labels = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                label = json.loads(line)
                labels[label['completed_at']] = label
    return labels


def main():
    parser = argparse.ArgumentParser(description='Completed litter box visits')
    parser.add_argument('--event-log', type=Path, default=STATE / 'visits.jsonl')
    parser.add_argument('--telemetry-log', type=Path, default=STATE / 'telemetry.jsonl')
    parser.add_argument('--labels', type=Path, default=STATE / 'labels.jsonl')
    parser.add_argument('--config', type=Path, help='push config holding private "cats"/"calibration"')
    parser.add_argument('--timezone', default='Europe/Zurich')
    parser.add_argument('--json', action='store_true')
    sub = parser.add_subparsers(dest='command')
    label = sub.add_parser('label', help='record the observed cat/deposit for a visit')
    label.add_argument('--visit', default='last',
                       help='"last" or a prefix of the completed_at timestamp (e.g. 2026-10-11T21:37)')
    label.add_argument('--cat')
    label.add_argument('--deposit', choices=DEPOSITS)
    label.add_argument('--note')
    args = parser.parse_args()

    from .learn import effective
    config = effective(json.loads(args.config.read_text())) if args.config else {}
    cats, calibration = config.get('cats'), config.get('calibration')
    zone = ZoneInfo(args.timezone)
    rows = list(visits(args.event_log.read_text().splitlines(), cats, calibration)) \
        if args.event_log.exists() else []
    if args.telemetry_log.exists():
        add_scale_context(rows, scale_readings(args.telemetry_log.read_text().splitlines()))
    labels = load_labels(args.labels)

    if args.command == 'label':
        if not rows:
            raise SystemExit('no completed visits yet')
        matches = rows[-1:] if args.visit == 'last' else \
            [r for r in rows if r['completed_at'].startswith(args.visit)]
        if len(matches) != 1:
            raise SystemExit(f'{len(matches)} visits match {args.visit!r}; be more specific')
        entry = {'completed_at': matches[0]['completed_at'], 'cat': args.cat,
                 'deposit': args.deposit, 'note': args.note,
                 'labelled_at': datetime.now(zone).isoformat(timespec='seconds')}
        args.labels.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(args.labels, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps(entry) + '\n')
        print('labelled', entry['completed_at'], entry['cat'], entry['deposit'])
        return

    for row in rows:
        row['label'] = labels.get(row['completed_at'])
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    fmt = lambda v, w=6: f'{v:>{w}.2f}' if isinstance(v, (int, float)) else ' ' * (w - 1) + '-'
    print(f"{'completed (local)':<20} {'kg':>6} {'box':>6} {'dur s':>6} {'resid':>6} {'settl':>6}  guess   label        deposit")
    for row in rows:
        when = datetime.fromisoformat(row['completed_at']).astimezone(zone).strftime('%Y-%m-%d %H:%M:%S')
        label = row['label'] or {}
        print(f"{when:<20} {fmt(row['weight_kg'])} {fmt(row['box_reading_kg'])} "
              f"{str(row['duration_seconds'] or ''):>6} {fmt(row.get('residual_kg'))} "
              f"{fmt(row.get('settled_kg'))}  {row['cat'] or '?':<7} {label.get('cat') or '':<12} "
              f"{label.get('deposit') or ''}")
    totals = Counter(row['cat'] or '?' for row in rows)
    print(f"{len(rows)} completed visits" + (': ' + ', '.join(f'{k} {v}' for k, v in sorted(totals.items())) if rows else ''))
    names = {cat['name'] for cat in cats or ()}
    # Calibration objects and other non-cat labels are not cat-guess outcomes.
    checked = [r for r in rows if r['label'] and r['label'].get('cat') in names]
    if checked:
        right = sum(r['cat'] == r['label']['cat'] for r in checked)
        print(f'cat guess vs label: {right}/{len(checked)} correct')
    print('Cat names are provisional.' if calibration else 'Weights and cat names are provisional until calibrated.')


if __name__ == '__main__':
    main()
