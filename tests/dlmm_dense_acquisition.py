"""Transaction-pressure bounded acquisition for dense finalized DLMM markets.

This module changes only when the research runner closes a verified chunk. It never
raises `MAX_TRANSACTIONS`, never drops signatures, and never treats a pressure census
as evidence. The census is only an early-warning signal; every accepted chunk still
uses the normal authentic snapshot -> complete signature census -> transaction bodies
-> terminal equality path in `dlmm_strategy_high_activity_batched._capture_chunk`.
"""
from __future__ import annotations

import time

from meme_machine.dlmm_tape import MAX_TRANSACTIONS, chain_verified_tapes
from meme_machine.provider import Unavailable
from tests import dlmm_strategy_high_activity_batched as base

PRESSURE_SOFT_LIMIT = 10
PRESSURE_CENSUS_LIMIT = MAX_TRANSACTIONS + 1
PRESSURE_INITIAL_POLL_SECONDS = 0.50
PRESSURE_ACTIVE_POLL_SECONDS = 0.25
PRESSURE_IDLE_POLL_SECONDS = 0.75
MAX_VERIFIED_CHUNKS_PER_ADVANCE = 24


def _pressure_census(rpc, start):
    """Count recent successful finalized pool transactions after the chunk start.

    The result is scheduling-only. Exact completeness is re-established by
    `_capture_chunk`; this count can never authorize or validate a tape.
    """
    signatures = rpc.call(
        'getSignaturesForAddress',
        [start['pool'], dict(limit=PRESSURE_CENSUS_LIMIT, commitment='finalized')],
        True,
    )
    if not isinstance(signatures, list):
        raise Unavailable('dlmm_pressure_census_shape')
    return sum(1 for sig in signatures
               if isinstance(sig, dict) and not sig.get('err')
               and isinstance(sig.get('slot'), int) and sig['slot'] > start['slot'])


def _await_pressure_boundary(adapter, current, max_wait):
    """Wait until time or transaction pressure says to close the next chunk."""
    if not current or max_wait <= 0:
        raise ValueError('dlmm_pressure_boundary_input')
    began = time.monotonic()
    polls = 0
    peak = {address: 0 for address in current}
    counts = {address: 0 for address in current}
    delay = min(PRESSURE_INITIAL_POLL_SECONDS, max_wait)
    trigger = 'time'
    overflow = []
    while True:
        if delay > 0:
            time.sleep(delay)
        polls += 1
        for address, start in current.items():
            count = _pressure_census(adapter.rpc, start)
            counts[address] = count
            peak[address] = max(peak[address], count)
        elapsed = min(max_wait, max(0.0, time.monotonic() - began))
        overflow = [address for address, count in counts.items()
                    if count > MAX_TRANSACTIONS]
        if overflow:
            trigger = 'hard_cap_visible'
            break
        if any(count >= PRESSURE_SOFT_LIMIT for count in counts.values()):
            trigger = 'transaction_pressure'
            break
        remaining = max_wait - elapsed
        if remaining <= 0:
            trigger = 'time'
            break
        active = any(count > 0 for count in counts.values())
        delay = min(PRESSURE_ACTIVE_POLL_SECONDS if active else PRESSURE_IDLE_POLL_SECONDS,
                    remaining)
    return dict(
        trigger=trigger,
        polls=polls,
        waited_seconds=elapsed,
        counts=dict(counts),
        peak_transactions=dict(peak),
        overflow=tuple(overflow),
        soft_limit=PRESSURE_SOFT_LIMIT,
        hard_limit=MAX_TRANSACTIONS,
    )


def pressure_advance(adapter, states, wait_seconds):
    """Advance through dense markets using early, independently verified chunks."""
    if wait_seconds <= 0:
        raise ValueError('dlmm_chunk_wait')
    current = dict(states)
    cursors = {address: [state['slot'], 2**31 - 1, 2**31 - 1]
               for address, state in states.items()}
    chunks = {address: [] for address in states}
    meta = {address: [] for address in states}
    errors = []
    remaining = float(wait_seconds)
    round_index = 0
    while remaining > 0 and current:
        if round_index >= MAX_VERIFIED_CHUNKS_PER_ADVANCE:
            for address, start in current.items():
                errors.append(dict(pool=address, chunk=round_index,
                                   reason='dlmm_verified_chunk_count_bound',
                                   start_last_update=start.get('last_update'),
                                   start_time=start.get('time')))
            current.clear()
            break
        max_wait = min(float(base.CHUNK_SECONDS), remaining)
        try:
            boundary = _await_pressure_boundary(adapter, current, max_wait)
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            for address, start in current.items():
                errors.append(dict(pool=address, chunk=round_index,
                                   reason=str(exc), stage='pressure_census',
                                   start_last_update=start.get('last_update'),
                                   start_time=start.get('time')))
            current.clear()
            break
        for address in boundary['overflow']:
            start = current.get(address, {})
            errors.append(dict(pool=address, chunk=round_index,
                               reason='dlmm_transaction_pressure_overflow',
                               stage='pressure_census',
                               observed_transactions=boundary['counts'].get(address),
                               start_last_update=start.get('last_update'),
                               start_time=start.get('time')))
            current.pop(address, None)
        for address in list(current):
            start = current[address]
            try:
                tape, cursor, tx_count = base._capture_chunk(adapter, start, cursors[address])
                chunks[address].append(tape)
                cursors[address] = cursor
                current[address] = tape.terminal
                item = base._chunk_meta(round_index, start, tape, tx_count)
                item['pressure_boundary'] = dict(
                    trigger=boundary['trigger'], polls=boundary['polls'],
                    waited_seconds=boundary['waited_seconds'],
                    preflight_transactions=boundary['counts'].get(address, 0),
                    peak_transactions=boundary['peak_transactions'].get(address, 0),
                    soft_limit=boundary['soft_limit'], hard_limit=boundary['hard_limit'])
                meta[address].append(item)
            except (Unavailable, ValueError, KeyError, TypeError) as exc:
                errors.append(dict(pool=address, chunk=round_index, reason=str(exc),
                    stage='verified_capture',
                    preflight_transactions=boundary['counts'].get(address, 0),
                    pressure_trigger=boundary['trigger'],
                    start_last_update=start.get('last_update'),
                    filter_period=(start.get('parameters') or {}).get('filter_period'),
                    start_time=start.get('time')))
                current.pop(address, None)
        consumed = boundary['waited_seconds']
        if consumed <= 0:
            consumed = min(PRESSURE_ACTIVE_POLL_SECONDS, remaining)
        remaining = max(0.0, remaining - consumed)
        round_index += 1
    advanced = {}
    tapes = {}
    diag = {}
    for address in current:
        if not chunks[address]:
            continue
        try:
            tape = chain_verified_tapes(states[address], chunks[address])
            advanced[address] = tape.terminal
            tapes[address] = tape
            diag[address] = dict(
                chunks=meta[address], combined_swaps=len(tape.events),
                terminal_adjustments=list(tape.terminal_adjustments),
                acquisition='transaction_pressure_bounded_verified_chunks')
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            errors.append(dict(pool=address, chunk='chain', reason=str(exc)))
    base.ADVANCE_DIAGNOSTICS.append(diag)
    return advanced, tapes, errors
