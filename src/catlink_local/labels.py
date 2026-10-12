"""Label visits from the phone: read short ntfy messages, record them, confirm back.

The owner publishes to a private labels topic from the ntfy app ("joy pee",
"pua poop 2", "none"). Each message labels the most recent completed visit (or the
N-th most recent), and a confirmation goes out on the visits topic. Labels feed
`catlink-history`, which scores the provisional cat and deposit guesses.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .history import STATE, visits
from .push import deliver
from .telegram import updates as tg_updates

DEPOSIT_WORDS = {'pee': 'pee', 'piss': 'pee', 'urine': 'pee', 'wee': 'pee',
                 'poop': 'poop', 'poo': 'poop', 'shit': 'poop', 'crap': 'poop', 'stool': 'poop',
                 'both': 'both', 'none': 'none', 'nothing': 'none', 'unknown': 'unknown'}
PENDING_FOR = timedelta(minutes=20)


def parse(text, cat_names):
    """("Joy", "pee", 1) from "joy pee"; missing parts are None; trailing number = N-th last."""
    words = re.findall(r'[a-zäöüß]+|\d+', text.lower())
    cat = deposit = None
    index = 1
    for word in words:
        if word.isdigit():
            index = max(1, int(word))
        elif word in DEPOSIT_WORDS:
            deposit = DEPOSIT_WORDS[word]
        else:
            for name in cat_names:
                if name.lower() == word:
                    cat = name
    if cat is None and deposit is None:
        return None
    return cat, deposit, index


def record(labels_path, visit, cat, deposit, note, zone, source='phone'):
    entry = {'completed_at': visit['completed_at'], 'cat': cat, 'deposit': deposit,
             'note': note, 'labelled_at': datetime.now(zone).isoformat(timespec='seconds'),
             'source': source}
    labels_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(labels_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(entry) + '\n')
    return entry


def visit_in_progress(lines, now):
    """True while a cat has entered recently and no completed report has followed."""
    entered = completed = None
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        if event['type'] == 'cat_entered':
            entered = datetime.fromisoformat(event['received_at'])
        elif event['type'] == 'visit_completed':
            completed = datetime.fromisoformat(event['received_at'])
    return entered is not None and (completed is None or entered > completed) \
        and now - entered < PENDING_FOR


def poll(config, url, since):
    """Phone messages on a topic newer than `since` (an ntfy message id or a timestamp).

    Notifications published by this project carry a title; untitled messages are
    what the owner typed in the app, so a shared topic works as well as a
    dedicated one.
    """
    credentials = f"{config['username']}:{config['password']}".encode()
    request = Request(f"{url}/json?poll=1&since={since}",
                      headers={'Authorization': 'Basic ' + base64.b64encode(credentials).decode()})
    with urlopen(request, timeout=15) as response:
        for line in response:
            item = json.loads(line)
            if item.get('event') == 'message' and not item.get('title'):
                yield item


BIN_WORDS = {'full': 'full', 'emptied': 'emptied', 'empty': 'emptied', 'changed': 'emptied'}


def bin_report(text):
    """['full', 'emptied'] from "bin was full, emptied"; [] when not about the bin."""
    words = re.findall(r'[a-z]+', text.lower())
    kinds = [BIN_WORDS[w] for w in words if w in BIN_WORDS]
    if not kinds:
        return []
    return sorted(set(kinds), key=['full', 'emptied'].index)


def record_bin(path, kinds, text):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as stream:
        for kind in kinds:
            stream.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'kind': kind,
                                     'note': text, 'source': 'phone'}) + '\n')


def pending_item(item, cat_names, config, pending, bins_path=None):
    kinds = bin_report(item.get('message', ''))
    if kinds and bins_path is not None:
        record_bin(bins_path, kinds, item['message'])
        deliver(config, {'type': 'digest', 'text': 'Noted: waste bin ' + ' and '.join(kinds)
                         + '. Cleaning counter ' + ('reset.' if 'emptied' in kinds else 'kept.')})
        return
    parsed = parse(item.get('message', ''), cat_names)
    if parsed:
        pending.append((datetime.now(timezone.utc), parsed, item['message']))
    else:
        deliver(config, {'type': 'digest', 'text': f"Could not read label '{item.get('message', '')}'. "
                         f"Use e.g. 'joy pee', 'pua poop', 'none', or 'joy both 2'."})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path, help='push config with a "labels" section')
    parser.add_argument('--event-log', type=Path, default=STATE / 'visits.jsonl')
    parser.add_argument('--labels', type=Path, default=STATE / 'labels.jsonl')
    parser.add_argument('--cursor', type=Path, default=STATE / 'labels.cursor')
    parser.add_argument('--bins', type=Path, default=STATE / 'bins.jsonl')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    labels_config = config.get('labels') or {}
    zone = ZoneInfo(config.get('timezone', 'Europe/Zurich'))
    cat_names = [cat['name'] for cat in config.get('cats', [])]
    os.umask(0o077)
    urls = labels_config.get('url') or []
    urls = urls if isinstance(urls, list) else [urls]
    telegram = config.get('telegram') or {}
    # First start ignores history: an old message must not relabel today's visit.
    since = json.loads(args.cursor.read_text()) if args.cursor.exists() else {}
    if not isinstance(since, dict):
        since = {}
    pending = []  # labels sent before their visit's completed report arrived
    while True:
        try:
            for url in urls:
                for item in poll(labels_config, url, since.get(url, str(int(time.time())))):
                    since[url] = item['id']
                    pending_item(item, cat_names, config, pending, args.bins)
            if telegram.get('read_replies'):
                # Only the owners' chats count; anything else sent to the bot is ignored.
                allowed = {str(c) for c in telegram.get('allowed_chat_ids', [telegram['chat_id']])}
                if 'telegram' not in since:
                    # First start: skip messages sent before the service existed.
                    backlog = tg_updates(telegram, None, timeout=0)
                    since['telegram'] = backlog[-1]['update_id'] + 1 if backlog else 0
                for update in tg_updates(telegram, since.get('telegram'), timeout=10):
                    since['telegram'] = update['update_id'] + 1
                    message = update.get('message') or {}
                    if str(message.get('chat', {}).get('id')) in allowed and message.get('text'):
                        pending_item({'message': message['text']}, cat_names, config, pending, args.bins)
            if pending:
                lines = args.event_log.read_text().splitlines() if args.event_log.exists() else []
                now = datetime.now(timezone.utc)
                # A label typed right after "Cat entered" waits for that visit's report.
                if visit_in_progress(lines, now) and now - pending[0][0] < PENDING_FOR:
                    time.sleep(15)
                    continue
                rows = list(visits(lines))
                for sent_at, (cat, deposit, index), text in pending:
                    if len(rows) < index:
                        deliver(config, {'type': 'digest', 'text': f"No visit to label for '{text}'."})
                        continue
                    target = rows[-index]
                    record(args.labels, target, cat, deposit, text, zone)
                    when = datetime.fromisoformat(target['completed_at']).astimezone(zone).strftime('%a %H:%M')
                    deliver(config, {'type': 'digest', 'text': f"Labelled {when} visit: "
                                     f"{cat or '?'}, {deposit or '?'}"})
                pending = []
            # Advance the cursor only once nothing is pending, so a restart re-reads
            # labels that were still waiting for their visit's report.
            args.cursor.write_text(json.dumps(since))
        except (OSError, URLError, ValueError) as error:
            detail = f' {error.code} {error.url}' if isinstance(error, HTTPError) else f' {error}'
            print(f'labels retry: {type(error).__name__}{detail}', flush=True)
            time.sleep(10)
        time.sleep(15)


if __name__ == '__main__':
    main()
