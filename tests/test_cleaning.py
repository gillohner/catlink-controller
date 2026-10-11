import json
from pathlib import Path
import unittest

from catlink_local.protocol import Frame
from catlink_local.visits import VisitDecoder


class CleaningTests(unittest.TestCase):
    def test_cleaning_start_and_finish_events(self):
        decoder = VisitDecoder()
        heartbeat = bytearray(Frame.decode(bytes.fromhex(json.loads(
            (Path(__file__).parent / 'observed_frames.json').read_text())[0]['hex'])).body)
        mac = bytes.fromhex('020000000001')
        idle = Frame(1, mac, 3, 1, 0x035a, bytes(heartbeat))
        heartbeat[2] = 1
        cleaning = Frame(2, mac, 3, 1, 0x035a, bytes(heartbeat))
        finished = Frame(3, mac, 3, 0x5a, 0x0b5a, b'\0\0')
        events = []
        for frame in (idle, cleaning, cleaning, idle, finished):
            events.extend(decoder.feed(frame, '2026-10-11T21:31:46+00:00'))
        self.assertEqual([e['type'] for e in events], ['cleaning_started', 'cleaning_finished'])


if __name__ == '__main__':
    unittest.main()
