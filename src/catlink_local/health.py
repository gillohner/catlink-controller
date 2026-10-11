"""Gateway health: box-offline alerts and a daily digest, delivered like visit alerts.

Polls the controller's admin socket. A silent gateway otherwise looks exactly like
cats that did not visit, so the absence of heartbeats is reported once, and the
recovery once. The digest summarises the previous 24 hours from the event log.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import time
from urllib.error import URLError
from zoneinfo import ZoneInfo

from .history import visits
from .push import deliver


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


def digest_text(lines, since, until, cats, calibration, zone):
    events = [json.loads(line) for line in lines if line.strip()]
    window = [e for e in events if since <= datetime.fromisoformat(e['received_at']) < until]
    rows = [r for r in visits([json.dumps(e) for e in window], cats, calibration)]
    per_cat = Counter(r['cat'] or 'unidentified' for r in rows)
    cleans = sum(e['type'] == 'cleaning_finished' for e in window)
    parts = [f"{len(rows)} visits" + (f" ({', '.join(f'{k} {v}' for k, v in sorted(per_cat.items()))})" if rows else ''),
             f'{cleans} cleaning cycles']
    for name in sorted({r['cat'] for r in rows if r['cat']}):
        weights = [r['weight_kg'] for r in rows if r['cat'] == name]
        parts.append(f'{name} {min(weights):.2f}-{max(weights):.2f} kg')
    day = since.astimezone(zone).strftime('%a %d %b')
    return f'Daily digest {day}: ' + '; '.join(parts) + '. Weights provisional.'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path,
                        help='push config; optional keys offline_after_seconds, digest_hour, timezone')
    parser.add_argument('--socket', type=Path,
                        default=Path('~/.local/state/catlink-local/control.sock').expanduser())
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    offline_after = config.get('offline_after_seconds', 300)
    # A controller restart drops the box for tens of seconds; only sustained trouble alerts.
    grace = config.get('offline_grace_seconds', 120)
    digest_hour = config.get('digest_hour')
    zone = ZoneInfo(config.get('timezone', 'Europe/Zurich'))
    log = Path(config['event_log']).expanduser()
    offline_since = trouble_since = None
    last_digest_day = datetime.now(zone).date() if digest_hour is not None and \
        datetime.now(zone).hour >= digest_hour else None
    while True:
        now = datetime.now(timezone.utc)
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
                deliver(config, {'type': 'box_offline',
                                 'text': f'ALERT: litter box monitoring is offline: {reason}.'})
                print(f'offline: {reason}', flush=True)
            elif not reason and offline_since is not None and trouble_since is None:
                minutes = int((now - offline_since).total_seconds() // 60)
                offline_since = None
                deliver(config, {'type': 'box_online',
                                 'text': f'Litter box monitoring is back online after {minutes} min.'})
                print('online', flush=True)
            local = now.astimezone(zone)
            if digest_hour is not None and local.hour >= digest_hour and last_digest_day != local.date():
                until = local.replace(hour=digest_hour, minute=0, second=0, microsecond=0)
                lines = log.read_text().splitlines() if log.exists() else []
                deliver(config, {'type': 'digest', 'text': digest_text(
                    lines, until - timedelta(days=1), until, config.get('cats'),
                    config.get('calibration'), zone)})
                last_digest_day = local.date()
                print('digest sent', flush=True)
        except (OSError, URLError, ValueError) as error:
            print(f'delivery retry: {type(error).__name__}', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
