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
        self.assertEqual([e['type'] for e in events], [
            'cat_entered', 'cat_left', 'visit_completed',
            'cat_entered', 'cat_left', 'cat_entered', 'cat_left', 'visit_completed'])
        completed = [e for e in events if e['type'] == 'visit_completed']
        self.assertEqual([e['weight_kg'] for e in completed], [3.84, 4.81])
        self.assertTrue(all(e['provisional'] for e in events))
