from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from catlink_local.behaviour import build, render, summary
from catlink_local.protocol import Frame

MAC = bytes.fromhex('020000000001')


def heartbeat(kg, sensor, present):
    body = bytearray(60)
    body[16], body[17] = int(kg), round(kg % 1 * 100)
    body[42], body[44] = sensor, present
    return Frame(1, MAC, 3, 1, 0x035a, bytes(body)).encode().hex()


class BehaviourTests(unittest.TestCase):
    def test_record_summary_and_png(self):
        at = lambda s: f'2026-10-12T10:{s}+00:00'
        telemetry = [(at('05:00'), heartbeat(0.0, 0, 0)), (at('07:16'), heartbeat(1.01, 0, 0)),
                     (at('07:20'), heartbeat(3.5, 1, 1)), (at('07:25'), heartbeat(0.3, 0, 0)),
                     (at('07:35'), heartbeat(3.71, 1, 1)), (at('08:08'), heartbeat(0.18, 0, 0)),
                     (at('09:48'), heartbeat(0.03, 0, 0))]
        events = [{'type': 'activity', 'received_at': at('07:16')},
                  {'type': 'cat_entered', 'received_at': at('07:20')},
                  {'type': 'cat_left', 'received_at': at('07:25')},
                  {'type': 'cat_entered', 'received_at': at('07:35')},
                  {'type': 'cat_left', 'received_at': at('08:08')},
                  {'type': 'visit_completed', 'received_at': at('08:27'), 'weight_kg': 3.74,
                   'duration_seconds': 52, 'activity_since': at('07:16')}]
        deposit = {'type': 'deposit_estimate', 'received_at': at('09:48'), 'residual_kg': 0.03,
                   'weight_kg': 3.74, 'duration_seconds': 52}
        config = {'cats': [{'name': 'Pua', 'min_kg': 1.5, 'max_kg': 4.29},
                           {'name': 'Joy', 'min_kg': 4.3, 'max_kg': 14.99}]}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'telemetry.jsonl').write_text(''.join(json.dumps(
                {'received_at': t, 'frame_hex': h, 'kind': 3, 'subsystem': 1, 'command': 0x035a}) + '\n'
                for t, h in telemetry))
            (state / 'visits.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
            record, points, marks = build(state, deposit, config)
        self.assertEqual(record['cat_guess'], 'Pua')
        self.assertEqual(record['checks'], 1)
        self.assertEqual(record['inside_seconds'], 38)
        self.assertEqual(record['deposit_guess'], 'poop')
        self.assertEqual(len(points), 6)  # from two minutes before the first activity
        self.assertTrue(summary(record).startswith('Pua: likely poop (+30 g). 3.7 kg. 1 check before'))
        png = render(points, marks)
        self.assertTrue(png.startswith(b'\x89PNG') and len(png) > 1000)


if __name__ == '__main__':
    unittest.main()
