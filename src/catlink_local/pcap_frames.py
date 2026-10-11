"""Offline decoder: list C08 frames inside MQTT publications from a private pcap.

Reads a classic libpcap file (Ethernet or Linux cooked link types) with the
standard library only, reassembles each TCP direction in order, parses MQTT
PUBLISH packets and prints decoded frames with the device MAC masked. Intended
for protocol research on captures of the box's plaintext vendor session; the
capture itself stays private.
"""
import argparse
import json
from pathlib import Path
import struct

from .mqtt import read_field
from .protocol import Frame

LINKTYPE_ETHERNET, LINKTYPE_LINUX_SLL, LINKTYPE_RAW = 1, 113, 101


def packets(path):
    data = Path(path).read_bytes()
    magic = data[:4]
    if magic == b'\xd4\xc3\xb2\xa1':
        order, nano = '<', False
    elif magic == b'\xa1\xb2\xc3\xd4':
        order, nano = '>', False
    elif magic == b'\x4d\x3c\xb2\xa1':
        order, nano = '<', True
    elif magic == b'\xa1\xb2\x3c\x4d':
        order, nano = '>', True
    else:
        raise ValueError('not a classic pcap file (pcapng is not supported; use tcpdump -w)')
    linktype = struct.unpack(order + 'I', data[20:24])[0]
    offset = 24
    while offset + 16 <= len(data):
        sec, frac, caplen, _ = struct.unpack(order + 'IIII', data[offset:offset + 16])
        offset += 16
        yield sec + frac / (1e9 if nano else 1e6), linktype, data[offset:offset + caplen]
        offset += caplen


def tcp_payload(linktype, packet):
    if linktype == LINKTYPE_ETHERNET:
        if len(packet) < 14 or packet[12:14] != b'\x08\x00':
            return None
        ip = packet[14:]
    elif linktype == LINKTYPE_LINUX_SLL:
        if len(packet) < 16 or packet[14:16] != b'\x08\x00':
            return None
        ip = packet[16:]
    elif linktype == LINKTYPE_RAW:
        ip = packet
    else:
        raise ValueError(f'unsupported link type {linktype}')
    if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 6:
        return None
    ihl = (ip[0] & 15) * 4
    total = int.from_bytes(ip[2:4], 'big')
    tcp = ip[ihl:total]
    if len(tcp) < 20:
        return None
    src = '.'.join(map(str, ip[12:16])), int.from_bytes(tcp[0:2], 'big')
    dst = '.'.join(map(str, ip[16:20])), int.from_bytes(tcp[2:4], 'big')
    seq = int.from_bytes(tcp[4:8], 'big')
    return (src, dst), seq, tcp[(tcp[12] >> 4) * 4:]


def mqtt_packets(stream):
    """Split a reassembled byte stream into (header, body) MQTT packets."""
    pos = 0
    while pos < len(stream):
        header = stream[pos]
        remaining, shift, index = 0, 0, 1
        while True:
            if pos + index >= len(stream):
                return
            value = stream[pos + index]
            remaining |= (value & 127) << shift
            shift += 7
            index += 1
            if not value & 128:
                break
        if pos + index + remaining > len(stream):
            return
        yield header, stream[pos + index:pos + index + remaining]
        pos += index + remaining


def decode(path, mask=True):
    streams = {}
    for when, linktype, packet in packets(path):
        parsed = tcp_payload(linktype, packet)
        if parsed is None or not parsed[2]:
            continue
        flow, seq, payload = parsed
        segments = streams.setdefault(flow, {})
        segments.setdefault(seq, (when, payload))
    for flow, segments in streams.items():
        stream, first = bytearray(), None
        for seq in sorted(segments):
            when, payload = segments[seq]
            first = first or when
            stream += payload
        for header, body in mqtt_packets(bytes(stream)):
            if header >> 4 != 3:
                continue
            try:
                topic, pos = read_field(body)
                if (header >> 1) & 3:
                    pos += 2
                frame = Frame.decode(body[pos:])
            except (ValueError, IndexError):
                continue
            yield {'direction': 'device->broker' if flow[1][1] == 1883 else 'broker->device',
                   'topic': '/'.join(topic.decode(errors='replace').split('/')[-3:]),
                   'seq': frame.seq, 'kind': frame.kind, 'subsystem': frame.subsystem,
                   'command': frame.command, 'body_hex': frame.body.hex(),
                   'mac': 'masked' if mask else frame.mac.hex()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('pcap', type=Path)
    parser.add_argument('--show-mac', action='store_true', help='print the device MAC (private)')
    args = parser.parse_args()
    for frame in decode(args.pcap, mask=not args.show_mac):
        print(json.dumps(frame))


if __name__ == '__main__':
    main()
