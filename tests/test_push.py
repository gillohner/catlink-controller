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
            self.assertEqual(received[0], ('/visits', 'Bearer test-token', b'A cat entered the litter box.'))
            self.assertIn(b'4.81 kg', received[1][2])
            self.assertNotIn(b'Probably', received[1][2])
            config['cats'] = [{'name': 'Pua', 'min_kg': 3.5, 'max_kg': 4.2},
                              {'name': 'Joy', 'min_kg': 4.5, 'max_kg': 5.2}]
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.81})
            self.assertTrue(received[-1][2].startswith(b'Probably Joy: 4.81 kg'))
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.35})
            self.assertNotIn(b'Probably', received[-1][2])
            config['cats'][1]['min_kg'] = 4.0
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.1})
            self.assertNotIn(b'Probably', received[-1][2])
            config['cats'] = [{'name': 'Joy', 'min_kg': 5.8, 'max_kg': 7.5}]
            config['calibration'] = {'slope': 0.729, 'intercept': 0.099}
            deliver(config, {'type': 'visit_completed', 'weight_kg': 4.81})
            self.assertEqual(received[-1][2], b'Probably Joy: 6.46 kg (calibrated; box reading 4.81 kg).')
            del config['cats'], config['calibration']
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
