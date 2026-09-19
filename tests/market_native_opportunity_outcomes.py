"""Research-only market-native opportunity outcome study.

One finalized Pump stream supports five questions without granting trading authority:
1. high-density (>100 event) candidates are tracked instead of disappearing at the
   evidence-capacity gate;
2. every policy-feasible candidate that loses its prioritizer slot is forward-labeled;
3. the unbiased fixed-time-slot natural sample receives full continuation-v1 evidence
   and 5/7.5/10 SOL liquidity counterfactual tags;
4. naturally qualified rows receive a trade-price-proxy +15/-10/900s shadow exit and
   are still tracked after that exit;
5. future labels are attached only after their original decision timestamp.

No Engine.consider call occurs. No order, reservation, signing or submission exists.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import Engine, GAS
from meme_machine.market_native_priority import (
    choose_slot_candidate, priority_slot_seconds, stream_feasibility,
)
from meme_machine.market_native_runtime import MarketNativeAuthority
from meme_machine.market_native_shadow import discover_market_native
from meme_machine.outcome_research import (
    DEFAULT_HORIZONS, enable_shadow_exit, high_density_features,
    is_two_buyer_sole_near_miss, liquidity_floor_eligibility, new_tracker,
    observe_trade, subclass_research_protocol, summarize_liquidity_counterfactual,
    summarize_post_exit_tail, summarize_trackers, summarize_two_buyer_near_misses,
    two_buyer_research_candidate,
)
from meme_machine.provider import RPC, PumpAdapter, Unavailable
from meme_machine.research import CURRENT_THRESHOLDS
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

REPORT=Path(os.environ.get('MM_MARKET_NATIVE_OUTCOME_REPORT','market-native-opportunity-outcomes.json'))
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-17 market-native opportunity outcome research; no order authority'
DISCOVERY_SECONDS=max(600,min(int(os.environ.get('MM_MARKET_NATIVE_OUTCOME_DISCOVERY_SECONDS','3300')),3300))
FOLLOWUP_SECONDS=max(300,min(int(os.environ.get('MM_MARKET_NATIVE_OUTCOME_FOLLOWUP_SECONDS','3600')),3600))
NATURAL_BUDGET=max(10,min(int(os.environ.get('MM_MARKET_NATIVE_OUTCOME_NATURAL_BUDGET','120')),120))
PRIORITY_BUDGET=max(1,min(int(os.environ.get('MM_MARKET_NATIVE_OUTCOME_PRIORITY_BUDGET','180')),180))
EXTRA_EVIDENCE_BUDGET=max(0,min(int(os.environ.get('MM_MARKET_NATIVE_OUTCOME_EXTRA_EVIDENCE_BUDGET','180')),240))
EXTRA_EVIDENCE_PER_SLOT=max(1,min(int(os.environ.get('MM_MARKET_NATIVE_OUTCOME_EXTRA_EVIDENCE_PER_SLOT','3')),5))
NATURAL_SLOT_SECONDS=max(1,math.ceil(DISCOVERY_SECONDS/NATURAL_BUDGET))
PRIORITY_SLOT_SECONDS=priority_slot_seconds(DISCOVERY_SECONDS,PRIORITY_BUDGET)
MAX_DISCOVERED=10_000
ROTATE_AT=205
CONCENTRATION_ROTATE_AT=32


def _save(report):
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))


def _event_baseline(candidate):
    event=candidate['nomination']
    return int(event['amount']),int(event['tokens']),int(event['market_time'])


class EvidenceSessions:
    def __init__(self,url):
        self.url=url
        self.sessions=[]
        self.rpc=None;self.adapter=None;self.reader=None
        self.rotate('initial')

    def _close_current(self,reason=None):
        if self.rpc is None:
            return
        concentration=self.reader.status() if self.reader is not None else {}
        self.sessions[-1].update(
            ended=int(time.time()),logical_requests=self.rpc.calls,
            transport_requests=self.rpc.http_requests,failures=self.rpc.failures,
            retries=self.rpc.retries,concentration=concentration,
        )
        if reason:
            self.sessions[-1]['ended_reason']=reason

    def rotate(self,reason):
        if self.rpc is not None:
            self._close_current(reason)
        self.rpc=RPC(self.url,limit=240)
        self.adapter=PumpAdapter(self.rpc)
        self.reader=ConcentrationReader(
            self.rpc,secondary_url=os.environ.get('MM_SOLANA_CONCENTRATION_RPC_URL','').strip())
        self.sessions.append(dict(started=int(time.time()),reason=reason))

    def maybe_rotate(self):
        concentration=self.reader.status() if self.reader is not None else {}
        if int(concentration.get('program_scan_logical_requests',0))>=CONCENTRATION_ROTATE_AT:
            self.rotate('bounded_concentration_reader_rotation')
        elif self.rpc.calls>=ROTATE_AT:
            self.rotate('bounded_research_rpc_rotation')

    def finish(self):
        self._close_current('study_end')


def _evaluate_natural(candidate,tape,evidence,authority,engine):
    nomination=dict(candidate['nomination']);nomination['discovery_source']='market_native'
    row=dict(
        mint=candidate['mint'],nomination_id=nomination['id'],
        natural_market_native_sample=True,evidence_stage='started',
        sampling_rule='first_new_market_native_candidate_in_fixed_time_slot',
        selection_uses_policy_score=False,selection_uses_future_outcomes=False,
        research_only=True,order_authority=False,
        nomination_market_time=int(nomination['market_time']),
    )
    try:
        evidence.maybe_rotate()
        now=int(time.time())
        if not tape.covered(now):
            raise Unavailable('incomplete_market_window')
        initial=evidence.adapter.snapshot(candidate['mint'],now,priority=True)
        concentration,meta=evidence.reader.read(candidate['mint'],initial,priority=True)
        final=evidence.adapter.snapshot(candidate['mint'],int(time.time()),priority=True)
        qualified_at=int(time.time())
        if not tape.covered(qualified_at):
            raise Unavailable('incomplete_market_window')
        events=tape.window(candidate['mint'],qualified_at,max_slot=final['slot'])
        vector=authority.vector(
            nomination,dict(snapshot=final,events=events,covered=True,
                            concentration_bps=concentration),qualified_at)
        c,rates=engine.validate_snapshot(final,qualified_at)
        amount=engine.store.state['initial']//20
        tokens,cost,fee=pump.buy(c,amount,rates)
        row.update(
            evidence_stage='complete',qualified_at=qualified_at,
            actual_reason=vector['actual_reason'],qualification_vector=vector,
            evidence_events=len(events),concentration_bps=concentration,
            concentration_source=meta.get('source'),
            entry_quote=dict(tokens=tokens,cost_lamports=cost,fee_lamports=fee,
                             gas_lamports=GAS,basis_lamports=cost+GAS),
            liquidity_floor_eligibility=liquidity_floor_eligibility(vector),
        )
        baseline_num=cost+GAS;baseline_den=tokens;origin=qualified_at
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        row.update(evidence_stage='incomplete',actual_reason='unavailable_executable_evidence',
                   limitation=str(exc) or type(exc).__name__)
        baseline_num,baseline_den,origin=_event_baseline(candidate)
    cohorts=['natural_sample']
    if is_two_buyer_sole_near_miss(row):
        cohorts.append('two_buyer_sole_near_miss')
    tracker=new_tracker(
        candidate['mint'],origin,baseline_num,baseline_den,cohorts,
        nomination_id=nomination['id'],metadata={'evidence_stage':row['evidence_stage']})
    if row.get('actual_reason')=='qualified' and row.get('evidence_stage')=='complete':
        enable_shadow_exit(tracker,opened_time=origin)
    return row,tracker



def _evaluate_extra_preflight(candidate,metric,tape,evidence,authority):
    nomination=dict(candidate['nomination']);nomination['discovery_source']='market_native'
    row=dict(
        mint=candidate['mint'],nomination_id=nomination['id'],
        cohort='feasible_unpreflighted_extra_evidence',
        research_only=True,order_authority=False,preflight_complete=False,
        full_evidence_complete=False,stream_feasibility=metric.to_dict(),
    )
    try:
        evidence.maybe_rotate()
        now=int(time.time())
        snap=evidence.adapter.snapshot(candidate['mint'],now,priority=True)
        now=int(time.time())
        if not tape.covered(now):
            raise Unavailable('incomplete_market_window')
        events=tape.window(candidate['mint'],now,max_slot=snap['slot'])
        pre=authority.vector(
            nomination,dict(snapshot=snap,events=events,covered=True,concentration_bps=0),now)
        pre_two_buyer=two_buyer_research_candidate(pre)
        row.update(
            preflight_complete=True,
            preflight_reason=(None if pre.get('actual_reason')=='qualified' else pre.get('actual_reason')),
            preflight_vector=pre,
            two_buyer_research_candidate=pre_two_buyer,
        )
        if pre.get('actual_reason')!='qualified' and not pre_two_buyer:
            return row
        concentration,meta=evidence.reader.read(candidate['mint'],snap,priority=True)
        final=evidence.adapter.snapshot(candidate['mint'],int(time.time()),priority=True)
        qualified_at=int(time.time())
        if not tape.covered(qualified_at):
            raise Unavailable('incomplete_market_window')
        events=tape.window(candidate['mint'],qualified_at,max_slot=final['slot'])
        vector=authority.vector(
            nomination,dict(snapshot=final,events=events,covered=True,
                            concentration_bps=concentration),qualified_at)
        sole_two=bool(
            int(vector.get('independent_buyer_groups') or -1)==2 and
            (((vector.get('sensitivity') or {}).get('values') or {})
             .get('min_independent_groups') or {}).get('2',False) and
            not bool(vector.get('current_threshold_pass'))
        )
        row.update(
            full_evidence_complete=True,qualified_at=qualified_at,
            actual_reason=vector.get('actual_reason'),qualification_vector=vector,
            concentration_bps=concentration,concentration_source=meta.get('source'),
            two_buyer_sole_near_miss=sole_two,
        )
        return row
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        row.update(
            actual_reason='unavailable_executable_evidence',
            limitation=str(exc) or type(exc).__name__,
        )
        return row

def main():
    started=int(time.time())
    report=dict(
        kind='market_native_opportunity_outcome_study',network='solana-mainnet',protocol='pump.fun',
        qualification_policy='continuation-v1',qualification_policy_frozen=True,
        research_only=True,order_authority=False,paper_trades=0,signing_authority=False,
        submission_authority=False,scout_lane_active=False,fomo_active=False,dlmm_enabled=False,
        discovery_seconds=DISCOVERY_SECONDS,followup_seconds=FOLLOWUP_SECONDS,
        natural_sample_budget=NATURAL_BUDGET,natural_slot_seconds=NATURAL_SLOT_SECONDS,
        priority_budget=PRIORITY_BUDGET,priority_slot_seconds=PRIORITY_SLOT_SECONDS,
        extra_evidence_budget=EXTRA_EVIDENCE_BUDGET,
        extra_evidence_per_slot=EXTRA_EVIDENCE_PER_SLOT,
        subclass_research_protocol=subclass_research_protocol(),
        frozen_entry_thresholds=dict(CURRENT_THRESHOLDS),entry_thresholds_unchanged=True,
        outcome_horizons=list(DEFAULT_HORIZONS),started=started,limitations=[],
        natural_results=[],extra_evidence_results=[],cohort_trackers=[],
    )
    _save(report)

    url=os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
    evidence=EvidenceSessions(url)
    tape=PumpTape();stop=threading.Event();ready=threading.Event();stream=PumpLogStream(url,tape)
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True);thread.start()

    discovered=set();slot_rows=defaultdict(list);stream_rejections=Counter()
    high_density_seen=set();natural_slots=set();natural_results=[]
    extra_evidence_results=[];extra_evidence_attempted=0
    trackers=[];trackers_by_mint=defaultdict(list)
    cursor=None;coverage_ready_at=None;last_priority_flush=-1
    discovery_finished_at=None

    def add_tracker(row):
        trackers.append(row);trackers_by_mint[row['mint']].append(row)

    def process_priority_slot(slot,now):
        nonlocal extra_evidence_attempted
        rows=slot_rows.pop(slot,[])
        refreshed=[]
        for candidate,_old in rows:
            metric=stream_feasibility(candidate,tape,now)
            if metric.possible:
                refreshed.append((candidate,metric))
            else:
                stream_rejections[metric.guaranteed_rejection]+=1
                if metric.guaranteed_rejection=='evidence_capacity' and candidate['mint'] not in high_density_seen:
                    high_density_seen.add(candidate['mint'])
                    num,den,_origin=_event_baseline(candidate)
                    window=tape.window(candidate['mint'],now)
                    add_tracker(new_tracker(candidate['mint'],now,num,den,['high_density'],
                                            nomination_id=candidate['nomination']['id'],
                                            metadata={'evidence_events':metric.evidence_events,
                                                      'source':'priority_slot_recheck',
                                                      'high_density_features':high_density_features(window,now)}))
        chosen=choose_slot_candidate(refreshed)
        chosen_id=None if chosen is None else chosen[0]['nomination']['id']
        unselected=[]
        for candidate,metric in refreshed:
            num,den,origin=_event_baseline(candidate)
            selected=candidate['nomination']['id']==chosen_id
            cohort='priority_selected' if selected else 'feasible_unpreflighted'
            add_tracker(new_tracker(
                candidate['mint'],origin,num,den,[cohort],
                nomination_id=candidate['nomination']['id'],
                metadata={'stream_feasibility':metric.to_dict(),'priority_slot':slot}))
            if not selected:
                unselected.append((candidate,metric))
        if extra_evidence_attempted<EXTRA_EVIDENCE_BUDGET and unselected:
            ranked=sorted(unselected,key=lambda row:row[1].priority_key())
            remaining=max(0,EXTRA_EVIDENCE_BUDGET-extra_evidence_attempted)
            for candidate,metric in ranked[:min(EXTRA_EVIDENCE_PER_SLOT,remaining)]:
                extra_evidence_attempted+=1
                result=_evaluate_extra_preflight(candidate,metric,tape,evidence,authority)
                result['priority_slot']=slot
                result['extra_evidence_sequence']=extra_evidence_attempted
                extra_evidence_results.append(result)
                if result.get('two_buyer_sole_near_miss'):
                    num,den,origin=_event_baseline(candidate)
                    add_tracker(new_tracker(
                        candidate['mint'],origin,num,den,['two_buyer_sole_near_miss_expanded'],
                        nomination_id=candidate['nomination']['id'],
                        metadata={'priority_slot':slot,'source':'expanded_full_evidence'}))

    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'outcomes.db'),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        engine=Engine(store,[]);authority=MarketNativeAuthority(engine)
        try:
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            else:
                hard_deadline=time.monotonic()+WINDOW_SECONDS+DISCOVERY_SECONDS+FOLLOWUP_SECONDS
                while time.monotonic()<hard_deadline:
                    now=int(time.time())
                    if stream.error_kind:
                        report['limitations'].append('stream_continuity_lost')
                        break
                    if not tape.covered(now):
                        if discovery_finished_at is None:
                            cursor=None;coverage_ready_at=None
                        stop.wait(0.25);continue
                    if cursor is None:
                        cursor=tape.latest_sequence();coverage_ready_at=now
                        report['coverage_ready_at']=now
                        stop.wait(0.25);continue

                    fresh,cursor=tape.events_since(cursor)
                    for event in fresh:
                        for tracker in trackers_by_mint.get(event.get('mint'),()):
                            try: observe_trade(tracker,event)
                            except (ValueError,KeyError,TypeError): pass

                    if discovery_finished_at is None:
                        elapsed=now-int(coverage_ready_at)
                        priority_slot=max(0,elapsed//PRIORITY_SLOT_SECONDS)
                        while last_priority_flush<priority_slot-1:
                            last_priority_flush+=1
                            process_priority_slot(last_priority_flush,now)

                        if fresh:
                            for mint in {e.get('mint') for e in fresh if e.get('mint')}:
                                if mint in high_density_seen:
                                    continue
                                window=tape.window(mint,now)
                                if len(window)>100:
                                    high_density_seen.add(mint)
                                    base=max(window,key=lambda e:(e['market_time'],e['slot'],e.get('index',0)))
                                    add_tracker(new_tracker(
                                        mint,now,base['amount'],base['tokens'],['high_density'],
                                        metadata={'evidence_events':len(window),'source':'finalized_stream',
                                                  'high_density_features':high_density_features(window,now)}))

                            native=discover_market_native(fresh,tape,now,discovered)
                            for candidate in native:
                                if len(discovered)>=MAX_DISCOVERED:
                                    report['limitations'].append('discovery_identity_capacity_exhausted')
                                    break
                                discovered.add(candidate['mint'])
                                metric=stream_feasibility(candidate,tape,now)
                                if metric.possible:
                                    slot_rows[priority_slot].append((candidate,metric))
                                else:
                                    stream_rejections[metric.guaranteed_rejection]+=1

                            natural_slot=max(0,elapsed//NATURAL_SLOT_SECONDS)
                            if natural_slot not in natural_slots and native and len(natural_results)<NATURAL_BUDGET:
                                chosen=min(native,key=lambda c:(
                                    int(c['nomination']['market_time']),c['nomination']['id'],c['mint']))
                                natural_slots.add(natural_slot)
                                row,tracker=_evaluate_natural(chosen,tape,evidence,authority,engine)
                                row['sample_slot']=natural_slot
                                row['tracker_index']=len(trackers)
                                natural_results.append(row);add_tracker(tracker)

                        if elapsed>=DISCOVERY_SECONDS:
                            for slot in sorted(list(slot_rows)):
                                process_priority_slot(slot,now)
                            discovery_finished_at=now
                            report['discovery_finished_at']=now
                    elif now-discovery_finished_at>=FOLLOWUP_SECONDS:
                        break

                    if now % 15 == 0:
                        report.update(
                            current_time=now,discovered=len(discovered),
                            natural_results=natural_results,
                            natural_complete=sum(r.get('evidence_stage')=='complete' for r in natural_results),
                            high_density_candidates=len(high_density_seen),
                            stream_guaranteed_rejections=dict(stream_rejections),
                            tracked_candidates=len(trackers),extra_evidence_attempted=extra_evidence_attempted,
                            extra_evidence_results=extra_evidence_results,
                        )
                        _save(report)
                    stop.wait(0.25)
        finally:
            ended=int(time.time());stop.set();thread.join(timeout=3);evidence.finish()
            for row in natural_results:
                idx=row.get('tracker_index')
                if isinstance(idx,int) and 0<=idx<len(trackers):
                    row['future_outcomes']=trackers[idx]
            report.update(
                ended=ended,discovered=len(discovered),natural_results=natural_results,
                extra_evidence_results=extra_evidence_results,
                extra_evidence_attempted=extra_evidence_attempted,
                extra_preflight_complete=sum(r.get('preflight_complete') for r in extra_evidence_results),
                extra_full_evidence_complete=sum(r.get('full_evidence_complete') for r in extra_evidence_results),
                extra_qualified=sum(r.get('actual_reason')=='qualified' for r in extra_evidence_results),
                expanded_two_buyer_full_evidence=sum(
                    r.get('full_evidence_complete') and r.get('two_buyer_research_candidate')
                    for r in extra_evidence_results),
                expanded_two_buyer_sole_near_misses=sum(
                    r.get('two_buyer_sole_near_miss') for r in extra_evidence_results),
                natural_complete=sum(r.get('evidence_stage')=='complete' for r in natural_results),
                natural_sample_ready=sum(r.get('evidence_stage')=='complete' for r in natural_results)>=50,
                high_density_candidates=len(high_density_seen),
                stream_guaranteed_rejections=dict(stream_rejections),
                cohort_trackers=trackers,
                cohort_summary=summarize_trackers(trackers),
                liquidity_counterfactual=summarize_liquidity_counterfactual(natural_results),
                post_exit_tail_summary=summarize_post_exit_tail(natural_results),
                two_buyer_sole_near_miss_summary=summarize_two_buyer_near_misses(natural_results),
                provider_sessions=evidence.sessions,
                stream=tape.status(ended),stream_error_kind=stream.error_kind,
                future_labels_used_for_selection=False,automatic_threshold_change=False,
            )
            _save(report);store.close()

    print(json.dumps(dict(
        discovered=report['discovered'],natural_complete=report['natural_complete'],
        natural_sample_ready=report['natural_sample_ready'],
        high_density_candidates=report['high_density_candidates'],
        extra_evidence_attempted=report['extra_evidence_attempted'],
        extra_preflight_complete=report['extra_preflight_complete'],
        extra_full_evidence_complete=report['extra_full_evidence_complete'],
        extra_qualified=report['extra_qualified'],
        cohort_counts={k:v['count'] for k,v in report['cohort_summary'].items()},
        limitations=report['limitations'],
    ),sort_keys=True))


if __name__=='__main__':
    main()
