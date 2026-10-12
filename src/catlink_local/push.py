"""Durable JSONL-to-ntfy/Telegram delivery. Credentials stay in a private config file."""
import argparse
import base64
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from .learn import effective
from .notify import message


def deliver(config, event):
    backend = config.get('backend', 'ntfy')
    if backend == 'homeassistant_webhook':
        data = json.dumps(event).encode()
        headers = {'Content-Type': 'application/json'}
    elif backend == 'ntfy':
        if event.get('type') == 'deposit_estimate' and not config.get('notify_deposit', True):
            return
        text = message(event, config.get('cats'), config.get('calibration'),
                       config.get('notify_cleaning', False), config.get('deposit'))
        if not text:
            return
        if (config.get('telegram') or {}).get('chat_id'):
            from .telegram import send_text
            prefix = '\u26a0\ufe0f ' if event.get('type') == 'box_offline' else ''
            send_text(config['telegram'], prefix + text)
        if not config.get('url'):
            return
        data = text.encode()
        headers = {'Title': 'Litter box', 'Content-Type': 'text/plain; charset=utf-8'}
        if event.get('type') == 'box_offline':
            headers['Priority'] = 'high'
            headers['Tags'] = 'warning'
    else:
        raise ValueError('unknown notification backend')
    if config.get('token'):
        headers['Authorization'] = 'Bearer ' + config['token']
    elif config.get('username'):
        credentials = f"{config['username']}:{config['password']}".encode()
        headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode()
    request = Request(config['url'], data=data, headers=headers, method='POST')
    try:
        with urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise OSError('destination did not accept event')
    except HTTPError as error:
        error.close()
        raise


ENTRY_QUIET = 600  # seconds


def repeated_entry(event, recent):
    """True for a further "at the box"/"inside" alert within one visit.

    Cats rest their paws, dig and peek before stepping in; each kind of alert goes
    out once per visit. A completed report ends the visit. Events are still logged,
    only the repeated notification is skipped.
    """
    from datetime import datetime
    kind = event.get('type')
    if kind == 'visit_completed':
        recent.clear()
        return False
    if kind not in ('cat_entered', 'activity'):
        return False
    at = datetime.fromisoformat(event['received_at'])
    last = recent.get(kind)
    recent[kind] = at
    return last is not None and (at - last).total_seconds() < ENTRY_QUIET


def send_report(config, event, state):
    """Behaviour summary with the scale graph attached; also logged privately."""
    from .behaviour import build, render, save, summary
    record, points, marks = build(state, event, config)
    png = render(points, marks)
    save(state, record, png)
    if (config.get('telegram') or {}).get('chat_id'):
        from .telegram import send_photo
        send_photo(config['telegram'], png, summary(record))
    if not config.get('url'):
        return
    headers = {'Title': 'Litter box', 'Filename': 'visit.png',
               'Message': summary(record).encode('ascii', 'replace').decode()}
    if config.get('username'):
        credentials = f"{config['username']}:{config['password']}".encode()
        headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode()
    request = Request(config['url'], data=png, headers=headers, method='PUT')
    try:
        with urlopen(request, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise OSError('destination did not accept report')
    except HTTPError as error:
        error.close()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    log = Path(config['event_log']).expanduser()
    cursor = Path(config['cursor']).expanduser()
    cursor.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.umask(0o077)
    # First startup starts at the current end; never notify old training visits.
    offset = int(cursor.read_text()) if cursor.exists() else (log.stat().st_size if log.exists() else 0)
    temporary = cursor.with_suffix('.tmp')
    if not cursor.exists():
        temporary.write_text(str(offset))
        temporary.replace(cursor)
    recent = {}
    while True:
        try:
            if not log.exists():
                time.sleep(1)
                continue
            if log.stat().st_size < offset:
                offset = 0
            with log.open('rb') as stream:
                stream.seek(offset)
                line = stream.readline()
                if not line.endswith(b'\n'):
                    time.sleep(0.5)
                    continue
                event = json.loads(line)
                if repeated_entry(event, recent):
                    pass
                elif event.get('type') == 'deposit_estimate' and config.get('visit_report', True):
                    try:
                        send_report(effective(config), event, log.parent)
                    except (OSError, ValueError, KeyError) as error:
                        # The text line still goes out if the graph cannot be built.
                        print(f'visit report failed: {type(error).__name__}: {error}', flush=True)
                        deliver(effective(config), event)
                else:
                    deliver(effective(config), event)
                offset = stream.tell()
                temporary.write_text(str(offset))
                temporary.replace(cursor)
        except (OSError, ValueError, URLError) as error:
            print(f'Push delivery retry: {type(error).__name__}', flush=True)
            time.sleep(5)


if __name__ == '__main__':
    main()
