import json
from pathlib import Path
import unittest
from catlink_local.protocol import Frame
from catlink_local.visits import VisitDecoder

class VisitTests(unittest.TestCase):
    def test_labelled_visits(self):
        decoder = VisitDecoder()
        events = []
        for row in json.loads(Path(__file__).with_name('visit_frames.json').read_text()):
            events.extend(decoder.feed(Frame.decode(bytes.fromhex(row['frame_hex'])), row['received_at']))
        self.assertEqual([e['type'] for e in events if e['type'] != 'deposit_estimate'], [
            'cat_entered', 'cat_left', 'visit_completed',
            'cat_entered', 'cat_left', 'cat_entered', 'cat_left', 'visit_completed'])
        completed = [e for e in events if e['type'] == 'visit_completed']
        self.assertEqual([e['weight_kg'] for e in completed], [3.84, 4.81])
        self.assertTrue(all(e['provisional'] for e in events))

    def test_deposit_estimate_follows_the_first_empty_heartbeat(self):
        from catlink_local.protocol import Frame
        mac = bytes.fromhex('020000000001')
        def heartbeat(seq, kg, sensor, present):
            body = bytearray(60)
            body[16], body[17] = int(kg), round(kg % 1 * 100)
            body[42], body[44] = sensor, present
            return Frame(seq, mac, 3, 1, 0x035a, bytes(body))
        report = Frame(9, mac, 3, 0x5a, 0x025a, bytes([0, 3, 0, 52, 4, 81]))
        decoder = VisitDecoder()
        events = []
        for frame in (heartbeat(1, 0.03, 0, 0), heartbeat(2, 0.02, 0, 0), heartbeat(3, 4.8, 1, 1),
                      heartbeat(4, 0.30, 0, 0), report, heartbeat(5, 0.07, 0, 0), heartbeat(6, 0.06, 0, 0)):
            events.extend(decoder.feed(frame, 't'))
        deposits = [e for e in events if e['type'] == 'deposit_estimate']
        self.assertEqual(len(deposits), 1)
        self.assertEqual(deposits[0]['residual_kg'], 0.05)   # 0.07 after minus 0.02 before entry
        self.assertEqual(deposits[0]['weight_kg'], 4.81)
        self.assertEqual(deposits[0]['duration_seconds'], 52)

    def test_paws_on_the_scale_before_the_sensor_are_not_a_baseline(self):
        from catlink_local.protocol import Frame
        mac = bytes.fromhex('020000000001')
        def heartbeat(seq, kg, sensor, present):
            body = bytearray(60)
            body[16], body[17] = int(kg), round(kg % 1 * 100)
            body[42], body[44] = sensor, present
            return Frame(seq, mac, 3, 1, 0x035a, bytes(body))
        report = Frame(9, mac, 3, 0x5a, 0x025a, bytes([0, 3, 0, 42, 3, 74]))
        decoder = VisitDecoder()
        events = []
        # Observed 2026-10-12: 1.01 kg with both flags clear right before the entry.
        for frame in (heartbeat(1, 0.0, 0, 0), heartbeat(2, 1.01, 0, 0), heartbeat(3, 1.16, 1, 0),
                      heartbeat(4, 3.71, 1, 1), heartbeat(5, 0.18, 0, 0), report, heartbeat(6, 0.03, 0, 0)):
            events.extend(decoder.feed(frame, 't'))
        deposits = [e for e in events if e['type'] == 'deposit_estimate']
        self.assertEqual([d['residual_kg'] for d in deposits], [0.03])
