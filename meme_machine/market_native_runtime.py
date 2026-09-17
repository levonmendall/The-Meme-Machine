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
from collections import Counter, defaultdict
from contextlib import contextmanager

from .market_native_priority import (
    choose_slot_candidate,
    priority_slot_seconds,
    stream_feasibility,
)
from .market_native_shadow import discover_market_native
from .provider import Unavailable
from .research import qualification_vector
from .stream import WINDOW_SECONDS


DEFAULT_PREFLIGHT_BUDGET = 60
DEFAULT_FULL_EVIDENCE_BUDGET = 20
MAX_DISCOVERED_MINTS = 5_000


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
    """Bounded in-memory discovery/evidence scheduler for prospective paper trading."""
    def __init__(self, engine, adapter, session_seconds,
                 preflight_budget=DEFAULT_PREFLIGHT_BUDGET,
                 full_evidence_budget=DEFAULT_FULL_EVIDENCE_BUDGET,
                 clock=time.time):
        if engine.seeds:
            raise ValueError('scouts_must_be_disabled_for_market_native_runtime')
        if session_seconds < 1 or preflight_budget < 1 or full_evidence_budget < 1:
            raise ValueError('invalid_market_native_budget')
        self.engine = engine
        self.adapter = adapter
        self.clock = clock
        self.authority = MarketNativeAuthority(engine)
        self.session_seconds = int(session_seconds)
        self.preflight_budget = int(preflight_budget)
        self.full_evidence_budget = int(full_evidence_budget)
        self.slot_seconds = priority_slot_seconds(self.session_seconds, self.preflight_budget)

        # Discovery RPC is deliberately non-priority so at least 40 logical requests
        # stay reserved for monitoring already-authorized exposure. Include a worst-
        # case primary concentration fallback for every full-evidence attempt.
        discovery_cap = max(0, int(adapter.rpc.limit) - 40)
        worst_case = int(adapter.rpc.calls) + 2*self.preflight_budget + 3*self.full_evidence_budget
        if worst_case > discovery_cap:
            raise ValueError('market_native_budget_exceeds_discovery_rpc_reserve')

        self.coverage_ready_at = None
        self.last_flushed_slot = -1
        self.discovered = set()
        self.slot_rows = defaultdict(list)
        self.stream_rejections = Counter()
        self.preflight_reasons = Counter()
        self.full_reasons = Counter()
        self.preflight_selected = 0
        self.full_evidence_attempted = 0
        self.qualified = 0
        self.capacity_losses = 0
        self.provider_failures = 0
        self.last_qualified_mint = None

    def _now(self):
        return int(self.clock())

    def _reset_signal_generation(self):
        self.coverage_ready_at = None
        self.last_flushed_slot = -1
        self.discovered.clear()
        self.slot_rows.clear()

    def _provider_status(self):
        rpc = self.adapter.rpc
        return dict(
            requests=rpc.calls,
            http_requests=rpc.http_requests,
            failures=rpc.failures,
            cache_hits=rpc.cache_hits,
            limit=rpc.limit,
            concentration=self.adapter.concentration_status(),
            infrastructure_spend_usd=0,
            provider_spend_usd=(0 if getattr(rpc, 'url', None) ==
                                'https://api.mainnet-beta.solana.com' else None),
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
        if not current.possible:
            self.preflight_reasons[current.guaranteed_rejection] += 1
            return

        try:
            snap = self.adapter.snapshot(candidate['mint'], now, priority=False)
            now = self._now()
            if not tape.covered(now):
                raise Unavailable('incomplete_market_window')
            events = tape.window(candidate['mint'], now, max_slot=snap['slot'])
            pre_evidence = dict(snapshot=snap, events=events, covered=True,
                                concentration_bps=0)
            pre = self.authority.vector(nomination, pre_evidence, now)
            if pre.get('actual_reason') != 'qualified':
                self.preflight_reasons[pre.get('actual_reason') or 'unknown'] += 1
                return
            self.preflight_reasons['passes_non_concentration'] += 1
            if self.full_evidence_attempted >= self.full_evidence_budget:
                self.preflight_reasons['full_evidence_budget_exhausted'] += 1
                return

            self.full_evidence_attempted += 1
            concentration = self.adapter.concentration(
                candidate['mint'], snap, priority=False)
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
            if reason != 'qualified':
                return

            canonical = self.authority.consider(nomination, evidence, qualified_at)
            if canonical != 'qualified':
                raise RuntimeError('market_native_qualification_authority_mismatch')
            self.qualified += 1
            self.last_qualified_mint = candidate['mint']
        except (Unavailable, ValueError, KeyError, TypeError):
            self.provider_failures += 1
            self.preflight_reasons['unavailable_executable_evidence'] += 1

    def _process_slot(self, slot, tape):
        if self.preflight_selected >= self.preflight_budget:
            self.slot_rows.pop(slot, None)
            return
        chosen = choose_slot_candidate(self.slot_rows.pop(slot, []))
        if chosen is None:
            return
        candidate, _metric = chosen
        self.preflight_selected += 1
        self._preflight(candidate, tape)

    def tick(self, tape, now, cursor):
        """Advance discovery only; existing exposure must be monitored by caller first."""
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
            self.last_flushed_slot = -1
            self._record_coverage(tape, now, 0)
            return cursor

        current_slot = max(0, (now-int(self.coverage_ready_at)) // self.slot_seconds)
        while self.last_flushed_slot < current_slot-1:
            self.last_flushed_slot += 1
            self._process_slot(self.last_flushed_slot, tape)

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
                    self.slot_rows[current_slot].append((candidate, metric))

        self._record_coverage(tape, now, len(fresh))
        return cursor

    def status(self):
        return dict(
            mode='market_native',
            scout_lane_active=False,
            scout_storage_active=False,
            configured_scouts=len(self.engine.seeds),
            discovered=len(self.discovered),
            stream_guaranteed_rejections=dict(self.stream_rejections),
            preflight_budget=self.preflight_budget,
            preflight_selected=self.preflight_selected,
            preflight_reason_distribution=dict(self.preflight_reasons),
            full_evidence_budget=self.full_evidence_budget,
            full_evidence_attempted=self.full_evidence_attempted,
            full_reason_distribution=dict(self.full_reasons),
            qualified=self.qualified,
            last_qualified_mint=self.last_qualified_mint,
            capacity_losses=self.capacity_losses,
            provider_failures=self.provider_failures,
            slot_seconds=self.slot_seconds,
            order_authority='unchanged_engine_after_continuation_v1',
            dlmm_enabled=False,
        )
