"""Optional Linux desktop consumer of local visit events."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time


def guess_cat(weight_kg, cats):
    """Name the cat only when exactly one configured weight band matches.

    Bands come from the owner's private config after labelled visits; an empty
    or ambiguous match yields None rather than a wrong name. Entry events never
    carry a usable weight, so identity is only ever attached to completed visits.
    """
    matches = [cat['name'] for cat in cats or ()
               if cat['min_kg'] <= weight_kg <= cat['max_kg']]
    return matches[0] if len(matches) == 1 else None


def calibrate(reported_kg, calibration):
    """Invert the box's linear scale error: reading = slope * true + intercept.

    The slope/intercept come from the owner's known-weight tests in private config.
    Without a calibration the reported value is returned unchanged.
    """
    if not calibration:
        return reported_kg
    return round((reported_kg - calibration.get('intercept', 0.0)) / calibration['slope'], 2)


# Deposit heuristic on the post-exit scale residual (kg). Urine clumps absorb litter
# and weigh more than stool; both sit close to the ~30 g tare noise, so this is a
# guess until labelled visits confirm or tune the thresholds.
DEPOSIT_PEE_KG = 0.04
DEPOSIT_POOP_KG = 0.015


def guess_deposit(residual_kg, pee_kg=DEPOSIT_PEE_KG, poop_kg=DEPOSIT_POOP_KG):
    if residual_kg >= pee_kg:
        return 'pee'
    if residual_kg >= poop_kg:
        return 'poop'
    return None


def message(event, cats=None, calibration=None, notify_cleaning=False, deposit=None):
    """Short notification text; None for events that should not be pushed."""
    kind = event.get('type')
    if kind == 'cat_entered':
        return 'Cat entered the box'
    if kind == 'cleaning_finished' and notify_cleaning:
        return 'Box cleaned'
    if kind in ('box_offline', 'box_online', 'digest'):
        return event['text']
    if kind in ('visit_completed', 'deposit_estimate'):
        kg = calibrate(event['weight_kg'], calibration)
        name = guess_cat(kg, cats) or 'Cat'
        duration = event.get('duration_seconds') or event.get('duration_seconds_candidate')
        when = f", {duration} s" if duration else ''
        if kind == 'visit_completed':
            return f"{name} {kg:.1f} kg{when}"
        grams = round(event['residual_kg'] * 1000)
        deposit = deposit or {}
        guess = guess_deposit(event['residual_kg'], deposit.get('pee_kg', DEPOSIT_PEE_KG),
                              deposit.get('poop_kg', DEPOSIT_POOP_KG))
        what = f'likely {guess}' if guess else 'nothing detected'
        return f"{name}: {what} ({grams:+d} g{when})"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', type=Path,
                        default=Path('~/.local/state/catlink-local/control.sock').expanduser())
    args = parser.parse_args()
    while True:
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(str(args.socket))
                connection.sendall(b'{"op":"watch"}\n')
                for line in connection.makefile():
                    event = json.loads(line)
                    text = message(event)
                    if text:
                        subprocess.run(['notify-send', '--app-name=CATLINK',
                                        'CATLINK litter box', text], check=True, timeout=10)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f'Notification consumer: {type(error).__name__}', flush=True)
        time.sleep(3)


if __name__ == '__main__':
    main()
