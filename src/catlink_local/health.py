"""Gateway health and box watchdogs, delivered like visit alerts.

- offline: no heartbeat / controller unreachable beyond a grace period, and recovery
- missed clean: in sensor mode every visit is followed by a cleaning cycle after the
  safe delay; when none starts the box has paused itself (the manual lists a full or
  missing waste bin and weight protection as causes)
- unknown status change: a heartbeat byte that never varied takes a new value and
  keeps it; probably a warning state. Recorded so the field can be decoded later.
- bin: cleaning cycles since the owner reported "emptied", warned before the
  learned capacity is reached
- hourly re-learning (see learn.py) and a daily digest with weight trends

Every alert is appended to alerts.jsonl.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import time
from urllib.error import URLError
from zoneinfo import ZoneInfo

from . import learn
from .history import visits
from .protocol import Frame
from .push import deliver
from .visits import HEARTBEAT

STATE = Path('~/.local/state/catlink-local').expanduser()
# Bytes understood or known to vary in normal operation (clock, live scale, flags).
KNOWN_VARYING = {2, 8, 10, 13, 14, 15, 16, 17, 42, 44}
ANALOG_DISTINCT = 3
MISSED_CLEAN_MARGIN = timedelta(minutes=7)


def controller_status(path):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(path))
        connection.sendall(b'{"op":"status"}\n')
        return json.loads(connection.makefile().readline())


def heartbeat_age(status, now):
    report = status.get('last_report')
    if not status.get('connected') or not report:
        return None
    return (now - datetime.fromisoformat(report['received_at'])).total_seconds()


def append(path, record):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(record) + '\n')


def missed_clean(events, now, safe_delay, clean_times=()):
    """The completed visit whose expected cleaning never started, or None.

    A later entry restarts the box's safe-delay timer, so only the last visit of a
    burst is checked. `clean_times` are cleaning flags read straight from heartbeats,
    which also cover cycles logged before cleaning events existed.
    """
    last_visit = last_entry = None
    last_clean = max(clean_times, default=None)
    for event in events:
        at = datetime.fromisoformat(event['received_at'])
        if event['type'] == 'visit_completed':
            last_visit = event
        elif event['type'] == 'cat_entered':
            last_entry = at
        elif event['type'] in ('cleaning_started', 'cleaning_finished'):
            last_clean = max(last_clean, at) if last_clean else at
    if last_visit is None:
        return None
    done = datetime.fromisoformat(last_visit['received_at'])
    if last_clean and last_clean >= done:
        return None
    if last_entry and last_entry > done:
        return None
    # Visits from before cleaning events were decoded (or long ago) are not judged.
    if now - done > timedelta(hours=2):
        return None
    return last_visit if now - done > safe_delay + MISSED_CLEAN_MARGIN else None


class StatusWatch:
    """Learns which heartbeat bytes are steady and reports persistent new values."""

    def __init__(self):
        self.seen = defaultdict(set)
        self.candidate = {}

    def learn(self, body):
        for index, value in enumerate(body):
            self.seen[index].add(value)

    def watched(self, index):
        return index not in KNOWN_VARYING and len(self.seen[index]) < ANALOG_DISTINCT

    def feed(self, body):
        """[(index, old_values, new_value)] confirmed on two consecutive heartbeats."""
        changes, current = [], {}
        for index, value in enumerate(body):
            if self.watched(index) and value not in self.seen[index]:
                current[index] = value
                if self.candidate.get(index) == value:
                    changes.append((index, sorted(self.seen[index]), value))
        for index, _, value in changes:
            self.seen[index].add(value)
            current.pop(index, None)
        self.candidate = current
        return changes


def heartbeat_bodies(lines):
    for line in lines:
        if not line.strip():
            continue
        observation = json.loads(line)
        if (observation['kind'], observation['subsystem'], observation['command']) != HEARTBEAT:
            continue
        try:
            body = Frame.decode(bytes.fromhex(observation['frame_hex'])).body
        except ValueError:
            continue
        if len(body) == 60:
            yield observation['received_at'], body


def trend(rows, name, now):
    recent = [r['weight_kg'] for r in rows if r['cat'] == name
              and now - datetime.fromisoformat(r['completed_at']) <= timedelta(days=7)]
    before = [r['weight_kg'] for r in rows if r['cat'] == name
              and timedelta(days=7) < now - datetime.fromisoformat(r['completed_at']) <= timedelta(days=37)]
    if len(recent) < 5 or len(before) < 5:
        return None
    a, b = sorted(recent)[len(recent) // 2], sorted(before)[len(before) // 2]
    return round((a - b) / b * 100, 1)


def digest_text(lines, since, until, cats, calibration, zone, learned=None):
    events = [json.loads(line) for line in lines if line.strip()]
    everything = list(visits([json.dumps(e) for e in events], cats, calibration))
    window = [e for e in events if since <= datetime.fromisoformat(e['received_at']) < until]
    rows = [r for r in visits([json.dumps(e) for e in window], cats, calibration)]
    per_cat = Counter(r['cat'] or 'unidentified' for r in rows)
    cleans = sum(e['type'] == 'cleaning_finished' for e in window)
    parts = [f"{len(rows)} visits" + (f" ({', '.join(f'{k} {v}' for k, v in sorted(per_cat.items()))})" if rows else ''),
             f'{cleans} cleans']
    for name in sorted({r['cat'] for r in rows if r['cat']}):
        weights = [r['weight_kg'] for r in rows if r['cat'] == name]
        text = f'{name} {min(weights):.1f}-{max(weights):.1f} kg'
        change = trend(everything, name, until)
        if change is not None and abs(change) >= 5:
            text += f' (weight {change:+.0f}% vs last month)'
        parts.append(text)
    if learned:
        bin_info = learned.get('bin', {})
        if bin_info.get('cleans_since_emptied') is not None:
            capacity = bin_info.get('capacity_cleans')
            parts.append(f"bin {bin_info['cleans_since_emptied']}" + (f'/{capacity}' if capacity else '')
                         + ' cleans since emptied')
        accuracy = learned.get('cat_accuracy', {})
        if accuracy.get('labelled'):
            parts.append(f"cat guesses {accuracy['correct']}/{accuracy['labelled']} right")
    day = since.astimezone(zone).strftime('%a %d %b')
    return f'Digest {day}: ' + '; '.join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path,
                        help='push config; optional keys offline_after_seconds, digest_hour, timezone')
    parser.add_argument('--socket', type=Path, default=STATE / 'control.sock')
    parser.add_argument('--state', type=Path, default=STATE)
    args = parser.parse_args()
    base_config = json.loads(args.config.read_text())
    offline_after = base_config.get('offline_after_seconds', 300)
    # A controller restart drops the box for tens of seconds; only sustained trouble alerts.
    grace = base_config.get('offline_grace_seconds', 120)
    safe_delay = timedelta(minutes=base_config.get('safe_delay_minutes', 5))
    expect_auto_clean = base_config.get('expect_auto_clean', True)
    digest_hour = base_config.get('digest_hour')
    zone = ZoneInfo(base_config.get('timezone', 'Europe/Zurich'))
    log = Path(base_config['event_log']).expanduser()
    telemetry = args.state / 'telemetry.jsonl'
    alerts = args.state / 'alerts.jsonl'
    os.umask(0o077)

    watch = StatusWatch()
    clean_times = []
    offset = 0
    if telemetry.exists():
        with telemetry.open('rb') as stream:
            lines = stream.read().decode(errors='replace').splitlines()
            offset = stream.tell()
        for received_at, body in heartbeat_bodies(lines):
            watch.learn(body)
            if body[2]:
                clean_times.append(datetime.fromisoformat(received_at))
    learned = learn.run(base_config, args.state)
    last_learn = time.monotonic()
    alerted_visit = next((a.get('visit') for a in reversed(learn.jsonl(alerts))
                          if a.get('kind') == 'missed_clean'), None)
    warned_bin_at = None
    offline_since = trouble_since = None
    last_digest_day = datetime.now(zone).date() if digest_hour is not None and \
        datetime.now(zone).hour >= digest_hour else None

    def alert(kind, text, **extra):
        deliver(learn.effective(base_config, args.state), {'type': 'box_offline', 'text': text})
        append(alerts, {'at': datetime.now(timezone.utc).isoformat(), 'kind': kind, 'text': text, **extra})
        print(f'{kind}: {text}', flush=True)

    while True:
        now = datetime.now(timezone.utc)
        config = learn.effective(base_config, args.state)
        try:
            age = heartbeat_age(controller_status(args.socket), now)
            reason = None if age is not None and age < offline_after else \
                ('no heartbeat for %d min' % ((age or 0) // 60) if age is not None else 'box not connected')
        except (OSError, ValueError) as error:
            reason = f'controller unreachable ({type(error).__name__})'
        trouble_since = (trouble_since or now) if reason else None
        if reason and (now - trouble_since).total_seconds() < grace:
            reason = None
        try:
            if reason and offline_since is None:
                offline_since = now
                alert('offline', f'Box monitoring offline: {reason}')
            elif not reason and offline_since is not None and trouble_since is None:
                minutes = int((now - offline_since).total_seconds() // 60)
                offline_since = None
                deliver(config, {'type': 'box_online', 'text': f'Box monitoring back after {minutes} min'})

            # Unknown status changes, from heartbeats appended since the last pass.
            if telemetry.exists() and telemetry.stat().st_size > offset:
                with telemetry.open('rb') as stream:
                    stream.seek(offset)
                    chunk = stream.read()
                complete = chunk[:chunk.rfind(b'\n') + 1]
                offset += len(complete)
                for received_at, body in heartbeat_bodies(complete.decode(errors='replace').splitlines()):
                    local = datetime.fromisoformat(received_at).astimezone(zone)
                    if body[2]:
                        clean_times.append(datetime.fromisoformat(received_at))
                    changes = watch.feed(body)
                    # Date fields may roll over at midnight; that is not a warning.
                    if changes and not (local.hour == 0 and local.minute < 5):
                        detail = ', '.join(f'byte {i}: {old} -> {new}' for i, old, new in changes)
                        alert('status_change', 'Box status changed (not yet decoded). Check the '
                              'warning light: full or missing bin? Reply "full"/"emptied" if so.',
                              detail=detail, body_hex=body.hex())

            # Missed automatic clean.
            events = learn.jsonl(log)
            if expect_auto_clean and offline_since is None:
                visit = missed_clean(events, now, safe_delay, clean_times)
                if visit and visit['received_at'] != alerted_visit:
                    alerted_visit = visit['received_at']
                    when = datetime.fromisoformat(visit['received_at']).astimezone(zone).strftime('%H:%M')
                    alert('missed_clean', f'Box did not clean after the {when} visit. Waste bin full, '
                          f'bin missing or warning light? Reply "emptied" after emptying.',
                          visit=visit['received_at'])

            # Re-learn hourly; warn when the bin approaches its learned capacity.
            if time.monotonic() - last_learn > 3600:
                learned = learn.run(base_config, args.state)
                last_learn = time.monotonic()
            bin_info = learn.bin_state(events, learn.jsonl(args.state / 'bins.jsonl'), learn.jsonl(alerts))
            capacity, used = bin_info['capacity_cleans'], bin_info['cleans_since_emptied']
            if capacity and used is not None and used >= 0.85 * capacity and \
                    warned_bin_at != bin_info['last_emptied']:
                warned_bin_at = bin_info['last_emptied']
                alert('bin_nearly_full', f'Waste bin probably nearly full ({used} of ~{capacity} cleans). '
                      f'Reply "emptied" after emptying.')

            local = now.astimezone(zone)
            if digest_hour is not None and local.hour >= digest_hour and last_digest_day != local.date():
                learned = learn.run(base_config, args.state)
                until = local.replace(hour=digest_hour, minute=0, second=0, microsecond=0)
                lines = log.read_text().splitlines() if log.exists() else []
                deliver(config, {'type': 'digest', 'text': digest_text(
                    lines, until - timedelta(days=1), until, config.get('cats'),
                    config.get('calibration'), zone, learned)})
                last_digest_day = local.date()
        except (OSError, URLError, ValueError) as error:
            print(f'delivery retry: {type(error).__name__}', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
