"""Active prospective market-native discovery for the paper-only Solana runtime.

This module retires configured wallet scouts from *prospective discovery authority*.
It does not remove the legacy scout implementation used by captured/synthetic
regressions. Candidate discovery comes only from the finalized Pump program tape;
continuation-v1 remains the canonical qualification policy and unchanged paper
execution remains in :class:`Engine`.

The runtime is intentionally hierarchical so broad market discovery does not spend
RPC evidence on candidates that the frozen policy can already reject from the stream:

1. market-native discovery from finalized Pump activity;
2. RPC-free feasibility under the existing 60-second evidence rules;
3. time-distributed one-snapshot preflight for non-concentration gates;
4. concentration + final snapshot only for surviving candidates;
5. unchanged Engine reservation/fill/monitor/exit authority.

The nomination wallet is a real triggering buyer and remains excluded from independent
demand exactly as before. It is admitted transiently only while Engine.qualify /
Engine.consider run; it is never configured or persisted as a scout and never receives
skill or sizing authority.
"""
from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager

from .engine import SIGNAL_WINDOW
from .market_native_priority import stream_feasibility
from .market_native_shadow import discover_market_native
from .provider import Unavailable
from .research import qualification_vector
from .stream import WINDOW_SECONDS


MAX_DISCOVERED_MINTS = 10_000
DEFAULT_EVIDENCE_QUEUE_LIMIT = 10_000
MONITORING_RESERVE_REQUESTS = 40
FULL_EVIDENCE_WORST_CASE_CALLS = 3
EVIDENCE_DEADLINE_SAFETY_SECONDS = 0.5


class MarketNativeAuthority:
    """Compatibility boundary that grants no wallet-scout authority.

    Engine.qualify historically required the nomination wallet to be present in the
    configured seed set. Market-native discovery deliberately has no configured
    wallet set. To preserve the exact policy implementation rather than copy it, the
    real nomination wallet is inserted into the in-memory set only for the duration
    of qualification/consideration and removed in ``finally``. No Store mutation,
    wallet scorecard, scout configuration change, or sizing influence is created.
    """
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def _nomination_anchor(self, wallet):
        existed = wallet in self.engine.seeds
        if not existed:
            self.engine.seeds.add(wallet)
        try:
            yield
        finally:
            if not existed:
                self.engine.seeds.discard(wallet)

    def vector(self, nomination, evidence, now):
        with self._nomination_anchor(nomination['wallet']):
            return qualification_vector(self.engine, nomination, evidence, now)

    def consider(self, nomination, evidence, now):
        with self._nomination_anchor(nomination['wallet']):
            return self.engine.consider(nomination, evidence, now)


class MarketNativeRuntime:
    """Adaptive deadline-aware evidence scheduler for prospective paper trading."""
    def __init__(self, engine, adapter, session_seconds,
                 clock=time.time, provider_rotation_threshold=None,
                 evidence_queue_limit=DEFAULT_EVIDENCE_QUEUE_LIMIT):
        if engine.seeds:
            raise ValueError('scouts_must_be_disabled_for_market_native_runtime')
        if session_seconds < 1 or evidence_queue_limit < 1:
            raise ValueError('invalid_market_native_scheduler')
        self.engine = engine
        self.adapter = adapter
        self.clock = clock
        self.authority = MarketNativeAuthority(engine)
        self.session_seconds = int(session_seconds)
        self.evidence_queue_limit = int(evidence_queue_limit)

        # Adaptive evidence has no fixed candidate-count quota. Safety comes from
        # a bounded in-memory queue, deadline expiry, and provider-session rotation
        # that always preserves monitoring capacity.
        discovery_cap = max(0, int(adapter.rpc.limit) - MONITORING_RESERVE_REQUESTS)
        threshold = (
            min(160, discovery_cap) if provider_rotation_threshold is None
            else int(provider_rotation_threshold)
        )
        if not MONITORING_RESERVE_REQUESTS <= threshold <= discovery_cap:
            raise ValueError('invalid_market_native_provider_rotation_threshold')
        self.provider_rotation_threshold = threshold
        self.provider_rotations = 0
        self.provider_sessions = []

        self.coverage_ready_at = None
        self.discovered = set()
        self.evidence_queue = {}
        self.stream_rejections = Counter()
        self.preflight_reasons = Counter()
        self.full_reasons = Counter()
        self.preflight_selected = 0
        self.full_evidence_attempted = 0
        self.qualified = 0
        self.capacity_losses = 0
        self.provider_failures = 0
        self.last_qualified_mint = None

        self.evidence_enqueued = 0
        self.evidence_processed = 0
        self.evidence_expired_before_preflight = 0
        self.evidence_deadline_insufficient = 0
        self.evidence_cancelled_on_gap = 0
        self.evidence_queue_capacity_skips = 0
        self.provider_headroom_deferrals = 0
        self.preflight_rpc_free_rejections = 0

        # Bounded diagnostic-only evidence for the most recent selected preflight.
        # It never participates in qualification or order authority.
        self.last_attempt = None
        self.last_attempt_sequence = 0

    def _start_attempt(self, candidate, current, stream_events, now):
        self.last_attempt_sequence += 1
        self.last_attempt = dict(
            sequence=self.last_attempt_sequence,
            mint=candidate['mint'],
            nomination=dict(candidate['nomination']),
            stage='stream_feasibility',
            observed_at=int(now),
            stream_feasibility=current.to_dict(),
            stream_events=list(stream_events),
        )

    def _update_attempt(self, stage, **details):
        if self.last_attempt is None:
            return
        self.last_attempt['stage'] = stage
        self.last_attempt.update(details)

    def replace_adapter(self, adapter):
        """Rotate only read-only evidence transport; never economic/order authority."""
        if self.provider_rotation_threshold is None:
            raise ValueError('market_native_provider_rotation_not_enabled')
        discovery_cap=max(0,int(adapter.rpc.limit)-40)
        if self.provider_rotation_threshold>discovery_cap:
            raise ValueError('invalid_market_native_provider_rotation_threshold')
        self.provider_sessions.append(self._provider_status())
        self.provider_sessions=self.provider_sessions[-8:]
        self.adapter=adapter
        self.provider_rotations+=1

    def _now(self):
        return int(self.clock())

    def _reset_signal_generation(self):
        self.coverage_ready_at = None
        self.discovered.clear()
        if self.evidence_queue:
            self.evidence_cancelled_on_gap += len(self.evidence_queue)
            self.evidence_queue.clear()

    def _provider_status(self):
        rpc = self.adapter.rpc
        return dict(
            requests=rpc.calls,
            http_requests=rpc.http_requests,
            failures=rpc.failures,
            cache_hits=rpc.cache_hits,
            limit=rpc.limit,
            concentration=self.adapter.concentration_status(),
            provider_topology=(rpc.provider_telemetry()
                               if hasattr(rpc,'provider_telemetry') else None),
            infrastructure_spend_usd=0,
            provider_spend_usd=(0 if getattr(rpc,'failover_count',0)==0 else None),
        )

    def _record_coverage(self, tape, now, fresh_count=0):
        status = tape.status(now)
        with self.engine.store.transaction('market_native_coverage'):
            s = self.engine.store.state
            s['last_time'] = now
            s['progress'] += 1
            s.setdefault('coverage', {})['pump_program_stream'] = dict(
                window_covered=bool(status.get('covered')),
                time=now,
                stream=status,
                discovery_mode='market_native',
                fresh_trade_events=int(fresh_count),
            )
            s['provider'] = self._provider_status()

    def _preflight(self, candidate, tape):
        nomination = dict(candidate['nomination'])
        nomination['discovery_source'] = 'market_native'
        now = self._now()
        current = stream_feasibility(candidate, tape, now)
        stream_events = tape.window(candidate['mint'], now)
        self._start_attempt(candidate, current, stream_events, now)
        if not current.possible:
            self.preflight_reasons[current.guaranteed_rejection] += 1
            self._update_attempt('guaranteed_rejection',
                                 reason=current.guaranteed_rejection)
            return

        try:
            self._update_attempt('preflight_snapshot')
            snap = self.adapter.snapshot(candidate['mint'], now, priority=False)
            now = self._now()
            if not tape.covered(now):
                raise Unavailable('incomplete_market_window')
            events = tape.window(candidate['mint'], now, max_slot=snap['slot'])
            pre_evidence = dict(snapshot=snap, events=events, covered=True,
                                concentration_bps=0)
            pre = self.authority.vector(nomination, pre_evidence, now)
            self._update_attempt(
                'preflight_vector',
                preflight_snapshot=snap,
                preflight_events=list(events),
                preflight_vector=pre,
            )
            if pre.get('actual_reason') != 'qualified':
                reason = pre.get('actual_reason') or 'unknown'
                self.preflight_reasons[reason] += 1
                self._update_attempt('preflight_rejection', reason=reason)
                return
            self.preflight_reasons['passes_non_concentration'] += 1
            self.full_evidence_attempted += 1
            self._update_attempt(
                'concentration',
                full_evidence_attempt=self.full_evidence_attempted,
            )
            concentration = self.adapter.concentration(
                candidate['mint'], snap, priority=False)
            self._update_attempt(
                'final_snapshot',
                concentration_bps=concentration,
                concentration_status=self.adapter.concentration_status(),
            )
            final = self.adapter.snapshot(candidate['mint'], self._now(), priority=False)
            qualified_at = self._now()
            if not tape.covered(qualified_at):
                raise Unavailable('incomplete_market_window')
            events = tape.window(candidate['mint'], qualified_at, max_slot=final['slot'])
            evidence = dict(snapshot=final, events=events, covered=True,
                            concentration_bps=concentration)
            vector = self.authority.vector(nomination, evidence, qualified_at)
            reason = vector.get('actual_reason') or 'unavailable_executable_evidence'
            self.full_reasons[reason] += 1
            self._update_attempt(
                'full_vector',
                qualified_at=qualified_at,
                final_snapshot=final,
                final_events=list(events),
                final_vector=vector,
                reason=reason,
            )
            if reason != 'qualified':
                self._update_attempt('full_rejection', reason=reason)
                return

            canonical = self.authority.consider(nomination, evidence, qualified_at)
            if canonical != 'qualified':
                raise RuntimeError('market_native_qualification_authority_mismatch')
            self.qualified += 1
            self.last_qualified_mint = candidate['mint']
            self._update_attempt(
                'qualified',
                canonical_result=canonical,
                order_id=nomination['id'],
            )
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ValueError) and str(exc) == 'order_identity_collision':
                self.full_reasons['order_identity_collision'] += 1
                self._update_attempt(
                    'identity_collision',
                    reason='order_identity_collision',
                    order_id=nomination.get('id'),
                    mint=nomination.get('mint'),
                )
                return
            self.provider_failures += 1
            self.preflight_reasons['unavailable_executable_evidence'] += 1
            rpc = self.adapter.rpc
            self._update_attempt(
                'failure',
                failure_class=type(exc).__name__,
                failure_reason=str(exc),
                concentration_status=self.adapter.concentration_status(),
                provider=dict(
                    logical=getattr(rpc, 'calls', 0),
                    transport=getattr(rpc, 'http_requests', 0),
                    failures=getattr(rpc, 'failures', 0),
                    retries=getattr(rpc, 'retries', 0),
                    failure_kinds=dict(getattr(rpc, 'failure_kinds', {})),
                ),
            )

    def _candidate_deadline(self, candidate):
        return int(candidate['nomination']['market_time']) + SIGNAL_WINDOW

    def _queue_key(self, row):
        return (
            int(row['deadline']),
            *tuple(row['metric'].priority_key()),
        )

    def _estimated_full_evidence_seconds(self):
        pacer=getattr(self.adapter.rpc,'read_pacer',None)
        interval=float(getattr(pacer,'minimum_interval',0.2))
        return max(
            1.0,
            FULL_EVIDENCE_WORST_CASE_CALLS*max(0.0,interval)
            + EVIDENCE_DEADLINE_SAFETY_SECONDS,
        )

    def provider_rotation_due(self, required_calls=FULL_EVIDENCE_WORST_CASE_CALLS):
        return (
            int(getattr(self.adapter.rpc,'calls',0)) + int(required_calls)
            > int(self.provider_rotation_threshold)
        )

    def _queue_candidate(self, candidate, metric, now):
        deadline=self._candidate_deadline(candidate)
        if deadline <= int(now):
            self.evidence_expired_before_preflight += 1
            return
        row=dict(
            candidate=candidate,
            metric=metric,
            queued_at=int(now),
            deadline=deadline,
        )
        if len(self.evidence_queue) >= self.evidence_queue_limit:
            worst_mint,worst=max(
                self.evidence_queue.items(),
                key=lambda item:self._queue_key(item[1]),
            )
            if self._queue_key(row) >= self._queue_key(worst):
                self.evidence_queue_capacity_skips += 1
                self.capacity_losses += 1
                return
            del self.evidence_queue[worst_mint]
            self.evidence_queue_capacity_skips += 1
            self.capacity_losses += 1
        self.evidence_queue[candidate['mint']]=row
        self.evidence_enqueued += 1

    def _expire_queue(self, now):
        expired=[
            mint for mint,row in self.evidence_queue.items()
            if int(row['deadline']) <= int(now)
        ]
        for mint in expired:
            del self.evidence_queue[mint]
        self.evidence_expired_before_preflight += len(expired)

    def _process_queue_one(self, tape, now):
        self._expire_queue(now)
        if not self.evidence_queue:
            return
        if self.provider_rotation_due():
            self.provider_headroom_deferrals += 1
            return
        mint,row=min(
            self.evidence_queue.items(),
            key=lambda item:self._queue_key(item[1]),
        )
        deadline=int(row['deadline'])
        if deadline-int(now) < self._estimated_full_evidence_seconds():
            del self.evidence_queue[mint]
            self.evidence_deadline_insufficient += 1
            return

        candidate=row['candidate']
        current=stream_feasibility(candidate,tape,int(now))
        if not current.possible:
            del self.evidence_queue[mint]
            self.preflight_rpc_free_rejections += 1
            self.preflight_reasons[current.guaranteed_rejection] += 1
            return

        del self.evidence_queue[mint]
        self.preflight_selected += 1
        self.evidence_processed += 1
        self._preflight(candidate,tape)

    def tick(self, tape, now, cursor):
        """Advance discovery/evidence once; caller monitors existing exposure first."""
        status = tape.status(now)
        if self.engine.store.pressure():
            return cursor

        if not status['covered']:
            with self.engine.store.transaction('market_native_stream_coverage'):
                s = self.engine.store.state
                if status['connected'] and status['warm_seconds'] < WINDOW_SECONDS:
                    until = now + (WINDOW_SECONDS-status['warm_seconds'])
                    s['entry_quarantine_until'] = max(
                        s.get('entry_quarantine_until', 0), until)
                else:
                    self.engine.quarantine('stream_continuity_unavailable', now)
                s.setdefault('coverage', {})['pump_program_stream'] = dict(
                    window_covered=False, time=now, stream=status,
                    discovery_mode='market_native')
            self._reset_signal_generation()
            return None

        if cursor is None:
            cursor = tape.latest_sequence()
            self.coverage_ready_at = now
            self._record_coverage(tape, now, 0)
            return cursor

        fresh, cursor = tape.events_since(cursor)
        if fresh:
            native = discover_market_native(fresh, tape, now, self.discovered)
            for candidate in native:
                if len(self.discovered) >= MAX_DISCOVERED_MINTS:
                    self.capacity_losses += 1
                    break
                mint = candidate['mint']
                self.discovered.add(mint)
                metric = stream_feasibility(candidate, tape, now)
                if not metric.possible:
                    self.stream_rejections[metric.guaranteed_rejection] += 1
                else:
                    self._queue_candidate(candidate,metric,now)

        # Exactly one evidence candidate per scheduler turn. The caller returns to
        # monitoring before another candidate can consume provider capacity.
        self._process_queue_one(tape,now)
        self._record_coverage(tape,self._now(),len(fresh))
        return cursor

    def status(self):
        now=self._now()
        next_deadline=(
            min(int(row['deadline']) for row in self.evidence_queue.values())
            if self.evidence_queue else None
        )
        return dict(
            mode='market_native',
            scout_lane_active=False,
            scout_storage_active=False,
            configured_scouts=len(self.engine.seeds),
            evidence_scheduler='adaptive_deadline_queue_v1',
            discovered=len(self.discovered),
            stream_guaranteed_rejections=dict(self.stream_rejections),
            evidence_queue_depth=len(self.evidence_queue),
            evidence_queue_limit=self.evidence_queue_limit,
            evidence_enqueued=self.evidence_enqueued,
            evidence_processed=self.evidence_processed,
            evidence_expired_before_preflight=self.evidence_expired_before_preflight,
            evidence_deadline_insufficient=self.evidence_deadline_insufficient,
            evidence_cancelled_on_gap=self.evidence_cancelled_on_gap,
            evidence_queue_capacity_skips=self.evidence_queue_capacity_skips,
            preflight_rpc_free_rejections=self.preflight_rpc_free_rejections,
            next_evidence_deadline_seconds=(
                None if next_deadline is None else max(0,next_deadline-now)
            ),
            estimated_full_evidence_seconds=self._estimated_full_evidence_seconds(),
            preflight_selected=self.preflight_selected,
            preflight_reason_distribution=dict(self.preflight_reasons),
            full_evidence_attempted=self.full_evidence_attempted,
            full_reason_distribution=dict(self.full_reasons),
            qualified=self.qualified,
            last_qualified_mint=self.last_qualified_mint,
            diagnostic_last_attempt=self.last_attempt,
            capacity_losses=self.capacity_losses,
            provider_failures=self.provider_failures,
            provider_rotation_threshold=self.provider_rotation_threshold,
            provider_rotation_due=self.provider_rotation_due(),
            provider_headroom_deferrals=self.provider_headroom_deferrals,
            provider_rotations=self.provider_rotations,
            prior_provider_sessions=list(self.provider_sessions),
            order_authority='unchanged_engine_after_continuation_v1',
            dlmm_enabled=False,
        )
