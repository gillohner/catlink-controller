"""Self-tuning from the persisted logs: cat weights, deposit thresholds, bin capacity.

Runs inside `catlink-health` and writes `learned.json`; the push bridge, history
and label services overlay it on the private config. Nothing here sends commands.

Cats: the household has exactly the configured cats, so every visit is assigned to
one. A one-dimensional k-means over all completed visits (labelled visits pinned to
their label, unlabelled visits assigned by distance) learns each cat's typical
weight; the dividing line is the midpoint between neighbouring means.

Deposits: the scale's noise floor comes from unlabelled data (drift between
consecutive empty heartbeats with nothing happening in between); "poop" starts at
three times that noise. The pee/poop split needs labelled visits of both kinds.

Bin: cleaning cycles since the owner last reported "emptied"; capacity samples come
from "full" reports (and "emptied" replies shortly after a missed-clean alert).
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from statistics import median

from .notify import DEPOSIT_PEE_KG, DEPOSIT_POOP_KG, calibrate

MIN_PER_CAT = 3
MIN_BOX_KG = 1.5          # the box ignores anything lighter (manual)
MAX_CAT_KG = 15.0
MIN_DEPOSIT_PER_KIND = 3


def jsonl(path):
    path = Path(path).expanduser()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def prior_order(cats):
    """Configured cats from lightest to heaviest, with a prior centre for each."""
    ordered = sorted(cats, key=lambda cat: cat['min_kg'])
    return [(cat['name'], (cat['min_kg'] + cat['max_kg']) / 2) for cat in ordered]


def bands_from_centres(names, centres):
    """Contiguous bands: every plausible weight maps to exactly one cat."""
    cuts = [round((a + b) / 2, 2) for a, b in zip(centres, centres[1:])]
    edges = [MIN_BOX_KG] + cuts + [MAX_CAT_KG]
    return [{'name': name, 'min_kg': edges[i], 'max_kg': round(edges[i + 1] - 0.01, 2)}
            for i, name in enumerate(names)]


def fit_cats(samples, cats):
    """samples: [(kg, label_or_None)]. Returns per-cat stats and contiguous bands."""
    prior = prior_order(cats)
    names = [name for name, _ in prior]
    centres = [centre for _, centre in prior]
    samples = [(kg, label) for kg, label in samples
               if MIN_BOX_KG <= kg <= MAX_CAT_KG and (label is None or label in names)]
    groups = {}
    for _ in range(25):
        groups = {name: [] for name in names}
        for kg, label in samples:
            name = label or min(zip(names, centres), key=lambda nc: abs(kg - nc[1]))[0]
            groups[name].append(kg)
        updated = [median(groups[n]) if groups[n] else c for n, c in zip(names, centres)]
        if updated == centres:
            break
        centres = updated
    stats = []
    for name, centre in zip(names, centres):
        weights = groups[name]
        spread = median(abs(w - centre) for w in weights) * 1.4826 if len(weights) > 1 else None
        stats.append({'name': name, 'n': len(weights), 'median_kg': round(centre, 2),
                      'spread_kg': round(spread, 2) if spread is not None else None})
    enough = all(s['n'] >= MIN_PER_CAT for s in stats) and centres == sorted(centres)
    fitted_centres = centres if enough else [c for _, c in prior]
    return {'learned': enough, 'stats': stats, 'bands': bands_from_centres(names, fitted_centres)}


def scale_noise(readings, busy_times, gap=timedelta(minutes=4)):
    """Robust spread of drift between consecutive quiet empty readings (kg)."""
    diffs = []
    for (t0, w0, b0), (t1, w1, b1) in zip(readings, readings[1:]):
        if b0 or b1 or t1 - t0 > gap:
            continue
        if any(t0 - timedelta(minutes=10) <= t <= t1 for t in busy_times):
            continue
        diffs.append(w1 - w0)
    if len(diffs) < 10:
        return None
    centre = median(diffs)
    # The scale reports hundredths of a kilogram; never claim less noise than that.
    return max(0.01, round(median(abs(d - centre) for d in diffs) * 1.4826, 3))


def fit_deposit(labelled_residuals, noise):
    """labelled_residuals: [(residual_kg, 'pee'|'poop'|'none'|'both')]."""
    poop = max(DEPOSIT_POOP_KG, round(3 * noise, 3)) if noise else DEPOSIT_POOP_KG
    pees = [r for r, kind in labelled_residuals if kind == 'pee']
    poops = [r for r, kind in labelled_residuals if kind == 'poop']
    nones = [r for r, kind in labelled_residuals if kind == 'none']
    pee = max(DEPOSIT_PEE_KG, poop + 0.01)
    learned = False
    if len(pees) >= MIN_DEPOSIT_PER_KIND and len(poops) >= MIN_DEPOSIT_PER_KIND:
        pee = round((median(pees) + median(poops)) / 2, 3)
        learned = True
    if len(nones) >= MIN_DEPOSIT_PER_KIND and len(poops) >= MIN_DEPOSIT_PER_KIND:
        poop = round(max(poop, (median(nones) + median(poops)) / 2), 3)
        learned = True
    return {'pee_kg': max(pee, poop + 0.005), 'poop_kg': poop, 'noise_kg': noise,
            'learned_from_labels': learned, 'labelled': {'pee': len(pees), 'poop': len(poops),
                                                         'none': len(nones)}}


def bin_state(events, bin_events, alerts):
    """Cleans since last emptied, and capacity samples from full / post-alert reports."""
    cleans = sorted(datetime.fromisoformat(e['received_at']) for e in events
                    if e['type'] == 'cleaning_finished')
    marks = sorted((datetime.fromisoformat(b['at']), b['kind']) for b in bin_events)
    alert_times = [datetime.fromisoformat(a['at']) for a in alerts if a.get('kind') == 'missed_clean']
    samples, last_emptied = [], None
    for at, kind in marks:
        after_alert = any(timedelta(0) <= at - t <= timedelta(hours=3) for t in alert_times)
        if last_emptied is not None and (kind == 'full' or (kind == 'emptied' and after_alert)):
            samples.append(sum(last_emptied < c <= at for c in cleans))
        if kind == 'emptied':
            last_emptied = at
    since = sum(c > last_emptied for c in cleans) if last_emptied else None
    return {'cleans_since_emptied': since,
            'last_emptied': last_emptied.isoformat() if last_emptied else None,
            'capacity_cleans': int(median(samples)) if samples else None,
            'capacity_samples': samples}


def run(config, state_dir):
    """Recompute everything from the logs and write learned.json atomically."""
    from .history import add_scale_context, scale_readings, visits, load_labels
    state = Path(state_dir).expanduser()
    events = jsonl(state / 'visits.jsonl')
    calibration = config.get('calibration')
    rows = list(visits([json.dumps(e) for e in events], None, calibration))
    telemetry = state / 'telemetry.jsonl'
    readings = sorted(scale_readings(telemetry.read_text().splitlines())) if telemetry.exists() else []
    add_scale_context(rows, readings)
    labels = load_labels(state / 'labels.jsonl')
    cats = fit_cats([(row['weight_kg'], (labels.get(row['completed_at']) or {}).get('cat'))
                     for row in rows], config.get('cats', []))
    busy = [datetime.fromisoformat(e['received_at']) for e in events]
    noise = scale_noise(readings, busy)
    deposit = fit_deposit([(row['residual_kg'], labels[row['completed_at']]['deposit'])
                           for row in rows if row.get('residual_kg') is not None
                           and (labels.get(row['completed_at']) or {}).get('deposit')], noise)
    bins = bin_state(events, jsonl(state / 'bins.jsonl'), jsonl(state / 'alerts.jsonl'))
    names = {cat['name'] for cat in cats['bands']}
    scored = [(row, labels[row['completed_at']]) for row in rows
              if (labels.get(row['completed_at']) or {}).get('cat') in names]
    from .notify import guess_cat
    correct = sum(guess_cat(row['weight_kg'], cats['bands']) == label['cat'] for row, label in scored)
    learned = {'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'visits': len(rows), 'cats': cats, 'deposit': deposit, 'bin': bins,
               'cat_accuracy': {'correct': correct, 'labelled': len(scored)}}
    path = state / 'learned.json'
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(learned, stream, indent=2)
    temporary.replace(path)
    return learned


def effective(config, state_dir='~/.local/state/catlink-local'):
    """Private config with the learned cat bands and deposit thresholds overlaid."""
    path = Path(state_dir).expanduser() / 'learned.json'
    if not path.exists():
        return config
    try:
        learned = json.loads(path.read_text())
    except ValueError:
        return config
    merged = dict(config)
    if config.get('cats'):
        merged['cats'] = learned['cats']['bands']
    merged['deposit'] = {**learned['deposit'], **(config.get('deposit_override') or {})}
    return merged
