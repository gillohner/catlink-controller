"""Small authenticated HTTP API for an assistant agent (e.g. Hermes) on another host.

Binds to localhost only; the agent reaches it through an SSH reverse tunnel. Every
request needs `Authorization: Bearer <token>` (token file, mode 600). Read access
covers status, visits, behaviour records, graphs, learned values and alerts; the only
writes are owner labels and waste-bin reports. No box commands are exposed.
"""
import argparse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from .history import STATE, add_scale_context, load_labels, scale_readings, visits
from .learn import effective, jsonl
from .labels import DEPOSIT_WORDS, record, record_bin

ENDPOINTS = {
    'GET /status': 'controller connection, last heartbeat, live scale',
    'GET /visits?days=7': 'completed visits: calibrated kg, raw box kg, duration, residual, cat guess, owner label',
    'GET /behaviour?limit=20&readings=0': 'per-visit behaviour records (checks, time inside, deposit guess, graph name)',
    'GET /graph/<name>.png': 'scale graph of a visit (name from /behaviour)',
    'GET /events?hours=24': 'raw decoded events (activity, entered, left, completed, deposit, cleaning)',
    'GET /learned': 'learned cat weights, deposit thresholds, bin fill and capacity, guess accuracy',
    'GET /alerts?limit=20': 'alerts sent (offline, missed clean, status change, bin)',
    'POST /label {"visit":"last"|timestamp prefix,"cat":"Joy","deposit":"pee|poop|both|none"}': 'owner label',
    'POST /bin {"kind":"emptied"|"full"}': 'waste-bin report (resets the cleaning counter on emptied)',
}


def controller_status(path):
    import socket
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(path))
        connection.sendall(b'{"op":"status"}\n')
        return json.loads(connection.makefile().readline())


class Handler(BaseHTTPRequestHandler):
    server_version = 'catlink-api'

    def log_message(self, format, *args):  # quiet; systemd journal gets errors only
        pass

    def reply(self, status, body, content_type='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body, indent=1, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorised(self):
        sent = self.headers.get('Authorization', '')
        expected = 'Bearer ' + self.server.token
        if hmac.compare_digest(sent.encode(), expected.encode()):
            return True
        self.reply(401, {'error': 'unauthorised'})
        return False

    def rows(self, days):
        state, config = self.server.state, effective(json.loads(self.server.config.read_text()))
        events_path = state / 'visits.jsonl'
        rows = list(visits(events_path.read_text().splitlines(), config.get('cats'),
                           config.get('calibration'))) if events_path.exists() else []
        telemetry = state / 'telemetry.jsonl'
        if telemetry.exists():
            add_scale_context(rows, scale_readings(telemetry.read_text().splitlines()))
        labels = load_labels(state / 'labels.jsonl')
        since = datetime.now(timezone.utc) - timedelta(days=days)
        out = []
        for row in rows:
            if datetime.fromisoformat(row['completed_at']) >= since:
                row['label'] = labels.get(row['completed_at'])
                out.append(row)
        return out, config

    def do_GET(self):
        if not self.authorised():
            return
        url = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        state = self.server.state
        try:
            if url.path in ('/', '/help'):
                self.reply(200, {'endpoints': ENDPOINTS, 'note': 'weights and guesses are provisional'})
            elif url.path == '/status':
                status = controller_status(state / 'control.sock')
                report = status.get('last_report') or {}
                self.reply(200, {'connected': status.get('connected'), 'subscribed': status.get('subscribed'),
                                 'last_heartbeat': report.get('received_at'),
                                 'recent_events': status.get('visit_events', [])[-10:]})
            elif url.path == '/visits':
                rows, _ = self.rows(float(query.get('days', 7)))
                self.reply(200, rows)
            elif url.path == '/behaviour':
                records = jsonl(state / 'behaviour.jsonl')[-int(query.get('limit', 20)):]
                for item in records:
                    item['graph'] = Path(item['graph']).name if item.get('graph') else None
                    if query.get('readings') != '1':
                        item.pop('readings', None)
                self.reply(200, records)
            elif url.path.startswith('/graph/'):
                name = url.path.rsplit('/', 1)[-1]
                path = state / 'graphs' / name
                if not re.fullmatch(r'visit-[0-9T-]+\.png', name) or not path.exists():
                    self.reply(404, {'error': 'no such graph'})
                else:
                    self.reply(200, path.read_bytes(), 'image/png')
            elif url.path == '/events':
                since = datetime.now(timezone.utc) - timedelta(hours=float(query.get('hours', 24)))
                self.reply(200, [e for e in jsonl(state / 'visits.jsonl')
                                 if datetime.fromisoformat(e['received_at']) >= since])
            elif url.path == '/learned':
                self.reply(200, json.loads((state / 'learned.json').read_text()))
            elif url.path == '/alerts':
                self.reply(200, jsonl(state / 'alerts.jsonl')[-int(query.get('limit', 20)):])
            else:
                self.reply(404, {'error': 'unknown endpoint', 'endpoints': ENDPOINTS})
        except (OSError, ValueError) as error:
            self.reply(500, {'error': f'{type(error).__name__}: {error}'})

    def do_POST(self):
        if not self.authorised():
            return
        url = urlparse(self.path)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 4096:
                raise ValueError('request too large')
            body = json.loads(self.rfile.read(length) or b'{}')
            state = self.server.state
            if url.path == '/label':
                rows, config = self.rows(days=30)
                names = {cat['name'].lower(): cat['name'] for cat in config.get('cats', [])}
                cat = names.get(str(body.get('cat') or '').lower()) if body.get('cat') else None
                if body.get('cat') and cat is None:
                    raise ValueError(f"unknown cat {body['cat']!r}; known: {sorted(names.values())}")
                deposit = DEPOSIT_WORDS.get(str(body.get('deposit') or '').lower()) if body.get('deposit') else None
                if body.get('deposit') and deposit is None:
                    raise ValueError('deposit must be pee, poop, both or none')
                visit = body.get('visit', 'last')
                matches = rows[-1:] if visit == 'last' else [r for r in rows if r['completed_at'].startswith(visit)]
                if len(matches) != 1:
                    raise ValueError(f'{len(matches)} visits match {visit!r}')
                entry = record(state / 'labels.jsonl', matches[0], cat, deposit,
                               body.get('note') or 'via assistant', datetime.now().astimezone().tzinfo,
                               source='assistant')
                self.reply(200, {'labelled': entry})
            elif url.path == '/bin':
                kind = body.get('kind')
                if kind not in ('emptied', 'full'):
                    raise ValueError('kind must be emptied or full')
                record_bin(state / 'bins.jsonl', [kind], body.get('note') or 'via assistant')
                self.reply(200, {'recorded': kind})
            else:
                self.reply(404, {'error': 'unknown endpoint', 'endpoints': ENDPOINTS})
        except (OSError, ValueError) as error:
            self.reply(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path, help='push config (cats, calibration)')
    parser.add_argument('--token-file', required=True, type=Path)
    parser.add_argument('--state', type=Path, default=STATE)
    parser.add_argument('--port', type=int, default=18090)
    args = parser.parse_args()
    os.umask(0o077)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.token = args.token_file.read_text().strip()
    server.state, server.config = args.state, args.config
    server.serve_forever()


if __name__ == '__main__':
    main()
