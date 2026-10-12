#!/usr/bin/env python3
"""CLI for the CATLINK litter-box API on Gil's laptop (reached via reverse SSH tunnel).

  catlink.py status                      connection + last heartbeat
  catlink.py visits [--days 7]           completed visits with cat guess and labels
  catlink.py behaviour [--limit 5]       per-visit behaviour (checks, time inside, deposit guess)
  catlink.py graph NAME [--out FILE]     download a visit graph PNG (NAME from behaviour)
  catlink.py events [--hours 24]         raw decoded events
  catlink.py learned                     learned weights, thresholds, bin fill, accuracy
  catlink.py alerts [--limit 10]         alerts already sent to Telegram
  catlink.py label --cat Joy --deposit pee [--visit last|2026-10-12T10:08]
  catlink.py bin emptied|full
Exit code 2 = laptop unreachable (tunnel down or laptop off): say so, do not guess.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:18090'
TOKEN = (Path.home() / '.config/catlink/api.token').read_text().strip()


def call(path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(BASE + path, data=data, method='POST' if data else 'GET',
                      headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read()
    except HTTPError as error:
        sys.exit(f'error {error.code}: {error.read().decode(errors="replace")}')
    except (URLError, OSError) as error:
        print(f'laptop unreachable: {error}', file=sys.stderr)
        sys.exit(2)
    return payload if raw else json.loads(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('learned')
    sub.add_parser('help')
    p = sub.add_parser('visits'); p.add_argument('--days', type=float, default=7)
    p = sub.add_parser('behaviour'); p.add_argument('--limit', type=int, default=5)
    p.add_argument('--readings', action='store_true')
    p = sub.add_parser('graph'); p.add_argument('name'); p.add_argument('--out')
    p = sub.add_parser('events'); p.add_argument('--hours', type=float, default=24)
    p = sub.add_parser('alerts'); p.add_argument('--limit', type=int, default=10)
    p = sub.add_parser('label'); p.add_argument('--cat'); p.add_argument('--deposit')
    p.add_argument('--visit', default='last'); p.add_argument('--note')
    p = sub.add_parser('bin'); p.add_argument('kind', choices=['emptied', 'full'])
    args = parser.parse_args()
    if args.command == 'graph':
        out = Path(args.out or f'/home/coder/household/data/catlink-{args.name}')
        out.write_bytes(call(f'/graph/{args.name}', raw=True))
        print(out)
        return
    path = {'status': '/status', 'learned': '/learned', 'help': '/help',
            'visits': f'/visits?days={getattr(args, "days", 7)}',
            'behaviour': f'/behaviour?limit={getattr(args, "limit", 5)}&readings={int(getattr(args, "readings", False))}',
            'events': f'/events?hours={getattr(args, "hours", 24)}',
            'alerts': f'/alerts?limit={getattr(args, "limit", 10)}'}.get(args.command)
    if args.command == 'label':
        result = call('/label', {'cat': args.cat, 'deposit': args.deposit, 'visit': args.visit,
                                 'note': args.note})
    elif args.command == 'bin':
        result = call('/bin', {'kind': args.kind})
    else:
        result = call(path)
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
