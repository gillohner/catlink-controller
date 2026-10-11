"""Local Unix-socket administration; no cloud account credentials."""
import argparse
import json
from pathlib import Path
import socket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['status', 'sync_clock', 'watch'])
    parser.add_argument('--socket', type=Path,
                        default=Path('~/.local/state/catlink-local/control.sock').expanduser())
    args = parser.parse_args()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(args.socket))
        connection.sendall(json.dumps({'op': args.operation}).encode() + b'\n')
        stream = connection.makefile()
        response = json.loads(stream.readline())
        if args.operation == 'watch' and response.get('ok'):
            for line in stream:
                print(line.rstrip(), flush=True)
            return
    print(json.dumps(response, indent=2))
    if not response['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
