from datetime import datetime, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from datetime import timedelta

from catlink_local.health import StatusWatch, digest_text, heartbeat_age, missed_clean


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
        self.assertIn('1 cleans', text)
        self.assertIn('Joy 4.8-4.8 kg', text)
        self.assertNotIn('09:00', text)


if __name__ == '__main__':
    unittest.main()


class WatchdogTests(unittest.TestCase):
    def test_missed_clean(self):
        visit = {'type': 'visit_completed', 'received_at': '2026-10-12T08:00:00+00:00', 'weight_kg': 4.8}
        clean = {'type': 'cleaning_started', 'received_at': '2026-10-12T08:05:30+00:00'}
        again = {'type': 'cat_entered', 'received_at': '2026-10-12T08:03:00+00:00'}
        at = lambda m: datetime(2026, 10, 12, 8, m, tzinfo=timezone.utc)
        delay = timedelta(minutes=5)
        self.assertIsNone(missed_clean([visit], at(10), delay))          # still within the delay
        self.assertEqual(missed_clean([visit], at(13), delay), visit)    # nothing started
        self.assertIsNone(missed_clean([visit, clean], at(13), delay))
        self.assertIsNone(missed_clean([visit, again], at(13), delay))   # a new visit restarted it
        self.assertIsNone(missed_clean([visit], at(13) + timedelta(hours=3), delay))
        self.assertIsNone(missed_clean([visit], at(13), delay, [at(6)]))   # flag seen in a heartbeat

    def test_status_watch_needs_two_heartbeats_and_ignores_analog_bytes(self):
        watch = StatusWatch()
        base = bytearray(60)
        for value in (191, 194, 197):
            base[26] = value
            watch.learn(bytes(base))
        changed = bytearray(base)
        changed[30] = 5
        changed[26] = 199
        self.assertEqual(watch.feed(bytes(changed)), [])
        self.assertEqual(watch.feed(bytes(changed)), [(30, [0], 5)])
        self.assertEqual(watch.feed(bytes(changed)), [])
