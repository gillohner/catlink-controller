import unittest

from datetime import datetime, timezone
import json

from catlink_local.labels import parse, visit_in_progress


class LabelParseTests(unittest.TestCase):
    def test_messages(self):
        cats = ['Pua', 'Joy']
        self.assertEqual(parse('joy pee', cats), ('Joy', 'pee', 1))
        self.assertEqual(parse('Pua shit', cats), ('Pua', 'poop', 1))
        self.assertEqual(parse('joy both 2', cats), ('Joy', 'both', 2))
        self.assertEqual(parse('none', cats), (None, 'none', 1))
        self.assertEqual(parse('Joy', cats), ('Joy', None, 1))
        self.assertIsNone(parse('hello there', cats))

    def test_visit_in_progress(self):
        now = datetime(2026, 10, 12, 8, 5, tzinfo=timezone.utc)
        entered = json.dumps({'type': 'cat_entered', 'received_at': '2026-10-12T08:00:00+00:00'})
        done = json.dumps({'type': 'visit_completed', 'received_at': '2026-10-12T08:02:00+00:00', 'weight_kg': 4.8})
        self.assertTrue(visit_in_progress([entered], now))
        self.assertFalse(visit_in_progress([entered, done], now))
        self.assertFalse(visit_in_progress([json.dumps({'type': 'cat_entered', 'received_at': '2026-10-12T07:00:00+00:00'})], now))


if __name__ == '__main__':
    unittest.main()
