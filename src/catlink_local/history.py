"""Visit history from the persisted event log, with optional per-cat summary."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .notify import calibrate, guess_cat


def visits(lines, cats=None, calibration=None):
    """Pair each completed report with the entry/exit transition that preceded it.

    Brief re-entries produce several transitions and one completed report; the
    entry used is the earliest since the previous completed report.
    """
    entered = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event['type'] == 'cat_entered':
            entered = entered or event['received_at']
        elif event['type'] == 'visit_completed':
            kg = calibrate(event['weight_kg'], calibration)
            yield {'entered_at': entered, 'completed_at': event['received_at'],
                   'weight_kg': kg, 'box_reading_kg': event['weight_kg'],
                   'duration_seconds_candidate': event.get('duration_seconds_candidate'),
                   'cat': guess_cat(kg, cats)}
            entered = None


def main():
    parser = argparse.ArgumentParser(description='Completed litter box visits')
    parser.add_argument('--event-log', type=Path,
                        default=Path('~/.local/state/catlink-local/visits.jsonl').expanduser())
    parser.add_argument('--config', type=Path, help='push config holding the private "cats" bands')
    parser.add_argument('--timezone', default='Europe/Zurich')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text()) if args.config else {}
    cats, calibration = config.get('cats'), config.get('calibration')
    zone = ZoneInfo(args.timezone)
    rows = list(visits(args.event_log.read_text().splitlines(), cats, calibration)) if args.event_log.exists() else []
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    print(f"{'completed (local)':<20} {'weight kg':>9} {'box kg':>7} {'dur s':>6}  cat")
    for row in rows:
        when = datetime.fromisoformat(row['completed_at']).astimezone(zone).strftime('%Y-%m-%d %H:%M:%S')
        print(f"{when:<20} {row['weight_kg']:>9.2f} {row['box_reading_kg']:>7.2f} "
              f"{str(row['duration_seconds_candidate'] or ''):>6}  {row['cat'] or '?'}")
    totals = Counter(row['cat'] or '?' for row in rows)
    print(f"{len(rows)} completed visits" + (': ' + ', '.join(f'{k} {v}' for k, v in sorted(totals.items())) if rows else ''))
    print('Cat names are provisional.' if calibration else 'Weights and cat names are provisional until calibrated.')


if __name__ == '__main__':
    main()
