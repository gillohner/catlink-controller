import asyncio
import json
from pathlib import Path
import unittest

from catlink_local.mqtt import field, packet, read_field, read_packet
from catlink_local.protocol import Frame
from catlink_local.server import Controller


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controller = Controller({'mac': '020000000001', 'timezone': 'Europe/Zurich',
                                     'product_key': 'testproduct', 'device_name': 'testdevice',
                                     'device_ip': '127.0.0.1'})
        self.server = await asyncio.start_server(self.controller.device, '127.0.0.1', 0)
        self.reader, self.writer = await asyncio.open_connection(
            '127.0.0.1', self.server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        self.writer.close()
        await self.writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()

    async def connect(self, username=b'testdevice&testproduct'):
        body = (field(b'MQIsdp') + bytes([3, 0xc2, 0, 120]) + field(b'test-client')
                + field(username) + field(b'private-test-password'))
        self.writer.write(packet(0x10, body))
        await self.writer.drain()

    async def test_real_flow_and_command_ack(self):
        await self.connect()
        self.assertEqual(await read_packet(self.reader), (0x20, b'\0\0'))
        with self.assertRaisesRegex(ValueError, 'subscribed'):
            await self.controller.sync_clock()
        subscription = '/ext/rrpc/+/' + self.controller.prefix + '/user/function/down_cmd'
        self.writer.write(packet(0x82, b'\0\1' + field(subscription.encode()) + b'\1'))
        await self.writer.drain()
        self.assertEqual(await read_packet(self.reader), (0x90, b'\0\1\1'))
        fixtures = json.loads(Path(__file__).with_name('observed_frames.json').read_text())
        report = bytes.fromhex(next(f['hex'] for f in fixtures if f['command'] == 0x035a))
        heartbeat_topic = (self.controller.prefix + '/user/heartbeat/up').encode()
        self.writer.write(packet(0x32, field(heartbeat_topic) + b'\0\3' + report))
        await self.writer.drain()
        self.assertEqual(await read_packet(self.reader), (0x40, b'\0\3'))
        self.assertEqual(self.controller.last_report['frame_hex'], report.hex())
        command = asyncio.create_task(self.controller.sync_clock())
        header, body = await read_packet(self.reader)
        self.assertEqual(header, 0x30)
        topic, offset = read_field(body)
        frame = Frame.decode(body[offset:])
        self.assertEqual(frame.command, 0x0d5a)
        ack = Frame(1, frame.mac, 2, 0x5a, 0x0d5a, b'\0\0').encode()
        self.writer.write(packet(0x32, field(topic) + b'\0\2' + ack))
        await self.writer.drain()
        self.assertEqual(await read_packet(self.reader), (0x40, b'\0\2'))
        self.assertEqual(await command, {'ok': True, 'acknowledged': True})
        self.writer.write(packet(0xc0))
        await self.writer.drain()
        self.assertEqual(await read_packet(self.reader), (0xd0, b''))

    async def test_completed_visit_retransmission_is_not_duplicated(self):
        await self.connect()
        await read_packet(self.reader)
        report = Frame(9, bytes.fromhex('020000000001'), 3, 0x5a,
                       0x025a, bytes.fromhex('000300180354')).encode()
        body = field((self.controller.prefix + '/user/function/up').encode()) + b'\0\7' + report
        for header in (0x32, 0x3a):
            self.writer.write(packet(header, body))
            await self.writer.drain()
            self.assertEqual(await read_packet(self.reader), (0x40, b'\0\7'))
        self.assertEqual(len(self.controller.visit_events), 1)
        self.assertEqual(self.controller.visit_events[0]['weight_kg'], 3.84)
        # A subsequent non-DUP publication can legitimately reuse the packet ID.
        self.writer.write(packet(0x32, body))
        await self.writer.drain()
        await read_packet(self.reader)
        self.assertEqual(len(self.controller.visit_events), 2)

    async def test_live_watch_receives_completed_visit(self):
        admin = await asyncio.start_server(self.controller.admin, '127.0.0.1', 0)
        reader, writer = await asyncio.open_connection('127.0.0.1', admin.sockets[0].getsockname()[1])
        try:
            writer.write(b'{"op":"watch"}\n')
            await writer.drain()
            self.assertTrue(json.loads(await reader.readline())['watching'])
            await self.connect()
            await read_packet(self.reader)
            report = Frame(10, bytes.fromhex('020000000001'), 3, 0x5a,
                           0x025a, bytes.fromhex('000300270451')).encode()
            self.writer.write(packet(0x32, field(b'testproduct/testdevice/user/function/up') + b'\0\4' + report))
            await self.writer.drain()
            await read_packet(self.reader)
            event = json.loads(await asyncio.wait_for(reader.readline(), 1))
            self.assertEqual(event['type'], 'visit_completed')
            self.assertEqual(event['weight_kg'], 4.81)
        finally:
            writer.close()
            await writer.wait_closed()
            admin.close()
            await admin.wait_closed()

    async def test_other_device_identity_is_rejected(self):
        await self.connect(b'otherdevice&testproduct')
        self.assertEqual(await self.reader.read(), b'')
        self.assertIsNone(self.controller.writer)

    async def test_malformed_mqtt_length_is_rejected(self):
        self.writer.write(b'\x10\xff\xff\xff\xff')
        await self.writer.drain()
        self.assertEqual(await self.reader.read(), b'')


if __name__ == '__main__':
    unittest.main()


class StaleSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_replaces_a_dead_socket_and_stops_on_sigterm(self):
        import os
        import signal
        import tempfile
        from catlink_local.server import admin_socket_alive, run
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / 'control.sock'
            import socket
            dead = socket.socket(socket.AF_UNIX)
            dead.bind(str(stale))
            dead.close()  # closing does not unlink: the path stays as a stale socket
            self.assertTrue(stale.exists())
            self.assertFalse(admin_socket_alive(stale))
            config = {'mac': '020000000001', 'timezone': 'Europe/Zurich', 'product_key': 'p',
                      'device_name': 'd', 'device_ip': '127.0.0.1', 'bind': '127.0.0.1',
                      'port': 0, 'admin_socket': str(stale)}
            task = asyncio.create_task(run(config))
            for _ in range(50):
                await asyncio.sleep(0.02)
                if admin_socket_alive(stale):
                    break
            self.assertTrue(admin_socket_alive(stale))
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(task, 5)
            self.assertFalse(stale.exists())
