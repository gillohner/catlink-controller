import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import unittest
from urllib.error import HTTPError
from catlink_local.push import deliver

class PushTests(unittest.TestCase):
    def test_http_delivery_and_failure(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get('Authorization'),
                                 self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200 if self.path == '/visits' else 503)
                self.end_headers()
                self.wfile.write(b'{}')
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = {'url': f'http://127.0.0.1:{server.server_port}/visits', 'token': 'test-token'}
            deliver(config, {'type': 'cat_entered'})
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.81})
            deliver(config, {'type': 'cat_left'})
            self.assertEqual(len(received), 2)
            self.assertEqual(received[0], ('/visits', 'Bearer test-token', b'Cat inside'))
            self.assertEqual(received[1][2], b'Cat 4.8 kg')
            config['cats'] = [{'name': 'Pua', 'min_kg': 3.5, 'max_kg': 4.2},
                              {'name': 'Joy', 'min_kg': 4.5, 'max_kg': 5.2}]
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.81, 'duration_seconds': 52})
            self.assertEqual(received[-1][2], b'Joy 4.8 kg, 52 s')
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.35})
            self.assertEqual(received[-1][2], b'Cat 4.3 kg')
            config['cats'][1]['min_kg'] = 4.0  # overlapping bands never name a cat
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.1})
            self.assertEqual(received[-1][2], b'Cat 4.1 kg')
            config['cats'] = [{'name': 'Joy', 'min_kg': 5.8, 'max_kg': 7.5}]
            config['calibration'] = {'slope': 0.729, 'intercept': 0.099}
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.81})
            self.assertEqual(received[-1][2], b'Joy 6.5 kg')
            deliver(config, {'type': 'deposit_estimate', 'weight_kg': 4.81, 'residual_kg': 0.05,
                             'duration_seconds': 52})
            self.assertEqual(received[-1][2], b'Joy: likely pee (+50 g, 52 s)')
            deliver(config, {'type': 'deposit_estimate', 'weight_kg': 4.81, 'residual_kg': 0.02})
            self.assertEqual(received[-1][2], b'Joy: likely poop (+20 g)')
            deliver(config, {'type': 'deposit_estimate', 'weight_kg': 4.81, 'residual_kg': -0.01})
            self.assertEqual(received[-1][2], b'Joy: nothing detected (-10 g)')
            config['notify_deposit'] = False
            deliver(config, {'type': 'deposit_estimate', 'weight_kg': 4.81, 'residual_kg': 0.05})
            self.assertEqual(received[-1][2], b'Joy: nothing detected (-10 g)')
            del config['cats'], config['calibration'], config['notify_deposit']
            config['backend'] = 'homeassistant_webhook'
            deliver(config, {'type': 'cat_left', 'provisional': True})
            self.assertEqual(json.loads(received[-1][2]), {'type': 'cat_left', 'provisional': True})
            config['url'] += '/unavailable' 
            with self.assertRaises(HTTPError):
                deliver(config, {'type': 'cat_entered'})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class EntryDebounceTests(unittest.TestCase):
    def test_peeks_before_a_visit_notify_once(self):
        from catlink_local.push import repeated_entry
        recent = {}
        entry = lambda t: {'type': 'cat_entered', 'received_at': f'2026-10-12T10:{t}+00:00'}
        self.assertFalse(repeated_entry(entry('00:00'), recent))
        self.assertTrue(repeated_entry(entry('00:20'), recent))     # quick check, then back
        self.assertTrue(repeated_entry(entry('01:10'), recent))     # actually goes in
        self.assertFalse(repeated_entry({'type': 'visit_completed', 'received_at': '2026-10-12T10:02:00+00:00'}, recent))
        self.assertFalse(repeated_entry(entry('03:00'), recent))    # the other cat right after
        self.assertFalse(repeated_entry(entry('20:00'), recent))    # a peek much later
