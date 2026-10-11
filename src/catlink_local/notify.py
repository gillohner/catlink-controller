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


def message(event, cats=None):
    kind = event.get('type')
    if kind == 'cat_entered':
        return 'A cat entered the litter box.'
    if kind == 'visit_completed':
        name = guess_cat(event['weight_kg'], cats)
        who = f"Probably {name}" if name else 'Visit completed'
        return f"{who}: {event['weight_kg']:.2f} kg (provisional weight)."
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
