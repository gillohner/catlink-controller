import json
from pathlib import Path
import struct
import tempfile
import unittest

from catlink_local.mqtt import field, packet
from catlink_local.pcap_frames import decode

FIXTURES = json.loads((Path(__file__).parent / 'observed_frames.json').read_text())


def tcp_segment(src, dst, sport, dport, seq, payload):
    tcp = struct.pack('>HHIIBBHHH', sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    total = 20 + len(tcp)
    ip = struct.pack('>BBHHHBBH4s4s', 0x45, 0, total, 0, 0, 64, 6, 0,
                     bytes(map(int, src.split('.'))), bytes(map(int, dst.split('.'))))
    return b'\0' * 12 + b'\x08\x00' + ip + tcp


def write_pcap(path, frames):
    out = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    for index, raw in enumerate(frames):
        out += struct.pack('<IIII', 1700000000 + index, 0, len(raw), len(raw)) + raw
    path.write_bytes(out)


class PcapFrameTests(unittest.TestCase):
    def test_publications_are_decoded_in_both_directions_and_split_segments(self):
        up = bytes.fromhex(FIXTURES[0]['hex'])
        publish = packet(0x30, field(b'/pk/dev/user/heartbeat/up') + up)
        # Split one publication across two TCP segments to exercise reassembly.
        cut = len(publish) // 2
        down = packet(0x32, field(b'/ext/rrpc/1/pk/dev/user/function/down_cmd') + b'\0\1' + up)
        with tempfile.TemporaryDirectory() as directory:
            pcap = Path(directory) / 'session.pcap'
            write_pcap(pcap, [
                tcp_segment('10.42.0.17', '1.2.3.4', 50000, 1883, 1, publish[:cut]),
                tcp_segment('1.2.3.4', '10.42.0.17', 1883, 50000, 1, down),
                tcp_segment('10.42.0.17', '1.2.3.4', 50000, 1883, 1 + cut, publish[cut:]),
            ])
            frames = list(decode(pcap))
        self.assertEqual([f['direction'] for f in frames], ['device->broker', 'broker->device'])
        self.assertEqual(frames[0]['topic'], 'user/heartbeat/up')
        self.assertEqual(frames[0]['command'], FIXTURES[0]['command'])
        self.assertEqual(len(bytes.fromhex(frames[0]['body_hex'])), FIXTURES[0]['body_length'])
        self.assertEqual(frames[1]['topic'], 'user/function/down_cmd')
        self.assertEqual(frames[0]['mac'], 'masked')


if __name__ == '__main__':
    unittest.main()
