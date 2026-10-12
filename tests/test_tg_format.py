import unittest

from catlink_local.tg_format import paragraphs, report_caption, text

CONFIG = {'cats': [{'name': 'Pua', 'min_kg': 1.5, 'max_kg': 4.29},
                   {'name': 'Joy', 'min_kg': 4.3, 'max_kg': 14.99}]}


class TelegramFormatTests(unittest.TestCase):
    def test_visit_messages_are_friendly(self):
        self.assertEqual(text({'type': 'activity'}, CONFIG), '🐾 <b>Someone is at the litter box</b>')
        self.assertEqual(text({'type': 'cat_entered', 'live_weight_kg': 3.7}, CONFIG), '🐈 <b>Pua went in</b>')
        self.assertEqual(text({'type': 'visit_completed', 'weight_kg': 4.81, 'duration_seconds': 42}, CONFIG),
                         '✅ <b>Joy is done</b>\n\n⚖️ 4.8 kg\n⏱ 42 seconds in the box')
        self.assertTrue(text({'type': 'deposit_estimate', 'weight_kg': 3.74, 'residual_kg': 0.05}, CONFIG)
                        .startswith('💧 <b>Pua probably peed</b>\n\n'))

    def test_alert_paragraphs_escape_html(self):
        self.assertEqual(paragraphs('⚠️', 'Bin <full>\n\nReply "emptied".'),
                         '⚠️ <b>Bin &lt;full&gt;</b>\n\nReply &quot;emptied&quot;.')

    def test_report_caption(self):
        record = {'cat_guess': 'Pua', 'deposit_guess': 'poop', 'weight_kg': 5.18,
                  'box_duration_seconds': 42, 'checks': 2}
        self.assertEqual(report_caption(record).split('\n\n')[:2],
                         ['💩 <b>Pua probably pooped</b>',
                          '⚖️ 5.2 kg\n⏱ 42 seconds in the box\n👀 Checked 2× before going in'])


if __name__ == '__main__':
    unittest.main()
