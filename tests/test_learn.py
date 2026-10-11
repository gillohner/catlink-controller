from datetime import datetime, timedelta, timezone
import unittest

from catlink_local.learn import bin_state, fit_cats, fit_deposit, scale_noise

CATS = [{'name': 'Pua', 'min_kg': 4.4, 'max_kg': 6.0}, {'name': 'Joy', 'min_kg': 6.1, 'max_kg': 8.0}]


class LearnTests(unittest.TestCase):
    def test_cats_learn_from_unlabelled_visits_and_cover_every_weight(self):
        prior = fit_cats([], CATS)
        self.assertFalse(prior['learned'])
        self.assertEqual(prior['bands'][0]['min_kg'], 1.5)
        samples = [(4.9, None), (5.0, None), (5.1, 'Pua'), (6.2, None), (6.3, 'Joy'), (6.4, None),
                   (1.3, None), (3.2, 'object')]
        fitted = fit_cats(samples, CATS)
        self.assertTrue(fitted['learned'])
        self.assertEqual([s['median_kg'] for s in fitted['stats']], [5.0, 6.3])
        self.assertEqual(fitted['bands'][0]['max_kg'], 5.64)
        self.assertEqual(fitted['bands'][1]['min_kg'], 5.65)

    def test_deposit_thresholds(self):
        self.assertEqual(fit_deposit([], None)['poop_kg'], 0.015)
        self.assertEqual(fit_deposit([], 0.01)['poop_kg'], 0.03)
        labelled = [(0.06, 'pee'), (0.07, 'pee'), (0.05, 'pee'), (0.02, 'poop'), (0.025, 'poop'), (0.03, 'poop')]
        self.assertEqual(fit_deposit(labelled, 0.005)['pee_kg'], 0.042)

    def test_noise_ignores_busy_periods(self):
        t0 = datetime(2026, 10, 12, tzinfo=timezone.utc)
        readings = [(t0 + timedelta(seconds=100 * i), 0.03 + (0.01 if i % 2 else 0), False) for i in range(20)]
        self.assertEqual(scale_noise(readings, []), 0.01)
        self.assertIsNone(scale_noise(readings[:5], []))

    def test_bin_capacity_from_full_reports(self):
        at = lambda h: (datetime(2026, 10, 12, tzinfo=timezone.utc) + timedelta(hours=h)).isoformat()
        events = [{'type': 'cleaning_finished', 'received_at': at(h)} for h in range(1, 30)]
        bins = [{'at': at(0.5), 'kind': 'emptied'}, {'at': at(20.5), 'kind': 'full'},
                {'at': at(20.6), 'kind': 'emptied'}]
        state = bin_state(events, bins, [])
        self.assertEqual(state['capacity_cleans'], 20)
        self.assertEqual(state['cleans_since_emptied'], 9)


if __name__ == '__main__':
    unittest.main()
