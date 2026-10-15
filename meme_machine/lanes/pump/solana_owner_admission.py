"""One bounded non-authoritative maintenance admission before one new source request.

Only returned pressure and local scheduling state cross this interface. The gate
never observes debt, builds Needs, chooses a side, or credits native service.
"""
from __future__ import annotations

import asyncio
from collections import Counter, deque
from dataclasses import dataclass
import math
import time

from .solana_evidence_plane import EvidenceUnavailable

OFFER_SECONDS = .100
HINT_SECONDS = 1.0
SOURCE_AGE_SECONDS = 8.9
SOURCE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SourceState:
    kind: str
    pending_frames: int
    pending_bytes: int
    receiver_waiting: bool
    inbound: int
    decoded: int
    ordered_ready: int
    commit_age: float
    head_age: float
    draining: bool = False


@dataclass(frozen=True)
class PressureHint:
    epoch: int
    generation: str
    returned_at: float
    positive: bool


@dataclass
class Offer:
    hint: PressureHint
    snapshot: object
    row: dict
    done: object
    released: object
    attempted: bool = False
    maintenance_future: object = None
    source_future: object = None
    timer: object = None


class OwnerAdmission:
    def __init__(self, owner, *, clock=time.monotonic):
        self.owner, self.clock = owner, clock
        self.loop = asyncio.get_running_loop()
        self.wake = asyncio.Event()
        self.generation = None
        self.hint = None
        self.epoch = self.consumed = 0
        self.offer = None
        self.maintenance_future = self.last_source = None
        self.closed = self.failed = self.generation_invalid = False
        self.counters = Counter()
        self.events = deque(maxlen=64)

    def publish(self, generation, result):
        self.epoch += 1
        self.hint = PressureHint(self.epoch, generation, self.clock(),
            bool(result['archive_pressure'] or result['retirement_pressure']))
        if generation != self.generation:
            self.generation_invalid = True
            self.recheck()

    def _reason(self, source, *, spending=False):
        now = self.clock()
        if source.kind != 'blocks':
            return 'head_' + source.kind if source.kind in ('account', 'ack', 'control') else 'head_other'
        if self.closed or source.draining:
            return 'draining'
        if self.failed:
            return 'failed'
        if self.generation_invalid or self.generation is None:
            return 'generation_invalid'
        hint = self.offer.hint if spending else self.hint
        if hint is None or not hint.positive:
            return 'no_positive_hint'
        if hint.generation != self.generation:
            return 'hint_generation'
        if not spending and hint.epoch <= self.consumed:
            return 'hint_consumed'
        if not math.isfinite(now) or not 0 <= now-hint.returned_at <= HINT_SECONDS:
            return 'hint_age'
        if self.last_source is not None and not self.last_source.done():
            return 'source_unfinished'
        if self.offer is not None and not spending:
            return 'offer_outstanding'
        if self.maintenance_future is not None and not self.maintenance_future.done():
            return 'maintenance_unfinished'
        if not 1 <= source.pending_frames < 16:
            return 'pending_frames'
        if not 0 <= source.pending_bytes <= SOURCE_BYTES:
            return 'pending_bytes'
        if source.receiver_waiting:
            return 'receiver_capacity'
        for name in ('inbound', 'decoded', 'ordered_ready'):
            if not 0 <= getattr(source, name) < 16:
                return name
        for name in ('commit_age', 'head_age'):
            value = getattr(source, name)
            if not math.isfinite(value) or not 0 <= value < SOURCE_AGE_SECONDS:
                return name
        with self.owner.cv:
            if self.owner.closed:
                return 'owner_closed'
            if self.owner._checkpoint_handoff is not None:
                return 'checkpoint_handoff'
            if any(row[0] < 2 for row in self.owner.queue):
                return 'urgent_waiting'
            if self.owner.queue:
                return 'owner_queue'
            if self.owner._checkpoint_busy:
                return 'owner_busy'
        return None

    def recheck(self):
        offer = self.offer
        if offer is None or offer.maintenance_future is not None or offer.done.done():
            return
        reason = self._reason(offer.snapshot(), spending=True)
        if reason:
            self._finish(offer, 'bypass_' + reason)

    def _finish(self, offer, outcome):
        if offer.done.done():
            return
        offer.row['outcome'] = outcome
        self.counters[outcome] += 1
        if offer.timer is not None:
            offer.timer.cancel()
        offer.done.set_result(outcome)
        self.wake.set()

    def expire(self, offer):
        if self.clock() < offer.row['deadline']:
            # Test clocks can lag the event loop; retain an absolute deadline.
            offer.timer = self.loop.call_later(
                offer.row['deadline']-self.clock(), self.expire, offer)
            return
        self._finish(offer, 'timeout')

    async def rendezvous(self, snapshot):
        source = snapshot()
        reason = self._reason(source)
        if reason:
            self.counters['bypass_' + reason] += 1
            return None
        now = self.clock()
        hint = self.hint
        row = dict(epoch=hint.epoch, generation=hint.generation,
            hint_returned=hint.returned_at, open=now, deadline=now+OFFER_SECONDS,
            pending_frames=source.pending_frames, pending_bytes=source.pending_bytes)
        offer = Offer(hint, snapshot, row, self.loop.create_future(), asyncio.Event())
        self.offer = offer
        self.consumed = hint.epoch
        self.counters['offers'] += 1
        if len(self.events) == self.events.maxlen:
            self.counters['evicted_events'] += 1
        self.events.append(row)
        offer.timer = self.loop.call_later(OFFER_SECONDS, self.expire, offer)
        self.wake.set()
        try:
            await asyncio.shield(offer.done)
            return offer
        except BaseException:
            self.abort(offer)
            raise
        finally:
            resume = self.clock()
            elapsed = max(0.0, resume-now)
            overshoot = max(0.0, resume-row['deadline'])
            row.update(resume=resume, gate_wait=elapsed, overshoot=overshoot)
            self.counters['wait_total_us'] += int(elapsed*1_000_000)
            self.counters['wait_peak_us'] = max(self.counters['wait_peak_us'], int(elapsed*1_000_000))
            self.counters['overshoot_total_us'] += int(overshoot*1_000_000)
            if overshoot:
                self.failed = True
                self.counters['overshoots'] += 1

    async def before_maintenance(self):
        # This barrier also covers the ordinary fast-resubmission path, including
        # a native turn that finishes before the source coroutine gets scheduled.
        while self.offer is not None:
            offer = self.offer
            if not offer.attempted and not offer.done.done():
                self.recheck()
                if self.clock() >= offer.row['deadline']:
                    self.expire(offer)
                if not offer.done.done():
                    offer.attempted = True
                    offer.row['maintenance_submit'] = self.clock()
                    return offer
            await offer.released.wait()
        return None

    def accepted(self, future, offer=None):
        self.maintenance_future = future
        if offer is None:
            return
        # submit() itself checked the absolute deadline under owner.cv, before
        # its unchanged heap admission. A wakeup is never recorded as acceptance.
        at = future.owner_accepted_at
        if at >= offer.row['deadline']:
            raise RuntimeError('late_owner_admission')
        offer.maintenance_future = future
        offer.row.update(owner_acceptance=at, maintenance_sequence=future.owner_sequence,
            submission_to_acceptance=at-offer.row['maintenance_submit'])
        if 'owner_entry' in offer.row:
            offer.row['owner_queue_wait']=offer.row['owner_entry']-at
        self._finish(offer, 'accepted')

    def refused(self, offer, error):
        if offer is not None:
            offer.row['admission_error'] = str(error)[:120]
            self._finish(offer, 'timeout' if str(error) == 'evidence_admission_offer_expired' else 'refused')

    def entry(self, offer):
        if offer is not None:
            at = self.clock()
            offer.row['owner_entry']=at
            if 'owner_acceptance' in offer.row:
                offer.row['owner_queue_wait']=at-offer.row['owner_acceptance']

    def completed(self, offer, *, result=None, error=None, event=None):
        if offer is not None:
            offer.row.update(completion=self.clock(), maintenance_result=(
                str(error)[:120] if error is not None else
                'decision' if result and result.get('side') else 'no_decision'))
            offer.row.update(selected_side=None,durable_progress={},durable_records={})
            if event:
                offer.row.update(selected_side=event.get('selected'),
                    durable_progress=event.get('durable_progress', {}),
                    durable_records=event.get('durable_records', {}),
                    native_completion=event.get('completion'))
            offer.row['maintenance_error_type'] = type(error).__name__ if error is not None else None
            offer.row['native_refusal'] = isinstance(error,EvidenceUnavailable) and str(error) != 'evidence_background_yield'

    def source_accepted(self, future, offer, frames):
        self.last_source = future
        if offer is None:
            return
        offer.source_future = future
        offer.row.update(source_submit=future.owner_accepted_at,
            source_sequence=future.owner_sequence, affected_frames=frames)
        future.add_done_callback(lambda f: offer.row.update(
            source_completion=self.clock(), source_error=str(f.exception())[:120] if f.exception() else None))
        self._release(offer)

    def _release(self, offer):
        if offer.timer is not None:
            offer.timer.cancel()
        if self.offer is offer:
            self.offer = None
        offer.released.set()

    def abort(self, offer):
        if offer is None or offer.source_future is not None:
            return
        offer.row['source_abort'] = self.clock()
        self._finish(offer, 'aborted')
        self._release(offer)

    def close(self):
        self.closed = True
        if self.offer is not None and self.offer.maintenance_future is None:
            self.abort(self.offer)
        # An accepted turn retains its barrier through the source's actual
        # submission or explicit abort, including an admitted-frame drain.
        self.wake.set()

    async def idle(self, stop, worker=None):
        # Preserve the existing one-second idle/worker cadence, adding a coalesced
        # immediate wake. Shield the one accepted worker future on cancellation.
        waiters = [asyncio.create_task(self.wake.wait()), asyncio.create_task(stop.wait())]
        if worker is not None:
            waiters.append(asyncio.ensure_future(asyncio.shield(asyncio.wrap_future(worker))))
        try:
            await asyncio.wait(waiters, timeout=1.0, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            self.wake.clear()

    def telemetry(self):
        return dict(generation=self.generation, hint_epoch=self.epoch,
            consumed_epoch=self.consumed, counters=dict(self.counters),
            events=list(self.events), failed=self.failed, closed=self.closed)
