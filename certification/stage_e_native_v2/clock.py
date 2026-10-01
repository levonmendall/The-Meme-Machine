"""Explicit modeled clocks. Fixture construction cannot advance execution time."""
from dataclasses import dataclass
import math


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass
class DeterministicClock:
    wall_epoch: int = 1_800_000_000
    monotonic_epoch: int = 100
    elapsed_us: int = 0
    executing: bool = False

    def time(self):
        return self.wall_epoch + self.elapsed_us / 1_000_000

    def monotonic(self):
        return self.monotonic_epoch + self.elapsed_us / 1_000_000

    def begin(self):
        if self.executing or self.elapsed_us:
            raise ValueError('execution_epoch_already_started')
        self.executing = True

    def advance_to(self, elapsed_us):
        if not self.executing or type(elapsed_us) is not int or elapsed_us < self.elapsed_us:
            raise ValueError('illegal_clock_advance')
        self.elapsed_us = elapsed_us


def validate_clock_samples(samples, declaration):
    """Fresh source cannot launder old events or stop economic aging."""
    if not samples:
        raise ValueError('missing_clock_samples')
    previous = None
    origins = {}
    episodes = {}
    wall0, mono0 = declaration['wall_epoch'], declaration['monotonic_epoch']
    if declaration['wall_monotonic_error_seconds'] != 3:
        raise ValueError('clock_tolerance_changed')
    for row in samples:
        fields = ('wall', 'monotonic', 'source', 'economic_now', 'residence_now')
        if any(not finite(row.get(k)) for k in fields):
            raise ValueError('invalid_clock_sample')
        if abs(row['wall'] - (wall0 + row['monotonic'] - mono0)) > 3:
            raise ValueError('wall_monotonic_incoherence')
        if row['economic_now'] != row['wall'] or row['residence_now'] != row['wall']:
            raise ValueError('economic_or_residence_aging_frozen')
        if not 0 <= row['wall'] - row['source'] < 45:
            raise ValueError('source_lag')
        if previous and any(row[k] < previous[k] for k in fields):
            raise ValueError('clock_regression')
        for record in row.get('records', []):
            identity, at = record['identity'], record['event_at']
            if not finite(at) or identity in origins and origins[identity] != at:
                raise ValueError('eligibility_timestamp_refreshed')
            origins[identity] = at
            age = row['economic_now'] - at
            if not 0 <= age < 240:
                raise ValueError('stale_economic_event')
        for episode in row.get('episodes', []):
            key = (episode['scope'], episode['side'])
            identity = (episode['episode_id'], episode['source_origin'], episode['wall_origin'])
            if key in episodes and episodes[key] != identity:
                raise ValueError('recovery_episode_rebased')
            episodes[key] = identity
            if episode['source_deadline'] != episode['source_origin'] + 120:
                raise ValueError('recovery_deadline_rebased')
            if row['source'] >= episode['source_deadline'] and not episode.get('cleared', False):
                raise ValueError('recovery_deadline_expired')
        previous = row
    return True
