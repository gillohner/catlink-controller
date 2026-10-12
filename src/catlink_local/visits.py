"""Provisional C08 visit decoding, based on labelled physical visits and known weights."""

HEARTBEAT = (3, 1, 0x035a)
# A tare-relative reading this high means something is on the scale even when the
# entry/presence flags are still clear (a cat's paws just before the sensor fires).
EMPTY_MAX_KG = 0.5
VISIT_REPORT = (3, 0x5a, 0x025a)
# Seen once after each observed auto-clean, ~80 s after the heartbeat that flagged
# byte 2; interpreted as "cleaning finished". Provisional until more cycles confirm it.
CLEAN_FINISHED = (3, 0x5a, 0x0b5a)


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
            # Byte 2 was 1 exactly in the heartbeat emitted when the box started its
            # automatic clean (~5.5 min after the exit, "cat mode"), 0 otherwise.
            'cleaning': body[2],
            'box_clock': f'{body[14]:02d}:{body[15]:02d}'}


class VisitDecoder:
    def __init__(self):
        self.occupied = None
        self.cleaning = False
        self.last_empty_kg = None     # most recent tare-relative reading with both flags clear
        self.entry_baseline_kg = None  # that reading as of the last entry
        self.pending_report = None    # completed report awaiting the first empty reading

    def feed(self, frame, received_at):
        events = []
        body = frame.body
        fields = heartbeat_fields(frame)
        if fields:
            if fields['cleaning'] and not self.cleaning:
                events.append({'type': 'cleaning_started', 'received_at': received_at,
                               'provisional': True})
            self.cleaning = bool(fields['cleaning'])
            flags = (fields['entry_sensor'], fields['weight_present'])
            if flags not in ((0, 0), (1, 1)):
                return events
            occupied = flags == (1, 1)
            if self.occupied is not None and occupied != self.occupied:
                events.append({'type': 'cat_entered' if occupied else 'cat_left',
                               'received_at': received_at, 'provisional': True,
                               'live_weight_kg': fields['live_weight_kg']})
                if occupied:
                    self.entry_baseline_kg = self.last_empty_kg
            self.occupied = occupied
            if not occupied and fields['live_weight_kg'] < EMPTY_MAX_KG:
                # The first empty reading after a completed report shows what stayed
                # behind, relative to the pre-entry baseline. Near the ~30 g tare noise.
                if self.pending_report and self.entry_baseline_kg is not None:
                    report = self.pending_report
                    events.append({'type': 'deposit_estimate', 'received_at': received_at,
                                   'residual_kg': round(fields['live_weight_kg'] - self.entry_baseline_kg, 2),
                                   'weight_kg': report['weight_kg'],
                                   'duration_seconds': report['duration_seconds'],
                                   'provisional': True})
                self.pending_report = None
                self.last_empty_kg = fields['live_weight_kg']
        elif (frame.kind, frame.subsystem, frame.command) == VISIT_REPORT:
            if len(body) == 6 and body[:2] == b'\x00\x03' and body[5] < 100:
                events.append({'type': 'visit_completed', 'received_at': received_at,
                               'weight_kg': weight_kg(body[4], body[5]),
                               'duration_seconds': int.from_bytes(body[2:4], 'big'),
                               # Kept for existing consumers; the field is now understood.
                               'duration_seconds_candidate': int.from_bytes(body[2:4], 'big'),
                               'provisional': True})
                self.pending_report = events[-1]
        elif (frame.kind, frame.subsystem, frame.command) == CLEAN_FINISHED and body == b'\0\0':
            events.append({'type': 'cleaning_finished', 'received_at': received_at,
                           'provisional': True})
        return events
