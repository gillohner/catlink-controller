"""Provisional C08 visit decoding, based on two labelled physical visits."""


class VisitDecoder:
    def __init__(self):
        self.occupied = None

    def feed(self, frame, received_at):
        events = []
        body = frame.body
        if (frame.kind, frame.subsystem, frame.command) == (3, 1, 0x035a) and len(body) == 60:
            flags = (body[42], body[44])
            if flags not in ((0, 0), (1, 1)):
                return events
            occupied = flags == (1, 1)
            if self.occupied is not None and occupied != self.occupied:
                events.append({'type': 'cat_entered' if occupied else 'cat_left',
                               'received_at': received_at, 'provisional': True})
            self.occupied = occupied
        elif (frame.kind, frame.subsystem, frame.command) == (3, 0x5a, 0x025a):
            if len(body) == 6 and body[:2] == b'\x00\x03' and body[5] < 100:
                events.append({'type': 'visit_completed', 'received_at': received_at,
                               'weight_kg': round(body[4] + body[5] / 100, 2),
                               'duration_seconds_candidate': int.from_bytes(body[2:4], 'big'),
                               'provisional': True})
        return events
