import json
import unittest

from catlink_local.history import visits

CATS = [{'name': 'Pua', 'min_kg': 3.2, 'max_kg': 4.3}, {'name': 'Joy', 'min_kg': 4.35, 'max_kg': 5.5}]


class HistoryTests(unittest.TestCase):
    def test_pairs_earliest_entry_with_completed_report(self):
        lines = [json.dumps(e) for e in [
            {'type': 'cat_entered', 'received_at': '2026-10-11T20:00:00+00:00'},
            {'type': 'cat_left', 'received_at': '2026-10-11T20:00:05+00:00'},
            {'type': 'cat_entered', 'received_at': '2026-10-11T20:00:08+00:00'},
            {'type': 'cat_left', 'received_at': '2026-10-11T20:01:30+00:00'},
            {'type': 'visit_completed', 'received_at': '2026-10-11T20:01:35+00:00',
             'weight_kg': 4.81, 'duration_seconds_candidate': 82},
            {'type': 'visit_completed', 'received_at': '2026-10-11T21:00:00+00:00', 'weight_kg': 4.32},
        ]]
        rows = list(visits(lines, CATS))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['entered_at'], '2026-10-11T20:00:00+00:00')
        self.assertEqual(rows[0]['cat'], 'Joy')
        self.assertIsNone(rows[1]['entered_at'])
        self.assertIsNone(rows[1]['cat'])


if __name__ == '__main__':
    unittest.main()
