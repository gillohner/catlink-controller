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
