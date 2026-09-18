"""Transaction-pressure bounded acquisition for dense finalized DLMM markets.

This module changes only when the research runner closes a verified chunk. It never
raises `MAX_TRANSACTIONS`, never drops signatures, and never treats a pressure census
as evidence. The census is only an early-warning signal; every accepted chunk still
uses the normal authentic snapshot -> complete signature census -> transaction bodies
-> terminal equality path in `dlmm_strategy_high_activity_batched._capture_chunk`.
"""
from __future__ import annotations

import math
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
PRESSURE_MIN_HEADROOM = 10
PRESSURE_CAPTURE_DEFAULT_SECONDS = 1.0
PRESSURE_CAPTURE_SAFETY_FACTOR = 1.5
PRESSURE_RATE_JITTER_TRANSACTIONS = 1
MAX_VERIFIED_CHUNKS_PER_ADVANCE = 24
ENDPOINT_CAPTURE_HIGH_WATER = {}
MAX_WARMUP_STATE_RESETS = 2
STATE_RESET_PREFIX = 'dlmm_snapshot_reset_required:'
STATE_RESET_KINDS = {'add_liquidity_by_strategy2','add_liquidity2'}


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


def _predictive_close_policy(samples,capture_seconds):
    """Reserve verifier capacity for growth while the endpoint snapshot is captured."""
    capture=max(PRESSURE_CAPTURE_DEFAULT_SECONDS,float(capture_seconds or 0))
    rate=0.0
    for (t0,c0),(t1,c1) in zip(samples,samples[1:]):
        dt=t1-t0
        if dt>0 and c1>=c0:
            rate=max(rate,(c1-c0)/dt)
    projected=int(math.ceil(rate*capture*PRESSURE_CAPTURE_SAFETY_FACTOR))
    headroom=max(PRESSURE_MIN_HEADROOM,projected+PRESSURE_RATE_JITTER_TRANSACTIONS)
    headroom=min(MAX_TRANSACTIONS-1,headroom)
    threshold=max(1,min(PRESSURE_SOFT_LIMIT,MAX_TRANSACTIONS-headroom))
    return dict(arrival_rate_per_second=rate,capture_latency_seconds=capture,
                projected_capture_growth=projected,reserved_headroom=headroom,
                close_threshold=threshold)


def _await_pressure_boundary(adapter,current,max_wait,capture_latency=None):
    """Wait until predictive transaction pressure says to close the next chunk."""
    if not current or max_wait <= 0:
        raise ValueError('dlmm_pressure_boundary_input')
    began = time.monotonic()
    polls = 0
    peak = {address: 0 for address in current}
    counts = {address: 0 for address in current}
    capture_latency=dict(capture_latency or {})
    samples={address:[] for address in current}
    policies={address:_predictive_close_policy([],capture_latency.get(address))
              for address in current}
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
        elapsed = min(max_wait, max(0.0,time.monotonic()-began))
        for address,count in counts.items():
            samples[address].append((elapsed,count))
            policies[address]=_predictive_close_policy(
                samples[address],capture_latency.get(address))
        overflow=[address for address,count in counts.items() if count>MAX_TRANSACTIONS]
        if overflow:
            trigger='hard_cap_visible'
            break
        if any(count>=policies[address]['close_threshold']
               for address,count in counts.items()):
            trigger='predictive_transaction_pressure'
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
        predictive_policy={address:dict(policy) for address,policy in policies.items()},
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
    capture_latency={address:ENDPOINT_CAPTURE_HIGH_WATER.get(
        address,PRESSURE_CAPTURE_DEFAULT_SECONDS) for address in states}
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
            boundary = _await_pressure_boundary(
                adapter,current,max_wait,capture_latency=capture_latency)
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
                chunks[address].append(tape);cursors[address]=cursor;current[address]=tape.terminal
                endpoint=None
                for candidate in reversed(getattr(base,'ENDPOINT_DIAGNOSTICS',[])):
                    if candidate.get('pool')==address and candidate.get('start_slot')==start.get('slot'):
                        endpoint=candidate;break
                if endpoint and isinstance(endpoint.get('endpoint_capture_seconds'),(int,float)):
                    measured=max(PRESSURE_CAPTURE_DEFAULT_SECONDS,float(endpoint['endpoint_capture_seconds']))
                    capture_latency[address]=max(capture_latency.get(address,0),measured)
                    ENDPOINT_CAPTURE_HIGH_WATER[address]=max(
                        ENDPOINT_CAPTURE_HIGH_WATER.get(address,0),measured)
                policy=(boundary.get('predictive_policy') or {}).get(address,{})
                item=base._chunk_meta(round_index,start,tape,tx_count)
                item['pressure_boundary']=dict(
                    trigger=boundary['trigger'],polls=boundary['polls'],
                    waited_seconds=boundary['waited_seconds'],
                    preflight_transactions=boundary['counts'].get(address,0),
                    peak_transactions=boundary['peak_transactions'].get(address,0),
                    soft_limit=boundary['soft_limit'],hard_limit=boundary['hard_limit'],
                    close_threshold=policy.get('close_threshold'),
                    reserved_headroom=policy.get('reserved_headroom'),
                    arrival_rate_per_second=policy.get('arrival_rate_per_second'),
                    capture_latency_seconds=policy.get('capture_latency_seconds'),
                    projected_capture_growth=policy.get('projected_capture_growth'))
                meta[address].append(item)
            except (Unavailable, ValueError, KeyError, TypeError) as exc:
                reason=str(exc)
                if allow_snapshot_reset and reason.startswith(STATE_RESET_PREFIX):
                    parts=reason.split(':')
                    if len(parts)!=3 or parts[1] not in STATE_RESET_KINDS:
                        errors.append(dict(pool=address,chunk=round_index,
                            reason='dlmm_snapshot_reset_kind_unsupported',
                            stage='verified_capture'))
                        current.pop(address,None)
                        continue
                    mutation_kind=parts[1]
                    if reset_counts[address] >= MAX_WARMUP_STATE_RESETS:
                        errors.append(dict(pool=address,chunk=round_index,
                            reason='dlmm_snapshot_reset_count_bound',stage='verified_capture',
                            preflight_transactions=boundary['counts'].get(address,0),
                            pressure_trigger=boundary['trigger']))
                        current.pop(address,None)
                        continue
                    try:
                        mutation_slot=int(parts[2])
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
                        mutation=mutation_kind,
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
