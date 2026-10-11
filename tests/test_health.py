from datetime import datetime, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from catlink_local.health import digest_text, heartbeat_age


class HealthTests(unittest.TestCase):
    def test_heartbeat_age(self):
        now = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
        self.assertIsNone(heartbeat_age({'connected': False, 'last_report': None}, now))
        status = {'connected': True, 'last_report': {'received_at': '2026-10-12T07:55:00+00:00'}}
        self.assertEqual(heartbeat_age(status, now), 300)

    def test_digest_counts_visits_cats_and_cleans(self):
        events = [
            {'type': 'cat_entered', 'received_at': '2026-10-11T22:00:00+00:00'},
            {'type': 'cat_left', 'received_at': '2026-10-11T22:00:40+00:00'},
            {'type': 'visit_completed', 'received_at': '2026-10-11T22:00:50+00:00', 'weight_kg': 4.81},
            {'type': 'cleaning_finished', 'received_at': '2026-10-11T22:07:00+00:00'},
            {'type': 'visit_completed', 'received_at': '2026-10-12T03:00:00+00:00', 'weight_kg': 3.84},
            {'type': 'visit_completed', 'received_at': '2026-10-12T09:00:00+00:00', 'weight_kg': 3.84},
        ]
        cats = [{'name': 'Pua', 'min_kg': 3.5, 'max_kg': 4.2}, {'name': 'Joy', 'min_kg': 4.5, 'max_kg': 5.2}]
        text = digest_text([json.dumps(e) for e in events],
                           datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc),
                           datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc), cats, None, ZoneInfo('UTC'))
        self.assertIn('2 visits (Joy 1, Pua 1)', text)
        self.assertIn('1 cleaning cycles', text)
        self.assertIn('Joy 4.81-4.81 kg', text)
        self.assertNotIn('09:00', text)


if __name__ == '__main__':
    unittest.main()
