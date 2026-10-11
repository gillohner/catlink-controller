"""Experimental C08 local endpoint. Only the clock command is enabled."""
import argparse
import asyncio
import contextlib
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket as socketlib
import time
from zoneinfo import ZoneInfo

from .mqtt import field, packet, read_field, read_packet
from .protocol import Frame
from .visits import VisitDecoder


class Controller:
    def __init__(self, config):
        self.config = config
        self.mac = bytes.fromhex(config['mac'].replace(':', ''))
        if len(self.mac) != 6:
            raise ValueError('MAC must contain six bytes')
        self.zone = ZoneInfo(config['timezone'])
        self.prefix = f"{config['product_key']}/{config['device_name']}"
        self.writer = None
        self.subscriptions = set()
        self.last_report = None
        self.observations = deque(maxlen=20)
        self.pending = {}
        self.visits = VisitDecoder()
        self.visit_events = deque(maxlen=100)
        self.watchers = set()

    async def device(self, reader, writer):
        peer = writer.get_extra_info('peername')
        publications = {}
        try:
            if peer[0] != self.config['device_ip']:
                return
            header, body = await read_packet(reader)
            proto, offset = read_field(body)
            if header != 0x10 or len(body) < offset + 4:
                raise ValueError('CONNECT required')
            if (proto, body[offset]) not in ((b'MQIsdp', 3), (b'MQTT', 4)):
                raise ValueError('unsupported MQTT version')
            _, pos = read_field(body, offset + 4)
            flags = body[offset + 1]
            if flags & 4:
                _, pos = read_field(body, pos)
                _, pos = read_field(body, pos)
            if not flags & 128:
                raise ValueError('device identity required')
            username, _ = read_field(body, pos)
            expected = f"{self.config['device_name']}&{self.config['product_key']}".encode()
            if username != expected:
                raise ValueError('unexpected device identity')
            if self.writer:
                self.writer.close()
            self.writer = writer
            self.visits.occupied = None
            self.subscriptions = set()
            writer.write(packet(0x20, b'\x00\x00'))
            await writer.drain()
            while True:
                header, body = await read_packet(reader)
                kind = header >> 4
                if kind == 8 and header & 15 == 2:
                    if len(body) < 3:
                        raise ValueError('short subscription')
                    pos, grants = 2, []
                    while pos < len(body):
                        topic, pos = read_field(body, pos)
                        if pos >= len(body) or body[pos] > 1:
                            raise ValueError('unsupported subscription QoS')
                        self.subscriptions.add(topic.decode())
                        grants.append(body[pos])
                        pos += 1
                    writer.write(packet(0x90, body[:2] + bytes(grants)))
                elif kind == 3:
                    topic, pos = read_field(body)
                    qos = (header >> 1) & 3
                    if qos > 1:
                        raise ValueError('unsupported publication QoS')
                    packet_id = None
                    if qos:
                        if pos + 2 > len(body):
                            raise ValueError('missing packet identifier')
                        packet_id = body[pos:pos + 2]
                        writer.write(packet(0x40, packet_id))
                        pos += 2
                    # A retransmitted QoS 1 publication is acknowledged again, but
                    # must not generate a second completed-visit notification.
                    signature = body
                    if packet_id is not None:
                        if header & 8 and publications.get(packet_id) == signature:
                            await writer.drain()
                            continue
                        publications[packet_id] = signature
                    frame = Frame.decode(body[pos:])
                    if frame.mac != self.mac:
                        raise ValueError('unexpected frame MAC')
                    topic = topic.decode()
                    observation = {'received_at': datetime.now(timezone.utc).isoformat(),
                                   'topic': topic, 'frame_hex': body[pos:].hex(),
                                   'kind': frame.kind, 'subsystem': frame.subsystem,
                                   'command': frame.command}
                    self.observations.append(observation)
                    for event in self.visits.feed(frame, observation["received_at"]):
                        self.visit_events.append(event)
                        if self.config.get('event_log'):
                            path = Path(self.config['event_log']).expanduser()
                            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                            with os.fdopen(fd, 'a') as stream:
                                stream.write(json.dumps(event) + '\n')
                        for queue in tuple(self.watchers):
                            if queue.full():
                                queue.get_nowait()
                            queue.put_nowait(event)
                    if self.config.get('telemetry_log'):
                        path = Path(self.config['telemetry_log']).expanduser()
                        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                        with os.fdopen(fd, 'a') as stream:
                            stream.write(json.dumps(observation) + '\n')
                    if topic == self.prefix + '/user/heartbeat/up':
                        self.last_report = observation
                    future = self.pending.get(topic)
                    if future and not future.done() and (frame.kind, frame.subsystem,
                            frame.command, frame.body) == (2, 0x5a, 0x0d5a, b'\0\0'):
                        future.set_result(True)
                elif header == 0xc0 and not body:
                    writer.write(packet(0xd0))
                elif header == 0xe0 and not body:
                    break
                else:
                    raise ValueError('unsupported MQTT packet')
                await writer.drain()
        except (ValueError, UnicodeError, OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            if self.writer is writer:
                self.writer = None
                self.subscriptions = set()
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def sync_clock(self):
        subscription = '/ext/rrpc/+/' + self.prefix + '/user/function/down_cmd'
        if self.writer is None or subscription not in self.subscriptions:
            raise ValueError('device is not connected and subscribed')
        topic = '/ext/rrpc/' + str(time.time_ns()) + '/' + self.prefix + '/user/function/down_cmd'
        future = asyncio.get_running_loop().create_future()
        self.pending[topic] = future
        try:
            frame = Frame.clock_command(self.mac, datetime.now(self.zone))
            self.writer.write(packet(0x30, field(topic.encode()) + frame.encode()))
            await self.writer.drain()
            await asyncio.wait_for(future, 10)
            return {'ok': True, 'acknowledged': True}
        finally:
            self.pending.pop(topic, None)

    async def admin(self, reader, writer):
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), 5))
            if request.get('op') == 'watch':
                queue = asyncio.Queue(maxsize=100)
                self.watchers.add(queue)
                async def send_events():
                    writer.write(b'{"ok":true,"watching":true}\n')
                    await writer.drain()
                    while True:
                        try:
                            event = await asyncio.wait_for(queue.get(), 30)
                        except TimeoutError:
                            event = {'type': 'keepalive'}
                        writer.write(json.dumps(event).encode() + b'\n')
                        await writer.drain()
                sender = asyncio.create_task(send_events())
                disconnected = asyncio.create_task(reader.read(1))
                try:
                    await asyncio.wait((sender, disconnected), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    sender.cancel()
                    disconnected.cancel()
                    await asyncio.gather(sender, disconnected, return_exceptions=True)
                    self.watchers.discard(queue)
                    writer.close()
                return
            if request.get('op', 'status') == 'status':
                result = {'ok': True, 'connected': self.writer is not None,
                          'subscribed': bool(self.subscriptions), 'last_report': self.last_report,
                          'recent_frames': list(self.observations),
                          'visit_events': list(self.visit_events)}
            elif request['op'] == 'sync_clock':
                result = await self.sync_clock()
            else:
                raise ValueError('unknown operation')
        except (ValueError, KeyError, TimeoutError, OSError) as error:
            result = {'ok': False, 'error': str(error) or type(error).__name__}
        writer.write(json.dumps(result).encode() + b'\n')
        await writer.drain()
        writer.close()


async def run(config):
    os.umask(0o077)
    controller = Controller(config)
    socket = Path(config['admin_socket']).expanduser()
    socket.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A live socket belongs to another daemon and must not be replaced silently.
    # A socket nobody answers on is left over from a non-graceful stop (e.g. a
    # SIGKILL) and would otherwise keep the service crash-looping after a restart.
    if socket.exists():
        if admin_socket_alive(socket):
            raise FileExistsError(f'admin socket already in use: {socket}')
        socket.unlink()
    server = await asyncio.start_server(controller.device, config['bind'], config['port'])
    admin = await asyncio.start_unix_server(controller.admin, socket, limit=4096)
    socket.chmod(0o600)
    stop = asyncio.get_running_loop().create_future()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(
            signum, lambda: stop.done() or stop.set_result(None))
    try:
        await stop
    finally:
        # wait_closed() would otherwise block on the box's long-lived MQTT session.
        if controller.writer is not None:
            controller.writer.close()
        for listener in (server, admin):
            listener.close()
            if hasattr(listener, 'close_clients'):  # Python 3.13+
                listener.close_clients()
        await asyncio.gather(server.wait_closed(), admin.wait_closed(), return_exceptions=True)
        socket.unlink(missing_ok=True)


def admin_socket_alive(path):
    probe = socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM)
    probe.settimeout(1)
    try:
        probe.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(json.loads(args.config.read_text())))


if __name__ == '__main__':
    main()
