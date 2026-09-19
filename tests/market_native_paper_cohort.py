"""Bounded natural Pump/PumpSwap paper cohort.

Unlike the one-lifecycle proof, discovery remains active after fills so the unchanged
shared allocator can admit multiple independent continuation-v1 paper positions.
Existing exposure is always monitored before new discovery/evidence work. A genuine
Pump -> PumpSwap graduation is recorded only if the market causes it naturally before
the position's normal +15% / -10% / 900s / liquidity-invalidation exit.

Paper only. No signing, submission, live-money or threshold authority exists here.
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
from meme_machine.solana_read_rpc import new_rpc, primary_rpc_url
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

REPORT=Path(os.environ.get('MM_MARKET_NATIVE_COHORT_REPORT',
                           'market-native-paper-cohort-report.json'))
DISCOVERY_SECONDS=max(1200,min(int(os.environ.get(
    'MM_MARKET_NATIVE_COHORT_DISCOVERY_SECONDS','5400')),5400))
POST_SECONDS=max(900,min(int(os.environ.get(
    'MM_MARKET_NATIVE_COHORT_POST_SECONDS','1100')),1800))
TARGET_SETTLED=max(2,min(int(os.environ.get(
    'MM_MARKET_NATIVE_COHORT_TARGET_SETTLED','3')),5))
PREFLIGHT_BUDGET=max(60,min(int(os.environ.get(
    'MM_MARKET_NATIVE_COHORT_PREFLIGHT_BUDGET','120')),150))
FULL_EVIDENCE_BUDGET=max(20,min(int(os.environ.get(
    'MM_MARKET_NATIVE_COHORT_FULL_EVIDENCE_BUDGET','30')),40))
RPC_LIMIT=240
RPC_ROTATE_AT=160
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE=('2026-09-18 bounded natural market-native paper cohort; '
                '$97.84/SOL reference retained for mechanical paper accounting')


def _save(report):
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))


def _paper_rows(state):
    rows=[]
    positions=state.get('positions',{})
    for oid,order in state.get('orders',{}).items():
        fill=order.get('fill')
        if not fill:
            continue
        exit_row=order.get('exit')
        mint=order.get('mint')
        exit_surface=(exit_row or {}).get('surface')
        postgrad=bool(order.get('postgrad_handoff')) or exit_surface=='pumpswap'
        position=positions.get(mint) or {}
        postgrad=postgrad or bool(position.get('postgrad_handoff')) or position.get('surface')=='pumpswap'
        rows.append(dict(
            order_id=oid,mint=mint,status=order.get('status'),
            created=order.get('created'),fill_time=fill.get('time'),
            fill_surface=fill.get('surface',order.get('surface','pump.fun')),
            fill_cost_lamports=fill.get('cost'),fill_tokens=fill.get('tokens'),
            terminal=bool(exit_row and mint not in positions),
            exit_reason=(exit_row or {}).get('reason'),
            exit_surface=exit_surface or ((exit_row or {}).get('snapshot') or {}).get('protocol'),
            exit_time=(exit_row or {}).get('time'),
            realized_lamports=(exit_row or {}).get('realized'),
            postgrad_handoff=postgrad,
            current_surface=position.get('surface'),
            unresolved=bool(position.get('unresolved')),
            last_exit_error=position.get('last_exit_error'),
        ))
    rows.sort(key=lambda r:(int(r.get('created') or 0),str(r.get('order_id'))))
    return rows


def _cohort_counts(state):
    rows=_paper_rows(state)
    return dict(
        filled=len(rows),
        settled=sum(r['terminal'] for r in rows),
        active_positions=len(state.get('positions',{})),
        reserved_orders=sum(o.get('status')=='reserved' for o in state.get('orders',{}).values()),
        pumpswap_handoffs=sum(r['postgrad_handoff'] for r in rows),
        pumpswap_settlements=sum(r['terminal'] and r.get('exit_surface')=='pumpswap' for r in rows),
    )


def _cohort_target_reached(state,target=TARGET_SETTLED):
    counts=_cohort_counts(state)
    return (counts['settled']>=int(target) and counts['active_positions']==0 and
            counts['reserved_orders']==0)


def main():
    started=int(time.time())
    report=dict(
        kind='market_native_natural_paper_cohort',network='solana-mainnet',
        paper_only=True,live_money_authority=False,signing_authority=False,
        submission_authority=False,qualification_policy='continuation-v1',
        qualification_policy_frozen=True,entry_thresholds_unchanged=True,
        normal_exit_policy_unchanged=True,graduation_forced=False,
        discovery_mode='market_native',scout_lane_active=False,fomo_authority=False,
        dlmm_enabled=False,target_settled=TARGET_SETTLED,
        discovery_seconds=DISCOVERY_SECONDS,post_seconds=POST_SECONDS,
        preflight_budget=PREFLIGHT_BUDGET,full_evidence_budget=FULL_EVIDENCE_BUDGET,
        rpc_rotation_threshold=RPC_ROTATE_AT,started=started,limitations=[],
        paper_rows=[],provider_sessions=[],
    )
    _save(report)

    url=primary_rpc_url()
    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'market-native-paper-cohort.db'),'prospective',
                    GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        _retire_scout_state(store)
        engine=Engine(store,[])
        tape=PumpTape();stop=threading.Event();ready=threading.Event()
        stream=PumpLogStream(url,tape)
        thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True);thread.start()

        rpc=new_rpc(limit=RPC_LIMIT)
        adapter=PumpAdapter(rpc)
        pumpswap=PumpSwapPaperRuntime(store,PostGraduationAdapter(rpc,scan_rpc=object()))
        runtime=MarketNativeRuntime(
            engine,adapter,DISCOVERY_SECONDS,
            preflight_budget=PREFLIGHT_BUDGET,
            full_evidence_budget=FULL_EVIDENCE_BUDGET,
            provider_rotation_threshold=RPC_ROTATE_AT,
        )
        session_started=int(time.time())
        cursor=None;discovery_ready_at=None;discovery_ended_at=None
        hard_deadline=time.monotonic()+WINDOW_SECONDS+DISCOVERY_SECONDS+POST_SECONDS+60

        def close_provider_session(reason,now):
            report['provider_sessions'].append(dict(
                started=session_started,ended=now,reason=reason,
                logical_requests=rpc.calls,transport_requests=rpc.http_requests,
                failures=rpc.failures,retries=rpc.retries,
                provider_topology=(rpc.provider_telemetry()
                                   if hasattr(rpc,'provider_telemetry') else None),
            ))

        try:
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            while time.monotonic()<hard_deadline and not report['limitations']:
                now=int(time.time())
                if stream.error_kind:
                    report['limitations'].append('stream_continuity_lost')
                    break

                # Monitoring existing capital always outranks discovery/evidence.
                _monitor_existing(engine,adapter,now,pumpswap_runtime=pumpswap)

                if rpc.calls>=RPC_ROTATE_AT:
                    close_provider_session('bounded_rpc_rotation',now)
                    session_started=now
                    rpc=new_rpc(limit=RPC_LIMIT,pacer=(rpc.read_pacer if hasattr(rpc,'read_pacer') else None))
                    adapter=PumpAdapter(rpc)
                    pumpswap=PumpSwapPaperRuntime(
                        store,PostGraduationAdapter(rpc,scan_rpc=object()))
                    runtime.replace_adapter(adapter)

                state=store.state
                counts=_cohort_counts(state)
                if discovery_ended_at is None:
                    cursor=runtime.tick(tape,now,cursor)
                    if runtime.coverage_ready_at is not None and discovery_ready_at is None:
                        discovery_ready_at=int(runtime.coverage_ready_at)
                        report['coverage_ready_at']=discovery_ready_at
                    elapsed=(0 if discovery_ready_at is None else now-discovery_ready_at)
                    if (_cohort_target_reached(state) or
                            (discovery_ready_at is not None and elapsed>=DISCOVERY_SECONDS)):
                        discovery_ended_at=now
                        report['discovery_ended_at']=now
                        report['discovery_end_reason']=(
                            'settlement_target_reached' if _cohort_target_reached(state)
                            else 'bounded_discovery_window_complete')
                else:
                    if _cohort_target_reached(state):
                        break
                    if (counts['active_positions']==0 and counts['reserved_orders']==0 and
                            counts['settled']>0):
                        break
                    if now-discovery_ended_at>=POST_SECONDS:
                        if counts['active_positions'] or counts['reserved_orders']:
                            report['limitations'].append(
                                'cohort_positions_not_terminal_within_post_window')
                        break

                report.update(
                    current_time=now,stream=tape.status(now),
                    market_native=runtime.status(),cohort_counts=counts,
                    paper_rows=_paper_rows(state),cash_lamports=state.get('cash'),
                    reserved_lamports=state.get('reserved'),rent_lamports=state.get('rent'),
                    realized_lamports=state.get('realized'),fees_lamports=state.get('fees'),
                )
                _save(report);stop.wait(1.0)
        finally:
            ended=int(time.time());stop.set();thread.join(timeout=3)
            close_provider_session('study_end',ended)
            try:
                reconciled=bool(store.reconcile())
                archive_verified=bool(store.verify_archive())
            except Exception as exc:
                reconciled=False;archive_verified=False
                report['limitations'].append(
                    f'integrity_verification_failed:{type(exc).__name__}')
            state=store.state;counts=_cohort_counts(state);rows=_paper_rows(state)
            report.update(
                ended=ended,cohort_counts=counts,paper_rows=rows,
                market_native=runtime.status(),stream=tape.status(ended),
                stream_error_kind=stream.error_kind,reconciled=reconciled,
                archive_verified=archive_verified,cash_lamports=state.get('cash'),
                reserved_lamports=state.get('reserved'),rent_lamports=state.get('rent'),
                realized_lamports=state.get('realized'),fees_lamports=state.get('fees'),
                natural_pumpswap_graduation_proven=counts['pumpswap_settlements']>0,
                provider_total_logical=sum(x['logical_requests'] for x in report['provider_sessions']),
                provider_total_transport=sum(x['transport_requests'] for x in report['provider_sessions']),
                provider_total_failures=sum(x['failures'] for x in report['provider_sessions']),
                provider_total_retries=sum(x['retries'] for x in report['provider_sessions']),
            )
            if (counts['settled']>=TARGET_SETTLED and reconciled and archive_verified and
                    not report['limitations']):
                result='market_native_natural_paper_cohort_target_reached'
            elif counts['settled']>0 and reconciled and archive_verified:
                result='market_native_natural_paper_cohort_partial'
            else:
                result='market_native_natural_paper_cohort_incomplete'
            report['result']=result
            _save(report);store.close()

    print(json.dumps(dict(
        result=report['result'],cohort_counts=report['cohort_counts'],
        natural_pumpswap_graduation_proven=report['natural_pumpswap_graduation_proven'],
        realized_lamports=report['realized_lamports'],reconciled=report['reconciled'],
        archive_verified=report['archive_verified'],limitations=report['limitations'],
        provider_total_logical=report['provider_total_logical'],
        provider_total_failures=report['provider_total_failures'],
    ),sort_keys=True))


if __name__=='__main__':
    main()
