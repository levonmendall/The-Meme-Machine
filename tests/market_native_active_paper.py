"""First real market-native active paper lifecycle proof.

This harness uses the active prospective MarketNativeRuntime and unchanged Engine paper
execution. It never signs or submits a transaction. Discovery is paused after the
first genuinely filled paper entry so the proof isolates one active lifecycle while
existing order/position monitoring and Pump -> PumpSwap continuation remain unchanged.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from meme_machine.__main__ import _monitor_existing, _retire_scout_state
from meme_machine.engine import Engine
from meme_machine.market_native_runtime import MarketNativeRuntime
from meme_machine.postgrad import PostGraduationAdapter
from meme_machine.provider import PumpAdapter
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.solana_read_rpc import new_rpc, primary_rpc_url, primary_ws_url
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

REPORT = Path(os.environ.get('MM_MARKET_NATIVE_PAPER_REPORT',
                             'market-native-active-paper-report.json'))
DISCOVERY_SECONDS = max(300, min(int(os.environ.get(
    'MM_MARKET_NATIVE_PAPER_DISCOVERY_SECONDS', '3300')), 3300))
POST_SECONDS = max(120, min(int(os.environ.get(
    'MM_MARKET_NATIVE_PAPER_POST_SECONDS', '1000')), 1000))
PREFLIGHT_BUDGET = max(1, min(int(os.environ.get(
    'MM_MARKET_NATIVE_PAPER_PREFLIGHT_BUDGET', '60')), 60))
FULL_EVIDENCE_BUDGET = max(1, min(int(os.environ.get(
    'MM_MARKET_NATIVE_PAPER_FULL_EVIDENCE_BUDGET', '20')), 20))
RPC_LIMIT = 240
RPC_ROTATE_AT = 200
# Use the same explicit paper genesis reference as the successful prioritized proof.
# This is mechanical paper evidence, not a profitability or current-NAV claim.
GENESIS_SOL_USD_MICROS = 97_840_000
GENESIS_SOURCE = ('2026-09-17 market-native active paper proof; '
                  '$97.84/SOL reference retained from prioritized proof')


def _save(report):
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True))


def _order_summary(order_id, order):
    fill = order.get('fill') or {}
    exit_row = order.get('exit') or {}
    nomination = order.get('nomination') or {}
    evidence = order.get('evidence') or {}
    snapshot = evidence.get('snapshot') or {}
    return dict(
        order_id=order_id,
        mint=order.get('mint'),
        status=order.get('status'),
        created=order.get('created'),
        due=order.get('due'),
        nomination_id=nomination.get('id'),
        nomination_source=nomination.get('discovery_source'),
        nomination_market_time=nomination.get('market_time'),
        qualification_snapshot_kind=snapshot.get('kind'),
        qualification_snapshot_slot=snapshot.get('slot'),
        concentration_bps=evidence.get('concentration_bps'),
        fill=(dict(slot=fill.get('slot'), market_time=fill.get('market_time'),
                   available_time=fill.get('available_time'), time=fill.get('time'),
                   tokens=fill.get('tokens'), cost=fill.get('cost'), fee=fill.get('fee'),
                   gas=fill.get('gas')) if fill else None),
        exit=(dict(reason=exit_row.get('reason'), proceeds=exit_row.get('proceeds'),
                   fee=exit_row.get('fee'), gas=exit_row.get('gas'),
                   realized=exit_row.get('realized'), time=exit_row.get('time'),
                   surface=(exit_row.get('snapshot') or {}).get('protocol'))
              if exit_row else None),
        surface=order.get('surface', 'pump.fun'),
        postgrad_handoff=bool(order.get('postgrad_handoff')),
    )


def _first_filled_order(state):
    rows=[]
    for oid, order in state.get('orders', {}).items():
        if order.get('status') == 'settled' and order.get('fill'):
            rows.append((int(order.get('created', 0)), str(oid), oid, order))
    if not rows:
        return None
    _created, _stable, oid, order = min(rows)
    return oid, order


def _has_reserved_order(state):
    return any(order.get('status') == 'reserved'
               for order in state.get('orders', {}).values())


def _target_terminal(state, target_id):
    if target_id is None:
        return False
    order = state.get('orders', {}).get(target_id) or {}
    mint = order.get('mint')
    return bool(order.get('exit') and mint not in state.get('positions', {}))


def main():
    started = int(time.time())
    report = dict(
        kind='market_native_active_paper_lifecycle',
        network='solana-mainnet',
        paper_only=True,
        live_money_authority=False,
        signing_authority=False,
        submission_authority=False,
        qualification_policy='continuation-v1',
        qualification_policy_frozen=True,
        discovery_mode='market_native',
        scout_lane_active=False,
        dlmm_enabled=False,
        fomo_authority=False,
        initial_usd_micros=500_000_000,
        initial_sol_usd_micros=GENESIS_SOL_USD_MICROS,
        valuation_source=GENESIS_SOURCE,
        discovery_seconds=DISCOVERY_SECONDS,
        post_seconds=POST_SECONDS,
        started=started,
        target_order_id=None,
        target_entry_observed_at=None,
        target_terminal=False,
        provider_sessions=[],
        limitations=[],
    )
    _save(report)

    url = primary_rpc_url()
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / 'market-native-active-paper.db')
        store = Store(db, 'prospective', GENESIS_SOL_USD_MICROS, GENESIS_SOURCE)
        _retire_scout_state(store)
        engine = Engine(store, [])
        tape = PumpTape()
        stop = threading.Event()
        ready = threading.Event()
        stream = PumpLogStream(url, tape, ws_url=primary_ws_url())
        thread = threading.Thread(target=stream.run, args=(stop, ready), daemon=True)
        thread.start()

        rpc = new_rpc(limit=RPC_LIMIT)
        adapter = PumpAdapter(rpc)
        postgrad = PostGraduationAdapter(rpc, scan_rpc=object())
        pumpswap = PumpSwapPaperRuntime(store, postgrad)
        runtime = MarketNativeRuntime(
            engine, adapter, DISCOVERY_SECONDS,
            preflight_budget=PREFLIGHT_BUDGET,
            full_evidence_budget=FULL_EVIDENCE_BUDGET,
        )
        session_started = int(time.time())
        report['provider_sessions'].append(dict(started=session_started))

        cursor = None
        target_id = None
        discovery_ready_at = None
        post_deadline = None
        hard_deadline = time.monotonic() + WINDOW_SECONDS + DISCOVERY_SECONDS + POST_SECONDS
        try:
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            while time.monotonic() < hard_deadline and not report['limitations']:
                now = int(time.time())
                if stream.error_kind:
                    report['limitations'].append('stream_continuity_lost')
                    break

                _monitor_existing(engine, adapter, now, pumpswap_runtime=pumpswap)
                state = store.state

                if target_id is None:
                    filled = _first_filled_order(state)
                    if filled is not None:
                        target_id, _order = filled
                        report['target_order_id'] = target_id
                        report['target_entry_observed_at'] = now
                        post_deadline = time.monotonic() + POST_SECONDS
                    elif not _has_reserved_order(state):
                        cursor = runtime.tick(tape, now, cursor)
                        if runtime.coverage_ready_at is not None and discovery_ready_at is None:
                            discovery_ready_at = int(runtime.coverage_ready_at)
                            report['coverage_ready_at'] = discovery_ready_at
                        if (discovery_ready_at is not None and
                                now - discovery_ready_at >= DISCOVERY_SECONDS):
                            report['limitations'].append('no_filled_market_native_entry_in_discovery_window')
                            break

                if target_id is not None:
                    if _target_terminal(state, target_id):
                        report['target_terminal'] = True
                        break
                    if post_deadline is not None and time.monotonic() >= post_deadline:
                        report['limitations'].append('target_lifecycle_not_terminal_within_post_window')
                        break

                    # After entry, discovery is intentionally paused. Rotate only the
                    # read-only RPC client before its logical cap; Store/Engine state
                    # and all execution rules remain unchanged across the rotation.
                    if rpc.calls >= RPC_ROTATE_AT:
                        report['provider_sessions'][-1].update(
                            ended=now, logical_requests=rpc.calls,
                            transport_requests=rpc.http_requests,
                            failures=rpc.failures, retries=rpc.retries,
                            provider_topology=(rpc.provider_telemetry()
                                               if hasattr(rpc,'provider_telemetry') else None))
                        rpc = new_rpc(limit=RPC_LIMIT,pacer=(rpc.read_pacer if hasattr(rpc,'read_pacer') else None))
                        adapter = PumpAdapter(rpc)
                        postgrad = PostGraduationAdapter(rpc, scan_rpc=object())
                        pumpswap = PumpSwapPaperRuntime(store, postgrad)
                        report['provider_sessions'].append(dict(started=now,
                                                               reason='bounded_rpc_rotation'))

                report.update(
                    current_time=now,
                    stream=tape.status(now),
                    market_native=runtime.status(),
                    target=(_order_summary(target_id, state['orders'][target_id])
                            if target_id in state.get('orders', {}) else None),
                    funnel=dict(state.get('funnel', {})),
                    cash_lamports=state.get('cash'),
                    reserved_lamports=state.get('reserved'),
                    realized_lamports=state.get('realized'),
                    active_positions=len(state.get('positions', {})),
                )
                _save(report)
                stop.wait(1.0)
        finally:
            ended = int(time.time())
            stop.set(); thread.join(timeout=3)
            report['provider_sessions'][-1].update(
                ended=ended, logical_requests=rpc.calls,
                transport_requests=rpc.http_requests,
                failures=rpc.failures, retries=rpc.retries,
                provider_topology=(rpc.provider_telemetry()
                                   if hasattr(rpc,'provider_telemetry') else None))
            try:
                reconciled = bool(store.reconcile())
                archive_verified = bool(store.verify_archive())
            except Exception as exc:
                reconciled = False
                archive_verified = False
                report['limitations'].append(f'integrity_verification_failed:{type(exc).__name__}')
            state = store.state
            report.update(
                ended=ended,
                target_terminal=bool(target_id is not None and _target_terminal(state, target_id)),
                target=(_order_summary(target_id, state['orders'][target_id])
                        if target_id in state.get('orders', {}) else None),
                final_status=engine.status(ended),
                market_native=runtime.status(),
                stream=tape.status(ended),
                stream_error_kind=stream.error_kind,
                stream_last_error_kind=getattr(stream,'last_error_kind',None),
                stream_connections=getattr(stream,'connections',0),
                stream_reconnects=getattr(stream,'reconnects',0),
                reconciled=reconciled,
                archive_verified=archive_verified,
                provider_total_logical=sum(int(x.get('logical_requests', 0))
                                           for x in report['provider_sessions']),
                provider_total_transport=sum(int(x.get('transport_requests', 0))
                                             for x in report['provider_sessions']),
                provider_total_failures=sum(int(x.get('failures', 0))
                                            for x in report['provider_sessions']),
                provider_total_retries=sum(int(x.get('retries', 0))
                                           for x in report['provider_sessions']),
            )
            if report['target_terminal'] and not report['limitations']:
                report['result'] = 'market_native_active_paper_lifecycle_proven'
            else:
                report['result'] = 'market_native_active_paper_lifecycle_incomplete'
            _save(report)
            store.close()

    print(json.dumps(dict(
        result=report['result'], target_terminal=report['target_terminal'],
        target=report.get('target'), funnel=(report.get('final_status') or {}).get('funnel'),
        reconciled=report['reconciled'], archive_verified=report['archive_verified'],
        market_native=report.get('market_native'), limitations=report['limitations'],
        provider_total_logical=report['provider_total_logical'],
        provider_total_failures=report['provider_total_failures'],
    ), sort_keys=True))


if __name__ == '__main__':
    main()
