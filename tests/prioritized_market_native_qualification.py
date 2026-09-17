"""Prospective market-native qualification with policy-derived evidence scheduling.

This is a research-only successor to the Scout-vs-market-native comparison. The scout
lane is intentionally absent: the completed comparison already established that it
added zero unique discovery in that window. Broad market-native discovery remains
unchanged; this harness repairs the 20-of-1326 evidence bottleneck without changing
continuation-v1.

Provider budget hierarchy:
- unlimited-in-memory broad discovery from one finalized Pump stream;
- RPC-free guaranteed rejections from the current 60-second tape;
- at most 90 snapshot preflights spread across the entire 55-minute window;
- at most 20 concentration/final qualification evaluations, only after all other
  continuation-v1 gates pass the snapshot preflight.

No order, paper reservation, signing, transaction submission, or live-money authority
exists in this harness.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import Engine
from meme_machine.market_native_priority import (
    choose_slot_candidate,
    priority_slot_seconds,
    snapshot_preflight,
    stream_feasibility,
)
from meme_machine.market_native_shadow import discover_market_native
from meme_machine.provider import RPC, PumpAdapter, Unavailable
from meme_machine.research import qualification_vector
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

REPORT=Path(os.environ.get('MM_MARKET_NATIVE_PRIORITY_REPORT','market-native-priority-report.json'))
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-17 market-native evidence prioritization; research only'
DISCOVERY_SECONDS=max(120,min(int(os.environ.get('MM_MARKET_NATIVE_PRIORITY_SECONDS','3300')),3300))
PREFLIGHT_BUDGET=max(1,min(int(os.environ.get('MM_MARKET_NATIVE_PREFLIGHT_BUDGET','90')),90))
FULL_EVIDENCE_BUDGET=max(1,min(int(os.environ.get('MM_MARKET_NATIVE_FULL_EVIDENCE_BUDGET','20')),20))
SLOT_SECONDS=priority_slot_seconds(DISCOVERY_SECONDS,PREFLIGHT_BUDGET)
MAX_DISCOVERY_RECORDS=5000


def _save(report):
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))


def _rpc_snapshot(rpc,reader):
    status=reader.status()
    return dict(
        primary_logical=rpc.calls,
        primary_transport=rpc.http_requests,
        primary_failures=rpc.failures,
        primary_retries=rpc.retries,
        program_logical=status.get('program_scan_logical_requests',0),
        program_transport=status.get('program_scan_transport_requests',0),
        program_failures=status.get('program_scan_failures',0),
    )


def _delta(before,after):
    return {key:int(after.get(key,0))-int(before.get(key,0)) for key in before}


def _candidate_public(candidate,metric,slot):
    return dict(
        mint=candidate['mint'],
        discovery_time=int(candidate['discovery_time']),
        trigger=candidate['trigger'],
        slot=int(slot),
        stream_feasibility=metric.to_dict(),
    )


def _preflight(candidate,metric,tape,adapter,reader,workdir,index,full_remaining):
    nomination=candidate['nomination']
    result=dict(
        mint=candidate['mint'],nomination_id=nomination['id'],
        discovery_time=int(candidate['discovery_time']),stream_feasibility=metric.to_dict(),
        research_only=True,order_authority=False,preflight_complete=False,
        full_evidence_attempted=False,
    )
    before=_rpc_snapshot(adapter.rpc,reader)
    try:
        now=int(time.time())
        current=stream_feasibility(candidate,tape,now)
        result['stream_feasibility_at_execution']=current.to_dict()
        if not current.possible:
            result.update(preflight_reason=current.guaranteed_rejection,
                          preflight_skipped_without_rpc=True)
            return result

        snap=adapter.snapshot(candidate['mint'],now,priority=True)
        now=int(time.time())
        if not tape.covered(now):
            raise Unavailable('incomplete_market_window')
        events=tape.window(candidate['mint'],now,max_slot=snap['slot'])
        path=Path(workdir)/f'priority-{index}.db'
        store=Store(str(path),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        try:
            engine=Engine(store,[nomination['wallet']])
            pre=snapshot_preflight(engine,nomination,snap,events,now)
            result.update(
                preflight_complete=True,
                preflight_reason=pre['non_concentration_reason'] or 'passes_non_concentration',
                preflight=pre,
            )
            if not pre['passes_non_concentration'] or not full_remaining:
                return result

            result['full_evidence_attempted']=True
            concentration,meta=reader.read(candidate['mint'],snap,priority=True)
            final=adapter.snapshot(candidate['mint'],int(time.time()),priority=True)
            qualified_at=int(time.time())
            if not tape.covered(qualified_at):
                raise Unavailable('incomplete_market_window')
            events=tape.window(candidate['mint'],qualified_at,max_slot=final['slot'])
            vector=qualification_vector(
                engine,nomination,
                dict(snapshot=final,events=events,covered=True,concentration_bps=concentration),
                qualified_at,
            )
            result.update(
                full_evidence_complete=True,
                actual_reason=vector['actual_reason'],
                qualification_vector=vector,
                concentration_source=meta.get('source'),
                qualified_at=qualified_at,
            )
            return result
        finally:
            store.close()
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        result.update(preflight_reason='unavailable_executable_evidence',limitation=str(exc))
        return result
    finally:
        result['rpc_delta']=_delta(before,_rpc_snapshot(adapter.rpc,reader))


def main():
    started=int(time.time())
    report=dict(
        kind='prioritized_market_native_shadow',network='solana-mainnet',protocol='pump.fun',
        qualification_policy='continuation-v1',qualification_policy_frozen=True,
        scout_lane_active=False,scout_storage_active=False,market_native_order_authority=False,
        prioritization_authority='research_only',trigger_optimized_from_outcomes=False,
        discovery_seconds=DISCOVERY_SECONDS,preflight_budget=PREFLIGHT_BUDGET,
        full_evidence_budget=FULL_EVIDENCE_BUDGET,priority_slot_seconds=SLOT_SECONDS,
        started=started,discoveries=[],preflights=[],limitations=[],
    )
    _save(report)

    url=os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
    rpc=RPC(url,limit=240)
    adapter=PumpAdapter(rpc)
    reader=ConcentrationReader(rpc,secondary_url=os.environ.get('MM_SOLANA_CONCENTRATION_RPC_URL','').strip())
    tape=PumpTape();stop=threading.Event();ready=threading.Event();stream=PumpLogStream(url,tape)
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True);thread.start()

    discovered={}
    slot_rows=defaultdict(list)
    stream_rejections=Counter()
    preflights=[]
    full_attempts=0
    selected=0
    coverage_ready_at=None
    cursor=None
    last_flushed=-1

    with tempfile.TemporaryDirectory() as td:
        def process_slot(slot,now):
            nonlocal selected,full_attempts
            if selected>=PREFLIGHT_BUDGET:
                return
            chosen=choose_slot_candidate(slot_rows.pop(slot,[]))
            if chosen is None:
                return
            candidate,metric=chosen
            selected+=1
            full_remaining=full_attempts<FULL_EVIDENCE_BUDGET
            row=_preflight(candidate,metric,tape,adapter,reader,td,selected,full_remaining)
            if row.get('full_evidence_attempted'):
                full_attempts+=1
            row['slot']=slot
            preflights.append(row)
            report.update(
                current_time=now,
                preflights=preflights,
                preflight_selected=selected,
                full_evidence_attempted=full_attempts,
                provider=_rpc_snapshot(rpc,reader),
            )
            _save(report)

        try:
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            else:
                deadline=time.monotonic()+WINDOW_SECONDS+DISCOVERY_SECONDS
                while time.monotonic()<deadline:
                    now=int(time.time())
                    if stream.error_kind:
                        report['limitations'].append('stream_continuity_lost')
                        break
                    if not tape.covered(now):
                        cursor=None
                        stop.wait(0.25)
                        continue
                    if cursor is None:
                        cursor=tape.latest_sequence();coverage_ready_at=now
                        report['coverage_ready_at']=now
                        stop.wait(0.25)
                        continue

                    current_slot=max(0,(now-coverage_ready_at)//SLOT_SECONDS)
                    while last_flushed < current_slot-1:
                        last_flushed+=1
                        process_slot(last_flushed,now)

                    fresh,cursor=tape.events_since(cursor)
                    if fresh:
                        native=discover_market_native(fresh,tape,now,set(discovered))
                        for candidate in native:
                            mint=candidate['mint']
                            candidate=dict(candidate)
                            candidate['discovery_time']=now
                            metric=stream_feasibility(candidate,tape,now)
                            discovered[mint]=(candidate,metric,current_slot)
                            if not metric.possible:
                                stream_rejections[metric.guaranteed_rejection]+=1
                            else:
                                slot_rows[current_slot].append((candidate,metric))
                            if len(report['discoveries'])<MAX_DISCOVERY_RECORDS:
                                report['discoveries'].append(_candidate_public(candidate,metric,current_slot))
                    report.update(
                        current_time=now,discovered=len(discovered),
                        stream_guaranteed_rejections=dict(stream_rejections),
                        stream_feasible=sum(1 for _,metric,_ in discovered.values() if metric.possible),
                        stream=tape.status(now),
                    )
                    _save(report)
                    stop.wait(0.25)

                if coverage_ready_at is not None and selected<PREFLIGHT_BUDGET:
                    now=int(time.time())
                    current_slot=max(0,(now-coverage_ready_at)//SLOT_SECONDS)
                    while last_flushed<=current_slot and selected<PREFLIGHT_BUDGET:
                        last_flushed+=1
                        process_slot(last_flushed-1,now)
        finally:
            ended=int(time.time())
            stop.set();thread.join(timeout=3)
            complete=[row for row in preflights if row.get('full_evidence_complete')]
            reasons=Counter(row.get('actual_reason') for row in complete)
            pre_reasons=Counter(row.get('preflight_reason') for row in preflights)
            report.update(
                ended=ended,stream=tape.status(ended),stream_error_kind=stream.error_kind,
                discovered=len(discovered),stream_guaranteed_rejections=dict(stream_rejections),
                stream_feasible=sum(1 for _,metric,_ in discovered.values() if metric.possible),
                preflight_selected=selected,preflight_reason_distribution=dict(pre_reasons),
                full_evidence_attempted=full_attempts,full_evidence_complete=len(complete),
                full_reason_distribution=dict(reasons),
                qualified=sum(row.get('actual_reason')=='qualified' for row in complete),
                preflights=preflights,
                provider=dict(logical_requests=rpc.calls,transport_requests=rpc.http_requests,
                              failures=rpc.failures,retries=rpc.retries,
                              failure_kinds=rpc.failure_kinds),
                concentration_retrieval=reader.status(),
                provider_spend_usd=0 if url=='https://api.mainnet-beta.solana.com' else None,
                infrastructure_spend_usd=0,
            )
            if selected>=PREFLIGHT_BUDGET and len(discovered)>selected:
                report['limitations'].append('preflight_budget_exhausted')
            if full_attempts>=FULL_EVIDENCE_BUDGET:
                report['limitations'].append('full_evidence_budget_exhausted')
            _save(report)

    print(json.dumps(dict(
        discovered=report['discovered'],stream_feasible=report['stream_feasible'],
        stream_guaranteed_rejections=report['stream_guaranteed_rejections'],
        preflight_selected=report['preflight_selected'],
        preflight_reason_distribution=report['preflight_reason_distribution'],
        full_evidence_attempted=report['full_evidence_attempted'],
        full_evidence_complete=report['full_evidence_complete'],
        full_reason_distribution=report['full_reason_distribution'],
        qualified=report['qualified'],limitations=report['limitations'],provider=report['provider'],
    ),sort_keys=True))


if __name__=='__main__':
    main()
