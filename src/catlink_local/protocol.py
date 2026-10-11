"""C08 frames: independently checked against this device's MQTT publications."""
from dataclasses import dataclass
from functools import reduce
from operator import xor

def checksum(data: bytes) -> int:
    return reduce(xor, data, 0)

@dataclass(frozen=True)
class Frame:
    seq: int
    mac: bytes
    kind: int
    subsystem: int
    command: int
    body: bytes

    @classmethod
    def decode(cls, data: bytes):
        if len(data) < 16 or data[0] != 0xfc:
            raise ValueError('invalid frame header')
        if int.from_bytes(data[1:3], 'big') + 4 != len(data):
            raise ValueError('invalid frame length')
        if checksum(data[1:-1]) != data[-1]:
            raise ValueError('invalid frame checksum')
        return cls(int.from_bytes(data[3:5], 'big'), data[5:11], data[11],
                   data[12], int.from_bytes(data[13:15], 'big'), data[15:-1])

    def encode(self):
        if len(self.mac) != 6 or not 0 <= self.seq <= 65535:
            raise ValueError('invalid identity')
        inner = (self.seq.to_bytes(2, 'big') + self.mac +
                 bytes([self.kind, self.subsystem]) + self.command.to_bytes(2, 'big') + self.body)
        checked = len(inner).to_bytes(2, 'big') + inner
        return b'\xfc' + checked + bytes([checksum(checked)])

    @classmethod
    def clock_command(cls, mac: bytes, when):
        """Build the C08 clock command verified against a real device ACK.

        The device expects local calendar fields; supply an aware datetime.
        """
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError('clock requires an explicit timezone')
        if not 2000 <= when.year <= 2255:
            raise ValueError('year does not fit device protocol')
        body = bytes((0, when.year - 2000, when.month, when.day,
                      when.isoweekday(), when.hour, when.minute, when.second))
        return cls(1, mac, 1, 0x5a, 0x0d5a, body)
