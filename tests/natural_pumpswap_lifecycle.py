"""Forward paper-only acceptance for one genuine natural continuation-v1 Pump -> PumpSwap lifecycle.

This harness never creates an order, reservation, position, graduation flag, handoff,
or exit directly. New exposure can appear only through the production prospective
`tick_stream` path, which calls the unchanged Engine.scout -> Engine.consider ->
Engine.qualify policy on finalized mainnet Pump events. Once a natural order exists,
the harness stops discovery and services that exact exposure through the production
existing-order/position monitor until it closes or proves PumpSwap settlement.

Acceptance is stricter than ordinary seed membership: the winning nomination must
come from a prospectively admitted watchlist record and its market_time must be
strictly greater than that wallet's recorded eligible_after timestamp. Captured
fixtures are never live acceptance seeds.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from meme_machine import pump
from meme_machine.__main__ import _monitor_existing, tick_stream
from meme_machine.engine import Engine
from meme_machine.postgrad import PostGraduationAdapter
from meme_machine.provider import RPC, PumpAdapter
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.store import Store, digest
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

WATCHLIST = Path('evidence/unvalidated_seed_watchlist.json')
REPORT = Path(os.environ.get('MM_NATURAL_LIFECYCLE_REPORT', 'natural-pumpswap-lifecycle-report.json'))
GENESIS_SOL_USD_MICROS = 97_840_000
GENESIS_SOURCE = (
    '2026-09-16 recorded validation reference: $97.84/SOL; '
    'forward natural Pump-to-PumpSwap paper acceptance, not performance continuity'
)
DISCOVERY_SECONDS = max(60, min(int(os.environ.get('MM_NATURAL_LIFECYCLE_DISCOVERY_SECONDS', '3300')), 3300))
POST_ENTRY_SECONDS = max(120, min(int(os.environ.get('MM_NATURAL_LIFECYCLE_POST_ENTRY_SECONDS', '1000')), 1000))
POLL_SECONDS = 5


def _seed_records():
    """Return only prospectively admitted watchlist seeds for live acceptance."""
    watch = json.loads(WATCHLIST.read_text())
    admitted = int(watch.get('created_at_unix', 0))
    return [
        dict(
            wallet=item['wallet'],
            eligible_after=int(item.get('eligible_after_unix', admitted)),
            source='watchlist',
        )
        for item in watch['seeds']
    ][:4]


def _prospective_admission(records, nomination):
    """Prove the nomination is from a watchlist seed after its admission boundary."""
    wallet = nomination.get('wallet')
    record = next(
        (item for item in records
         if item.get('wallet') == wallet and item.get('source') == 'watchlist'),
        None,
    )
    if record is None:
        return False, None
    try:
        market_time = int(nomination['market_time'])
        eligible_after = int(record['eligible_after'])
    except (KeyError, TypeError, ValueError):
        return False, record
    return market_time > eligible_after, record


def _save(report):
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True))


def _replay_qualification(seeds, nomination, evidence, created_at):
    """Re-run the exact captured evidence against frozen qualify in clean capital state."""
    with tempfile.TemporaryDirectory() as td:
        replay_store = Store(
            str(Path(td) / 'qualification-replay.db'),
            'prospective',
            GENESIS_SOL_USD_MICROS,
            GENESIS_SOURCE,
        )
        replay_engine = Engine(replay_store, seeds)
        try:
            return replay_engine.qualify(
                copy.deepcopy(nomination),
                copy.deepcopy(evidence),
                int(created_at),
            )
        finally:
            replay_store.close()


def _natural_order_packet(order, records):
    nomination = order.get('nomination') or {}
    evidence = order.get('evidence') or {}
    snapshot = evidence.get('snapshot') or {}
    admitted, record = _prospective_admission(records, nomination)
    return dict(
        nomination=copy.deepcopy(nomination),
        qualification_evidence=copy.deepcopy(evidence),
        scout_wallet_is_preselected=record is not None,
        scout_source=None if record is None else record.get('source'),
        scout_eligible_after=None if record is None else int(record['eligible_after']),
        scout_market_time=nomination.get('market_time'),
        prospective_admission_valid=admitted,
        covered_market_window=bool(evidence.get('covered')),
        evidence_kind=snapshot.get('kind'),
        evidence_protocol=snapshot.get('protocol'),
        evidence_network=snapshot.get('network'),
    )


def _pump_fill_is_real_open_position(order):
    fill = order.get('fill') or {}
    snapshot = order.get('fill_snapshot') or {}
    if fill.get('surface') == 'pumpswap':
        return False
    if snapshot.get('kind') != 'real' or snapshot.get('network') != 'solana-mainnet':
        return False
    if snapshot.get('protocol') != 'pump.fun':
        return False
    try:
        return not bool(pump.curve(snapshot['accounts'][0]).complete)
    except (ValueError, KeyError, TypeError, IndexError):
        return False


def _proof_complete(store, runtime, oid, candidate):
    order = store.state['orders'].get(oid) or {}
    exit_record = order.get('exit') or {}
    mint = order.get('mint')
    if not (
        candidate.get('prospective_admission_valid') is True
        and candidate.get('qualification_replay') == 'qualified'
        and candidate.get('pump_position_opened')
        and candidate.get('graduation_handoff')
        and exit_record.get('surface') == 'pumpswap'
        and (exit_record.get('snapshot') or {}).get('surface') == 'pumpswap'
        and mint not in store.state['positions']
        and int(store.state['funnel'].get('settled_exits', 0)) >= 1
    ):
        return False
    status = runtime.status()
    if status.get('new_allocation_authority') or status.get('legacy_raydium_authority'):
        return False
    store.reconcile()
    store.verify_archive()
    return True


def main():
    records = _seed_records()
    seeds = [item['wallet'] for item in records]
    started = int(time.time())
    report = dict(
        kind='natural_forward_continuation_v1_pump_to_pumpswap_acceptance',
        network='solana-mainnet',
        qualification_policy='continuation-v1',
        qualification_policy_frozen=True,
        prospective_watchlist_required=True,
        admission_rule='market_time > eligible_after',
        captured_fixture_seed_allowed=False,
        paper_only=True,
        signing_available=False,
        transaction_submission_available=False,
        live_money_authority=False,
        forced_authority=False,
        synthetic_candidate=False,
        acquisition='finalized_logsSubscribe',
        seed_records=records,
        discovery_seconds=DISCOVERY_SECONDS,
        post_entry_seconds=POST_ENTRY_SECONDS,
        provider_limit=120,
        proof=False,
        candidates=[],
        limitations=[],
        started=started,
    )
    _save(report)

    url = os.environ.get('MM_SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
    rpc = RPC(url, limit=120)
    tape = PumpTape()
    stop = threading.Event()
    ready = threading.Event()
    stream = PumpLogStream(url, tape)
    thread = threading.Thread(target=stream.run, args=(stop, ready), daemon=True)
    thread.start()

    try:
        with tempfile.TemporaryDirectory() as td:
            store = Store(
                str(Path(td) / 'natural-lifecycle.db'),
                'prospective',
                GENESIS_SOL_USD_MICROS,
                GENESIS_SOURCE,
            )
            engine = Engine(store, seeds)
            pump_adapter = PumpAdapter(rpc)
            postgrad_adapter = PostGraduationAdapter(rpc, scan_rpc=object())
            pumpswap_runtime = PumpSwapPaperRuntime(store, postgrad_adapter)
            cursor = None
            known_orders = set(store.state['orders'])
            target_oid = None
            target = None
            discovery_deadline = time.monotonic() + WINDOW_SECONDS + DISCOVERY_SECONDS
            absolute_deadline = discovery_deadline + POST_ENTRY_SECONDS

            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            else:
                while time.monotonic() < absolute_deadline:
                    now = int(time.time())
                    if stream.error_kind:
                        report['limitations'].append('stream_continuity_lost')
                        break

                    if target_oid is None:
                        if time.monotonic() >= discovery_deadline:
                            break
                        cursor = tick_stream(
                            engine,
                            pump_adapter,
                            tape,
                            now,
                            cursor,
                            pumpswap_runtime=pumpswap_runtime,
                        )
                        new_orders = [oid for oid in store.state['orders'] if oid not in known_orders]
                        known_orders.update(store.state['orders'])
                        if new_orders:
                            target_oid = new_orders[0]
                            order = store.state['orders'][target_oid]
                            packet = _natural_order_packet(order, records)
                            replay = _replay_qualification(
                                seeds,
                                order['nomination'],
                                order['evidence'],
                                order['created'],
                            )
                            target = dict(
                                order_id=target_oid,
                                mint=order['mint'],
                                created_at=order['created'],
                                natural_nomination=True,
                                prospective_admission_valid=packet['prospective_admission_valid'],
                                scout_source=packet['scout_source'],
                                scout_eligible_after=packet['scout_eligible_after'],
                                scout_market_time=packet['scout_market_time'],
                                qualification_replay=replay,
                                packet=packet,
                                pump_position_opened=False,
                                graduation_handoff=None,
                                terminal=None,
                            )
                            report['candidates'].append(target)
                            if not packet['prospective_admission_valid']:
                                report['limitations'].append(
                                    'candidate_not_prospectively_admitted_watchlist_seed')
                                break
                            if replay != 'qualified':
                                report['limitations'].append('natural_order_failed_clean_qualification_replay')
                                break
                    else:
                        _monitor_existing(
                            engine,
                            pump_adapter,
                            now,
                            pumpswap_runtime=pumpswap_runtime,
                        )
                        order = store.state['orders'].get(target_oid) or {}
                        mint = target['mint']
                        position = store.state['positions'].get(mint)

                        if position is not None and _pump_fill_is_real_open_position(order):
                            target['pump_position_opened'] = True
                            target['pump_fill_snapshot'] = copy.deepcopy(order.get('fill_snapshot'))
                        if position is not None and position.get('postgrad_handoff'):
                            target['graduation_handoff'] = copy.deepcopy(position['postgrad_handoff'])
                            target['postgrad_surface'] = position.get('surface')

                        if _proof_complete(store, pumpswap_runtime, target_oid, target):
                            order = store.state['orders'][target_oid]
                            target['terminal'] = 'pumpswap_settled'
                            target['pumpswap_exit'] = copy.deepcopy(order['exit'])
                            report.update(
                                proof=True,
                                proven_order_id=target_oid,
                                proven_mint=target['mint'],
                                proven_scout_wallet=(target['packet']['nomination'] or {}).get('wallet'),
                                proven_scout_source=target['scout_source'],
                                proven_scout_eligible_after=target['scout_eligible_after'],
                                proven_scout_market_time=target['scout_market_time'],
                                prospective_admission_valid=True,
                                final_state_hash=digest(store.state),
                                reconciliation=True,
                                archive_verified=True,
                                pumpswap_continuation=pumpswap_runtime.status(),
                            )
                            break

                        if order.get('status') == 'cancelled' and position is None:
                            target['terminal'] = 'entry_cancelled'
                            target_oid = None
                            target = None
                            cursor = None
                        elif order.get('exit') and position is None:
                            target['terminal'] = (
                                'pumpswap_settled_without_pump_position'
                                if (order.get('exit') or {}).get('surface') == 'pumpswap'
                                else 'pump_settled_before_graduation'
                            )
                            target['exit'] = copy.deepcopy(order.get('exit'))
                            target_oid = None
                            target = None
                            cursor = None

                    report.update(
                        current_time=now,
                        stream=tape.status(now),
                        funnel=copy.deepcopy(store.state.get('funnel', {})),
                        active_orders=sum(o.get('status') == 'reserved' for o in store.state['orders'].values()),
                        active_positions=len(store.state['positions']),
                        provider=dict(
                            logical_requests=rpc.calls,
                            transport_requests=rpc.http_requests,
                            failures=rpc.failures,
                            retries=rpc.retries,
                            failure_kinds=copy.deepcopy(rpc.failure_kinds),
                        ),
                        provider_spend_usd=0 if url == 'https://api.mainnet-beta.solana.com' else None,
                        infrastructure_spend_usd=0,
                    )
                    _save(report)
                    if report['proof']:
                        break
                    stop.wait(POLL_SECONDS)

            store.reconcile()
            store.verify_archive()
            report.update(
                ended=int(time.time()),
                proof=bool(report.get('proof')),
                final_state_hash=digest(store.state),
                final_funnel=copy.deepcopy(store.state.get('funnel', {})),
                final_orders=len(store.state['orders']),
                final_positions=len(store.state['positions']),
                final_reserved_lamports=store.state['reserved'],
                reconciliation=True,
                archive_verified=True,
                pumpswap_continuation=pumpswap_runtime.status(),
                stream=tape.status(int(time.time())),
                stream_error_kind=stream.error_kind,
                provider=dict(
                    logical_requests=rpc.calls,
                    transport_requests=rpc.http_requests,
                    failures=rpc.failures,
                    retries=rpc.retries,
                    failure_kinds=copy.deepcopy(rpc.failure_kinds),
                ),
                provider_spend_usd=0 if url == 'https://api.mainnet-beta.solana.com' else None,
                infrastructure_spend_usd=0,
            )
            if not report['proof'] and not report['limitations']:
                report['limitations'].append('no_complete_natural_pump_to_pumpswap_settlement_observed')
            _save(report)
            store.close()
    finally:
        stop.set()
        thread.join(timeout=3)

    summary = dict(
        proof=report.get('proof', False),
        candidates=len(report.get('candidates', [])),
        proven_mint=report.get('proven_mint'),
        prospective_admission_valid=report.get('prospective_admission_valid', False),
        funnel=report.get('final_funnel', report.get('funnel', {})),
        limitations=report.get('limitations', []),
        provider=report.get('provider', {}),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if report.get('proof') else 2


if __name__ == '__main__':
    raise SystemExit(main())
