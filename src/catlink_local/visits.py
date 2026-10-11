"""Provisional C08 visit decoding, based on labelled physical visits and known weights."""

HEARTBEAT = (3, 1, 0x035a)
VISIT_REPORT = (3, 0x5a, 0x025a)


def weight_kg(high, low):
    """Weight encoding shared by the heartbeat and the completed report: kg, hundredths."""
    return round(high + low / 100, 2)


def heartbeat_fields(frame):
    """Decode the heartbeat fields established so far; None for other frames.

    Byte 42 follows the entry sensor, byte 44 the weight-present state, bytes 16-17
    the live scale reading relative to the box's own tare (so an empty box reads
    close to zero and slowly re-zeroes after a deposit), bytes 14-15 the box clock.
    """
    if (frame.kind, frame.subsystem, frame.command) != HEARTBEAT or len(frame.body) != 60:
        return None
    body = frame.body
    return {'live_weight_kg': weight_kg(body[16], body[17]),
            'entry_sensor': body[42], 'weight_present': body[44],
            'box_clock': f'{body[14]:02d}:{body[15]:02d}'}


class VisitDecoder:
    def __init__(self):
        self.occupied = None

    def feed(self, frame, received_at):
        events = []
        body = frame.body
        fields = heartbeat_fields(frame)
        if fields:
            flags = (fields['entry_sensor'], fields['weight_present'])
            if flags not in ((0, 0), (1, 1)):
                return events
            occupied = flags == (1, 1)
            if self.occupied is not None and occupied != self.occupied:
                events.append({'type': 'cat_entered' if occupied else 'cat_left',
                               'received_at': received_at, 'provisional': True,
                               'live_weight_kg': fields['live_weight_kg']})
            self.occupied = occupied
        elif (frame.kind, frame.subsystem, frame.command) == VISIT_REPORT:
            if len(body) == 6 and body[:2] == b'\x00\x03' and body[5] < 100:
                events.append({'type': 'visit_completed', 'received_at': received_at,
                               'weight_kg': weight_kg(body[4], body[5]),
                               'duration_seconds': int.from_bytes(body[2:4], 'big'),
                               # Kept for existing consumers; the field is now understood.
                               'duration_seconds_candidate': int.from_bytes(body[2:4], 'big'),
                               'provisional': True})
        return events
