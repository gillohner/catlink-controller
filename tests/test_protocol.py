import json
from datetime import datetime, timezone
from pathlib import Path
import unittest

from catlink_local.protocol import Frame


class ProtocolTests(unittest.TestCase):
    def test_observed_frames(self):
        fixtures = json.loads(Path(__file__).with_name('observed_frames.json').read_text())
        for fixture in fixtures:
            with self.subTest(frame=fixture['hex']):
                wire = bytes.fromhex(fixture['hex'])
                frame = Frame.decode(wire)
                self.assertEqual(frame.kind, fixture['kind'])
                self.assertEqual(frame.command, fixture['command'])
                self.assertEqual(len(frame.body), fixture['body_length'])
                self.assertEqual(frame.encode(), wire)
                for offset in range(len(wire)):
                    corrupted = bytearray(wire)
                    corrupted[offset] ^= 1
                    with self.assertRaises(ValueError):
                        Frame.decode(corrupted)
                for length in range(len(wire)):
                    with self.assertRaises(ValueError):
                        Frame.decode(wire[:length])

    def test_clock_matches_observed_command(self):
        when = datetime(2026, 10, 11, 20, 53, 46, tzinfo=timezone.utc)
        frame = Frame.clock_command(bytes.fromhex('020000000001'), when)
        self.assertEqual(frame.body.hex(), '001a0a0b0714352e')
        self.assertEqual((frame.kind, frame.subsystem, frame.command), (1, 0x5a, 0x0d5a))

    def test_naive_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            Frame.clock_command(bytes(6), datetime(2026, 10, 11))


if __name__ == '__main__':
    unittest.main()
