"""Small MQTT 3.1/3.1.1 wire codec for the observed C08 client."""
import asyncio


def field(value):
    return len(value).to_bytes(2, 'big') + value


def read_field(data, offset=0):
    if offset + 2 > len(data):
        raise ValueError('truncated MQTT field')
    end = offset + 2 + int.from_bytes(data[offset:offset + 2], 'big')
    if end > len(data):
        raise ValueError('truncated MQTT field')
    return data[offset + 2:end], end


def packet(header, body=b''):
    if len(body) > 65536:
        raise ValueError('MQTT packet too large')
    remaining = len(body)
    out = bytearray([header])
    while True:
        remaining, value = divmod(remaining, 128)
        out.append(value | (128 if remaining else 0))
        if not remaining:
            return bytes(out) + body


async def read_packet(reader):
    async with asyncio.timeout(190):
        header = (await reader.readexactly(1))[0]
        remaining = 0
        for index in range(4):
            value = (await reader.readexactly(1))[0]
            remaining += (value & 127) << (7 * index)
            if remaining > 65536:
                raise ValueError('MQTT packet too large')
            if not value & 128:
                return header, await reader.readexactly(remaining)
        raise ValueError('invalid MQTT remaining length')
