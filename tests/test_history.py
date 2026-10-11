import json
import unittest

from datetime import datetime

from catlink_local.history import add_scale_context, visits

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
        self.assertEqual(rows[0]['left_at'], '2026-10-11T20:01:30+00:00')
        self.assertEqual(rows[0]['duration_seconds'], 82)

    def test_scale_context_uses_empty_readings_around_the_visit(self):
        rows = [{'entered_at': '2026-10-11T20:00:30+00:00', 'left_at': '2026-10-11T20:01:30+00:00',
                 'completed_at': '2026-10-11T20:01:35+00:00'}]
        t = lambda s: datetime.fromisoformat(f'2026-10-11T20:{s}+00:00')
        readings = [(t('00:00'), 0.03, 0), (t('00:40'), 4.81, 1), (t('01:00'), 4.85, 1),
                    (t('01:31'), 0.09, 0), (t('03:00'), 0.05, 0), (t('09:00'), 0.0, 0)]
        add_scale_context(rows, readings, window_seconds=360)
        self.assertEqual(rows[0]['baseline_kg'], 0.03)
        self.assertEqual(rows[0]['peak_kg'], 4.85)
        self.assertEqual(rows[0]['residual_kg'], 0.06)
        self.assertEqual(rows[0]['settled_kg'], 0.02)


if __name__ == '__main__':
    unittest.main()
