"""Per-visit behaviour record and scale graph, built after the deposit estimate.

The box only sends heartbeats on state changes and every ~100 s, so the graph shows
every reading the box reported around the visit, not a continuous trace. Records go
to behaviour.jsonl and graphs to graphs/<visit>.png (both private state).
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import struct
import zlib

from .learn import jsonl
from .notify import calibrate, guess_cat, guess_deposit, DEPOSIT_PEE_KG, DEPOSIT_POOP_KG
from .protocol import Frame
from .visits import heartbeat_fields

BEFORE = timedelta(minutes=2)


def heartbeats(telemetry_lines, start, end):
    for line in telemetry_lines:
        if not line.strip():
            continue
        observation = json.loads(line)
        at = datetime.fromisoformat(observation['received_at'])
        if not start <= at <= end:
            continue
        try:
            fields = heartbeat_fields(Frame.decode(bytes.fromhex(observation['frame_hex'])))
        except ValueError:
            continue
        if fields:
            yield at, fields


def build(state, deposit_event, config):
    """Behaviour record and plot points for the visit that the deposit estimate closes."""
    state = Path(state).expanduser()
    events = jsonl(state / 'visits.jsonl')
    done = datetime.fromisoformat(deposit_event['received_at'])
    reports = [e for e in events if e['type'] == 'visit_completed'
               and datetime.fromisoformat(e['received_at']) <= done]
    report = reports[-1] if reports else {}
    completed = datetime.fromisoformat(report['received_at']) if report else done
    previous = reports[-2]['received_at'] if len(reports) > 1 else None
    since = report.get('activity_since') or next(
        (e['received_at'] for e in events if e['type'] in ('activity', 'cat_entered')
         and (previous is None or e['received_at'] > previous) and e['received_at'] <= report.get('received_at', '')),
        None)
    start = datetime.fromisoformat(since) if since else completed - timedelta(seconds=report.get('duration_seconds') or 60)
    burst = [e for e in events if start <= datetime.fromisoformat(e['received_at']) <= done]
    telemetry = state / 'telemetry.jsonl'
    lines = telemetry.read_text().splitlines() if telemetry.exists() else []
    points = list(heartbeats(lines, start - BEFORE, done))
    entries = [e for e in burst if e['type'] == 'cat_entered']
    exits = [e for e in burst if e['type'] == 'cat_left']
    inside = 0.0
    for entry in entries:
        out = next((x for x in exits if x['received_at'] > entry['received_at']), None)
        if out:
            inside += (datetime.fromisoformat(out['received_at']) -
                       datetime.fromisoformat(entry['received_at'])).total_seconds()
    cats = config.get('cats') or []
    calibration = config.get('calibration')
    kg = calibrate(report['weight_kg'], calibration) if report else None
    cat = guess_cat(kg, cats) if kg is not None else None
    deposit_config = config.get('deposit') or {}
    pee_kg = deposit_config.get('pee_kg', DEPOSIT_PEE_KG)
    poop_kg = deposit_config.get('poop_kg', DEPOSIT_POOP_KG)
    residual = deposit_event.get('residual_kg')
    learned = {}
    try:
        learned = json.loads((state / 'learned.json').read_text())
    except (OSError, ValueError):
        pass
    usual = {s['name']: s['median_kg'] for s in learned.get('cats', {}).get('stats', [])}
    candidates = [{'cat': c['name'], 'usual_kg': usual.get(c['name']),
                   'band': [c['min_kg'], c['max_kg']]} for c in cats]
    record = {
        'visit_completed_at': report.get('received_at'), 'first_activity_at': since,
        'checks': max(0, len(entries) - 1), 'entries': len(entries),
        'inside_seconds': round(inside), 'box_duration_seconds': report.get('duration_seconds'),
        'peak_live_kg': max((f['live_weight_kg'] for _, f in points), default=None),
        'box_reading_kg': report.get('weight_kg'), 'weight_kg': kg, 'cat_guess': cat,
        'cat_candidates': candidates,
        'residual_kg': residual,
        'deposit_guess': guess_deposit(residual, pee_kg, poop_kg) if residual is not None else None,
        'deposit_thresholds_kg': {'poop': poop_kg, 'pee': pee_kg},
        'readings': [[at.isoformat(), f['live_weight_kg'], f['entry_sensor'], f['weight_present']]
                     for at, f in points],
        'provisional': True}
    marks = [(datetime.fromisoformat(e['received_at']), e['type']) for e in burst]
    return record, points, marks


def summary(record):
    cat = record['cat_guess'] or 'Cat'
    deposit = record['deposit_guess']
    grams = round((record['residual_kg'] or 0) * 1000)
    what = f'likely {deposit}' if deposit else 'nothing detected'
    checks = record['checks']
    others = [c for c in record['cat_candidates'] if c['cat'] != record['cat_guess'] and c['usual_kg']]
    alt = f"; {others[0]['cat']} usually {others[0]['usual_kg']:.1f}" if others else ''
    return (f"{cat}: {what} ({grams:+d} g). {record['weight_kg']:.1f} kg{alt}. "
            f"{checks} check{'s' if checks != 1 else ''} before, inside {record['inside_seconds']} s, "
            f"box {record['box_duration_seconds']} s.")


# --- minimal PNG rendering (no third-party dependencies) ---------------------------

def _png(width, height, pixels):
    raw = b''.join(b'\0' + bytes(pixels[y * width * 3:(y + 1) * width * 3]) for y in range(height))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + \
        struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


FONT = {  # 3x5 digits and a few symbols, rows top to bottom
    '0': '111101101101111', '1': '010110010010111', '2': '111001111100111', '3': '111001111001111',
    '4': '101101111001001', '5': '111100111001111', '6': '111100111101111', '7': '111001001001001',
    '8': '111101111101111', '9': '111101111001111', '.': '000000000000010', ':': '000010000010000',
    'k': '100101110101101', 'g': '011101011001110', ' ': '000000000000000', '-': '000000111000000'}


def render(points, marks, width=720, height=300):
    """Scale readings over time: step line, occupied shading, event markers."""
    pixels = bytearray([255] * width * height * 3)
    left, right, top, bottom = 44, 12, 12, 28

    def put(x, y, colour):
        if 0 <= x < width and 0 <= y < height:
            pixels[(y * width + x) * 3:(y * width + x) * 3 + 3] = bytes(colour)

    def text(x, y, string, colour=(90, 90, 90), scale=2):
        for char in string:
            glyph = FONT.get(char, FONT[' '])
            for i, bit in enumerate(glyph):
                if bit == '1':
                    for dx in range(scale):
                        for dy in range(scale):
                            put(x + (i % 3) * scale + dx, y + (i // 3) * scale + dy, colour)
            x += 4 * scale

    if not points:
        return _png(width, height, pixels)
    t0, t1 = points[0][0], max(points[-1][0], max((m for m, _ in marks), default=points[-1][0]))
    span = max((t1 - t0).total_seconds(), 1)
    top_kg = max(1.0, max(f['live_weight_kg'] for _, f in points) * 1.1)
    xs = lambda t: left + int((t - t0).total_seconds() / span * (width - left - right))
    ys = lambda kg: top + int((1 - max(kg, 0) / top_kg) * (height - top - bottom))
    # occupied shading
    for (a, fa), (b, _) in zip(points, points[1:]):
        if fa['weight_present'] or fa['entry_sensor']:
            for x in range(xs(a), xs(b)):
                for y in range(top, height - bottom):
                    put(x, y, (225, 238, 252))
    # axes and kg gridlines
    for x in range(left, width - right):
        put(x, height - bottom, (120, 120, 120))
    for y in range(top, height - bottom + 1):
        put(left, y, (120, 120, 120))
    step = 1 if top_kg <= 6 else 2
    for kg in range(0, int(top_kg) + 1, step):
        for x in range(left, width - right, 4):
            put(x, ys(kg), (210, 210, 210))
        text(4, ys(kg) - 5, f'{kg}')  # kg
    # event markers: activity orange, entered green, left red, report blue, cleaning grey
    colours = {'activity': (230, 140, 0), 'cat_entered': (30, 160, 60), 'cat_left': (200, 50, 50),
               'visit_completed': (40, 90, 220), 'cleaning_started': (140, 140, 140),
               'deposit_estimate': (150, 60, 170)}
    for at, kind in marks:
        if kind in colours:
            for y in range(top, height - bottom, 2):
                put(xs(at), y, colours[kind])
    # step line of live weight
    for (a, fa), (b, _) in zip(points, points[1:]):
        y = ys(fa['live_weight_kg'])
        for x in range(xs(a), xs(b) + 1):
            for d in (0, 1):
                put(x, y + d, (20, 20, 20))
        ny = ys(_['live_weight_kg'])
        for yy in range(min(y, ny), max(y, ny) + 1):
            put(xs(b), yy, (20, 20, 20))
    for at, f in points:
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                put(xs(at) + dx, ys(f['live_weight_kg']) + dy, (20, 20, 20))
    # time labels (local clock as HH:MM:SS at both ends)
    text(left, height - bottom + 8, t0.astimezone().strftime('%H:%M:%S'))
    label = t1.astimezone().strftime('%H:%M:%S')
    text(width - right - len(label) * 8, height - bottom + 8, label)
    return _png(width, height, pixels)


def save(state, record, png):
    state = Path(state).expanduser()
    graphs = state / 'graphs'
    graphs.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = (record['visit_completed_at'] or datetime.now().isoformat())[:19].replace(':', '')
    path = graphs / f'visit-{stamp}.png'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(png)
    record['graph'] = str(path)
    fd = os.open(state / 'behaviour.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(record) + '\n')
    return path
