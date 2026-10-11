"""Durable JSONL-to-ntfy delivery. Credentials stay in a private config file."""
import argparse
import base64
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from .notify import message


def deliver(config, event):
    backend = config.get('backend', 'ntfy')
    if backend == 'homeassistant_webhook':
        data = json.dumps(event).encode()
        headers = {'Content-Type': 'application/json'}
    elif backend == 'ntfy':
        text = message(event, config.get('cats'))
        if not text:
            return
        data = text.encode()
        headers = {'Title': 'CATLINK litter box', 'Content-Type': 'text/plain; charset=utf-8'}
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
                deliver(config, event)
                offset = stream.tell()
                temporary.write_text(str(offset))
                temporary.replace(cursor)
        except (OSError, ValueError, URLError) as error:
            print(f'Push delivery retry: {type(error).__name__}', flush=True)
            time.sleep(5)


if __name__ == '__main__':
    main()
