"""One-shot real-data mechanical canary with no strategy or live-money authority.

This is intentionally NOT a prospective strategy experiment. It waits for a real
finalized Pump.fun buy, records the unchanged continuation-v1 result, then overrides
only paper authorization in an isolated temporary store so the downstream reservation,
delayed fill, restart, monitor, forced mechanical close, settlement and reconciliation
machinery can be exercised against contemporaneous real observations.

No transaction is signed/submitted. No authoritative portfolio is touched. Any P&L is
canary plumbing evidence only and must never be used as strategy/performance evidence.
"""
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import DELAY, MAX_AGE, Engine, MAYHEM_AGENT_WALLET
from meme_machine.provider import PumpAdapter, Unavailable
from meme_machine.solana_read_rpc import new_rpc, primary_rpc_url
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

GENESIS_SOL_USD_MICROS = 97_840_000
GENESIS_SOURCE = (
    '2026-09-16 canary reference $97.84/SOL; isolated forced mechanical test, '
    'not portfolio or performance continuity'
)
CANDIDATE_WAIT_SECONDS = 55
MAX_CANDIDATE_MINTS = 6
LATER_SNAPSHOT_WAIT_SECONDS = 18


def _wait_later_snapshot(adapter, mint, min_slot, min_market_time, timeout=LATER_SNAPSHOT_WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    last_kind = 'later_snapshot_timeout'
    while time.monotonic() < deadline:
        requested_at = int(time.time())
        try:
            snap = adapter.snapshot(mint, requested_at, priority=True)
            now = max(int(time.time()), int(snap['available_time']))
            if snap['slot'] > int(min_slot) and snap['market_time'] >= int(min_market_time):
                return snap, now
            last_kind = 'finality_not_advanced'
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            last_kind = str(exc) or type(exc).__name__
        time.sleep(1.0)
    raise Unavailable(last_kind)


def _report_error(report, stage, exc):
    report.update(success=False, terminal_stage=stage,
                  blocker=str(exc) if isinstance(exc, (Unavailable, ValueError)) else type(exc).__name__)
    return report


def main():
    url = primary_rpc_url()
    report = dict(
        kind='forced_real_data_canary',
        network='solana-mainnet', protocol='pump.fun',
        isolated_temporary_store=True,
        forced_authorization=True,
        forced_close_allowed=True,
        continuation_v1_modified=False,
        authoritative_portfolio_touched=False,
        order_submission_authority=False,
        signing_authority=False,
        live_money_authority=False,
        portfolio_performance_claim=False,
        provider_spend_usd=0,
        infrastructure_spend_usd=0,
        started=int(time.time()),
    )
    rpc = new_rpc(limit=160)
    adapter = None
    reader = None
    tape = PumpTape()
    stop = threading.Event()
    ready = threading.Event()
    stream = PumpLogStream(url, tape)
    thread = threading.Thread(target=stream.run, args=(stop, ready), daemon=True)
    thread.start()
    store = None
    stage = 'startup'
    try:
        adapter = PumpAdapter(rpc)
        reader = ConcentrationReader(rpc)
        if not ready.wait(15) or stream.error_kind:
            raise Unavailable('stream_subscription_unavailable')

        stage = 'stream_warmup'
        warm_deadline = time.monotonic() + WINDOW_SECONDS + 12
        while time.monotonic() < warm_deadline and not tape.covered(int(time.time())):
            if stream.error_kind:
                raise Unavailable('stream_continuity_lost')
            time.sleep(0.25)
        if not tape.covered(int(time.time())):
            raise Unavailable('stream_never_reached_complete_window')

        cursor = tape.latest_sequence()
        selected = None
        seen_mints = set()
        candidate_deadline = time.monotonic() + CANDIDATE_WAIT_SECONDS
        stage = 'candidate_selection'
        while time.monotonic() < candidate_deadline and selected is None:
            if stream.error_kind or not tape.covered(int(time.time())):
                raise Unavailable('stream_continuity_lost')
            fresh, cursor = tape.events_since(cursor)
            for event in fresh:
                if not event.get('buy') or event.get('wallet') == MAYHEM_AGENT_WALLET:
                    continue
                mint = event.get('mint')
                if not mint or mint in seen_mints:
                    continue
                seen_mints.add(mint)
                if len(seen_mints) > MAX_CANDIDATE_MINTS:
                    break
                requested_at = int(time.time())
                try:
                    snap = adapter.snapshot(mint, requested_at, priority=True)
                    evaluated_at = max(int(time.time()), int(snap['available_time']))
                    curve = pump.curve(snap['accounts'][0])
                    if curve.complete or curve.real_token <= 0 or curve.real_sol <= 0:
                        continue
                    if not snap['market_time'] <= snap['available_time'] <= evaluated_at:
                        continue
                    if evaluated_at - snap['market_time'] > MAX_AGE:
                        continue
                except (Unavailable, ValueError, KeyError, TypeError):
                    continue
                selected = (dict(event), snap)
                break
            if len(seen_mints) > MAX_CANDIDATE_MINTS and selected is None:
                break
            if selected is None:
                time.sleep(0.25)
        if selected is None:
            raise Unavailable('no_supported_post_warmup_buy_for_canary')

        nomination, preliminary = selected
        mint = nomination['mint']
        report.update(candidate_mint=mint, candidate_event_id=nomination['id'],
                      candidate_wallet=nomination['wallet'], preliminary_snapshot_slot=preliminary['slot'])

        stage = 'concentration'
        concentration = None
        concentration_meta = None
        concentration_error = None
        try:
            concentration, concentration_meta = reader.read(mint, preliminary, priority=True)
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            concentration_error = str(exc) or type(exc).__name__

        # Refresh the quote *after* concentration retrieval. The prior harness used
        # a `now` captured before its RPC call, which could make available_time appear
        # one second in the future. Product validation correctly rejected that harness
        # mistake as stale_or_future_quote.
        stage = 'authorization_snapshot'
        initial = adapter.snapshot(mint, int(time.time()), priority=True)
        authorization_now = max(int(time.time()), int(initial['available_time']))
        if concentration_meta is not None and int(concentration_meta['slot']) < int(initial['slot']) - 32:
            try:
                concentration, concentration_meta = reader.read(mint, initial, priority=True)
                concentration_error = None
            except (Unavailable, ValueError, KeyError, TypeError) as exc:
                concentration = None
                concentration_meta = None
                concentration_error = str(exc) or type(exc).__name__
            initial = adapter.snapshot(mint, int(time.time()), priority=True)
            authorization_now = max(int(time.time()), int(initial['available_time']))

        report.update(initial_snapshot_slot=initial['slot'],
                      signal_age_seconds=max(0, authorization_now-int(nomination['market_time'])),
                      concentration_bps=concentration,
                      concentration_source=None if concentration_meta is None else concentration_meta['source'],
                      concentration_slot=None if concentration_meta is None else concentration_meta['slot'],
                      concentration_error=concentration_error)

        stage = 'unchanged_policy_evaluation'
        history = tape.window(mint, authorization_now, max_slot=initial['slot'])
        evidence = dict(snapshot=initial, events=history, covered=True,
                        concentration_bps=concentration)

        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / 'forced-canary.db')
            store = Store(db_path, 'prospective', GENESIS_SOL_USD_MICROS, GENESIS_SOURCE)
            initial_cash = store.state['cash']
            engine = Engine(store, [nomination['wallet']])
            try:
                policy_reason = engine.qualify(nomination, evidence, authorization_now)
            except (Unavailable, ValueError, KeyError, TypeError) as exc:
                policy_reason = 'unavailable_executable_evidence:' + (str(exc) or type(exc).__name__)
            report.update(unchanged_policy_reason=policy_reason,
                          market_window_events=len(history), market_window_covered=True)

            stage = 'forced_authorization'
            original_qualify = engine.qualify
            engine.qualify = lambda _nomination, _evidence, _now: 'qualified'
            try:
                authorization = engine.consider(nomination, evidence, authorization_now)
            finally:
                engine.qualify = original_qualify
            report['forced_authorization_result'] = authorization
            if authorization != 'qualified':
                raise Unavailable('forced_reservation_not_created')

            order = store.state['orders'][nomination['id']]
            report.update(reservation_lamports=order['reservation'], entry_budget_lamports=order['budget'],
                          entry_due=order['due'])

            stage = 'delayed_entry_fill'
            time.sleep(max(0.0, order['due'] - time.time() + 0.25))
            fill_snap, fill_now = _wait_later_snapshot(adapter, mint, order['slot'], order['due'])
            fill_result = engine.fill(nomination['id'], fill_snap, fill_now)
            report.update(fill_result=fill_result, fill_snapshot_slot=fill_snap['slot'])
            if fill_result != 'settled':
                report.update(success=True, terminal_stage='entry_attempt_terminal', downstream_reached=False,
                              cash_unchanged=store.state['cash']==initial_cash,
                              isolated_state=engine.status(int(time.time())))
                store.verify_archive()
                return print(json.dumps(report, sort_keys=True))

            fill = store.state['orders'][nomination['id']]['fill']
            report.update(entry_tokens=fill['tokens'], entry_cost_lamports=fill['cost'],
                          entry_fee_lamports=fill['fee'])

            stage = 'restart_reconciliation'
            store.close(); store = None
            store = Store(db_path, 'prospective', GENESIS_SOL_USD_MICROS, GENESIS_SOURCE)
            engine = Engine(store, [nomination['wallet']])
            report['restart_reconciled'] = bool(store.reconcile())
            if mint not in store.state['positions']:
                raise Unavailable('position_missing_after_restart')

            stage = 'first_monitor'
            next_monitor = store.state['positions'][mint]['next_monitor']
            time.sleep(max(0.0, next_monitor - time.time() + 0.25))
            monitor_snap, monitor_now = _wait_later_snapshot(adapter, mint, fill_snap['slot'], next_monitor)
            first_monitor = engine.monitor(mint, monitor_snap, monitor_now)
            report.update(first_monitor_result=first_monitor, first_monitor_slot=monitor_snap['slot'])
            if first_monitor == 'unresolved':
                raise Unavailable('real_exit_mark_unavailable')

            forced_close = False
            if mint in store.state['positions'] and first_monitor == 'holding':
                with store.transaction('forced_canary_exit_intent'):
                    p = store.state['positions'][mint]
                    p.update(exit_due=monitor_now+DELAY,
                             exit_reason='forced_canary_mechanical_close',
                             exit_slot=monitor_snap['slot'])
                forced_close = True
            report['forced_close_intent'] = forced_close

            stage = 'exit_settlement'
            attempts = 0
            terminal = first_monitor
            while mint in store.state['positions'] and attempts < 3:
                p = store.state['positions'][mint]
                due = max(int(p['next_monitor']), int(p.get('exit_due') or 0))
                time.sleep(max(0.0, due - time.time() + 0.25))
                exit_snap, exit_now = _wait_later_snapshot(
                    adapter, mint, int(p.get('exit_slot', p['entry_slot'])), due)
                terminal = engine.monitor(mint, exit_snap, exit_now)
                attempts += 1
                report.update(exit_snapshot_slot=exit_snap['slot'], exit_monitor_result=terminal,
                              exit_monitor_attempts=attempts)
                if terminal in ('settled','unresolved','exit_failed','gas_exhausted'):
                    break

            stage = 'final_reconciliation'
            reconciled = bool(store.reconcile())
            archive_verified = bool(store.verify_archive())
            settled = mint not in store.state['positions'] and terminal == 'settled'
            order_final = store.state['orders'][nomination['id']]
            report.update(success=True, terminal_stage='settled' if settled else 'open_or_unresolved',
                          settled=settled, final_reconciled=reconciled,
                          archive_verified=archive_verified,
                          final_cash_lamports=store.state['cash'],
                          final_realized_lamports=store.state['realized'],
                          final_fees_lamports=store.state['fees'],
                          order_has_exit='exit' in order_final,
                          remaining_positions=len(store.state['positions']),
                          remaining_reserved_lamports=store.state['reserved'])
    except Exception as exc:
        _report_error(report, stage, exc)
    finally:
        if store is not None:
            try:
                report.setdefault('final_reconciled', bool(store.reconcile()))
                report.setdefault('archive_verified', bool(store.verify_archive()))
            except Exception:
                report.setdefault('final_reconciled', False)
            store.close()
        stop.set(); thread.join(timeout=3)
        report.update(ended=int(time.time()), stream=tape.status(int(time.time())),
                      stream_error_kind=stream.error_kind,
                      http_logical_requests=rpc.calls,
                      http_transport_requests=rpc.http_requests,
                      http_failures=rpc.failures,
                      http_retries=rpc.retries,
                      http_failure_kinds=rpc.failure_kinds,
                      provider_spend_usd=0 if rpc.failover_count==0 else None,
                      provider_topology=rpc.provider_telemetry(),
                      concentration_retrieval={} if reader is None else reader.status())
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()