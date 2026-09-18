"""Transaction-pressure bounded acquisition for dense finalized DLMM markets.

This module changes only when the research runner closes a verified chunk. It never
raises `MAX_TRANSACTIONS`, never drops signatures, and never treats a pressure census
as evidence. The census is only an early-warning signal; every accepted chunk still
uses the normal authentic snapshot -> complete signature census -> transaction bodies
-> terminal equality path in `dlmm_strategy_high_activity_batched._capture_chunk`.
"""
from __future__ import annotations

import time

from meme_machine import dlmm
from meme_machine.dlmm_tape import MAX_TRANSACTIONS, chain_verified_tapes
from meme_machine.provider import Unavailable
from meme_machine.store import digest
from tests import dlmm_strategy_high_activity_batched as base

PRESSURE_SOFT_LIMIT = 10
PRESSURE_CENSUS_LIMIT = MAX_TRANSACTIONS + 1
PRESSURE_INITIAL_POLL_SECONDS = 0.50
PRESSURE_ACTIVE_POLL_SECONDS = 0.25
PRESSURE_IDLE_POLL_SECONDS = 0.75
MAX_VERIFIED_CHUNKS_PER_ADVANCE = 24
MAX_WARMUP_STATE_RESETS = 2
STATE_RESET_PREFIX = 'dlmm_snapshot_reset_required:add_liquidity_by_strategy2:'


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


def pressure_advance(adapter, states, wait_seconds, allow_snapshot_reset=False):
    """Advance dense markets; warmup may restart after one authenticated LP mutation.

    A reset never bridges a state discontinuity. All chunks collected before the
    mutation are discarded, the caller's warmup origin is replaced with a fresh
    finalized snapshot, and the full observation window restarts. Outcome replay must
    pass allow_snapshot_reset=False so a post-entry liquidity mutation still fails
    closed rather than changing the counterfactual entry state.
    """
    if wait_seconds <= 0:
        raise ValueError('dlmm_chunk_wait')
    if type(allow_snapshot_reset) is not bool:
        raise ValueError('dlmm_snapshot_reset_policy')
    if allow_snapshot_reset and len(states)!=1:
        raise ValueError('dlmm_snapshot_reset_requires_single_pool')
    current = dict(states)
    origins = dict(states)
    cursors = {address: [state['slot'], 2**31 - 1, 2**31 - 1]
               for address, state in states.items()}
    chunks = {address: [] for address in states}
    meta = {address: [] for address in states}
    errors = []
    resets = {address: [] for address in states}
    reset_counts = {address: 0 for address in states}
    full_window = float(wait_seconds)
    remaining = full_window
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
                reason=str(exc)
                if allow_snapshot_reset and reason.startswith(STATE_RESET_PREFIX):
                    if reset_counts[address] >= MAX_WARMUP_STATE_RESETS:
                        errors.append(dict(pool=address,chunk=round_index,
                            reason='dlmm_snapshot_reset_count_bound',stage='verified_capture',
                            preflight_transactions=boundary['counts'].get(address,0),
                            pressure_trigger=boundary['trigger']))
                        current.pop(address,None)
                        continue
                    try:
                        mutation_slot=int(reason.rsplit(':',1)[1])
                        fresh_snapshot=adapter.snapshot(
                            address,int(time.time()),True,fresh=True)
                        fresh=dlmm.validate(
                            fresh_snapshot,fresh_snapshot['available_time'],'real')
                        if fresh['pool']!=address or fresh['slot']<mutation_slot or fresh['slot']<=start['slot']:
                            raise Unavailable('dlmm_snapshot_reset_endpoint_not_after_mutation')
                    except (Unavailable,ValueError,KeyError,TypeError) as reset_exc:
                        errors.append(dict(pool=address,chunk=round_index,
                            reason=str(reset_exc),stage='snapshot_reset'))
                        current.pop(address,None)
                        continue
                    discarded=len(chunks[address])
                    reset_counts[address]+=1
                    resets[address].append(dict(
                        mutation='add_liquidity_by_strategy2',
                        mutation_slot=mutation_slot,
                        prior_origin_slot=origins[address]['slot'],
                        prior_start_slot=start['slot'],
                        reset_slot=fresh['slot'],
                        discarded_verified_chunks=discarded,
                        policy='discard_prior_warmup_and_restart_full_window'))
                    # This is a new point-in-time research origin, not a continuity
                    # bridge. Discard every earlier chunk/cursor and mutate the
                    # caller's warmup state so regime features use the reset snapshot.
                    states[address]=fresh
                    origins[address]=fresh
                    current[address]=fresh
                    cursors[address]=[fresh['slot'],2**31-1,2**31-1]
                    chunks[address].clear();meta[address].clear()
                    remaining=full_window
                    continue
                errors.append(dict(pool=address, chunk=round_index, reason=reason,
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
        # A handled state reset already restored the full window above. Otherwise
        # account for elapsed observation time normally.
        if not any(r and r[-1].get('reset_slot')==current.get(a,{}).get('slot')
                   for a,r in resets.items() if a in current):
            remaining = max(0.0, remaining - consumed)
        round_index += 1
    advanced = {}
    tapes = {}
    diag = {}
    for address in current:
        if not chunks[address]:
            continue
        try:
            tape = chain_verified_tapes(origins[address], chunks[address])
            advanced[address] = tape.terminal
            tapes[address] = tape
            diag[address] = dict(
                chunks=meta[address], combined_swaps=len(tape.events),
                terminal_adjustments=list(tape.terminal_adjustments),
                acquisition='transaction_pressure_bounded_verified_chunks',
                snapshot_resets=list(resets[address]))
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            errors.append(dict(pool=address, chunk='chain', reason=str(exc)))
    base.ADVANCE_DIAGNOSTICS.append(diag)
    return advanced, tapes, errors
