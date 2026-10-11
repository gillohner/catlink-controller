"""Optional Linux desktop consumer of local visit events."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time


def message(event):
    kind = event.get('type')
    if kind == 'cat_entered':
        return 'A cat entered the litter box.'
    if kind == 'visit_completed':
        return f"Visit completed. Estimated weight: {event['weight_kg']:.2f} kg (provisional)."
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
