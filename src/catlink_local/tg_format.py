"""Telegram presentation: friendly wording, bold headline, blank lines (HTML parse mode)."""
from html import escape

from .notify import calibrate, guess_cat, guess_deposit, DEPOSIT_PEE_KG, DEPOSIT_POOP_KG

REPLY_HINT = '<i>Was that right? Reply e.g. "pua poop" or "joy pee".</i>'


def _cat(kg, config):
    return guess_cat(kg, config.get('cats')) or 'A cat'


def _deposit(residual_kg, config):
    deposit = config.get('deposit') or {}
    return guess_deposit(residual_kg, deposit.get('pee_kg', DEPOSIT_PEE_KG),
                         deposit.get('poop_kg', DEPOSIT_POOP_KG))


def deposit_headline(name, guess):
    if guess == 'poop':
        return f'💩 <b>{escape(name)} probably pooped</b>'
    if guess == 'pee':
        return f'💧 <b>{escape(name)} probably peed</b>'
    return f'🐈 <b>{escape(name)} didn\'t leave much behind</b>'


def text(event, config):
    """HTML message for an event, or None when it is not pushed."""
    kind = event.get('type')
    calibration = config.get('calibration')
    if kind == 'activity':
        return '🐾 <b>Someone is at the litter box</b>'
    if kind == 'cat_entered':
        live = event.get('live_weight_kg')
        if live is None or live < 1.5:
            return '🐈 <b>A cat went in</b>'
        return f'🐈 <b>{escape(_cat(calibrate(live, calibration), config))} went in</b>'
    if kind == 'visit_completed':
        kg = calibrate(event['weight_kg'], calibration)
        duration = event.get('duration_seconds') or event.get('duration_seconds_candidate')
        details = f'⚖️ {kg:.1f} kg' + (f'\n⏱ {_duration(duration)}' if duration else '')
        return f'✅ <b>{escape(_cat(kg, config))} is done</b>\n\n{details}'
    if kind == 'deposit_estimate':
        kg = calibrate(event['weight_kg'], calibration)
        return f"{deposit_headline(_cat(kg, config), _deposit(event['residual_kg'], config))}\n\n{REPLY_HINT}"
    if kind == 'cleaning_finished' and config.get('notify_cleaning'):
        return '🧹 <b>The litter box cleaned itself</b>'
    if kind == 'box_offline':
        return paragraphs('⚠️', event['text'])
    if kind in ('box_online', 'digest'):
        icon = {'box_online': '✅'}.get(kind) or event.get('icon', '')
        return paragraphs(icon, event['text'])
    return None


def _duration(seconds):
    if seconds < 90:
        return f'{seconds} seconds in the box'
    return f'{round(seconds / 60)} minutes in the box'


def paragraphs(icon, message):
    """First paragraph bold with the icon; the rest as plain paragraphs."""
    head, _, rest = message.partition('\n\n')
    out = f'{icon} <b>{escape(head)}</b>'.strip()
    return out + (f'\n\n{escape(rest)}' if rest else '')


def report_caption(record):
    """Photo caption for the per-visit report."""
    name = record['cat_guess'] or 'A cat'
    details = [f"⚖️ {record['weight_kg']:.1f} kg"]
    if record.get('box_duration_seconds'):
        details.append(f"⏱ {_duration(record['box_duration_seconds'])}")
    if record.get('checks'):
        details.append(f"👀 Checked {record['checks']}× before going in")
    return f"{deposit_headline(name, record['deposit_guess'])}\n\n" + '\n'.join(details) + f'\n\n{REPLY_HINT}'
