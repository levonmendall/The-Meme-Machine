"""Prospective paired shadow comparison: scout-gated vs market-native discovery.

One finalized Pump stream feeds both lanes over the same wall-clock period. The live
strategy remains untouched. Both lanes use unchanged Engine.qualify; the market-native
lane selects mints from activity only and uses a real fresh buy solely as the required
nomination anchor. Qualified opportunities receive isolated exact paper lifecycles
using existing Pump/PumpSwap fill, monitoring and exit code. No production order,
signing, submission, deployment or live-money authority exists here.
"""
from __future__ import annotations

import copy
import json
import os
import statistics
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

from meme_machine import pump
from meme_machine.__main__ import _monitor_existing
from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import Engine
from meme_machine.market_native_shadow import classify_buckets, discover_market_native
from meme_machine.postgrad import PostGraduationAdapter
from meme_machine.solana_read_rpc import discovery_ws_url, new_rpc, primary_rpc_url
from meme_machine.provider import PumpAdapter, Unavailable
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.research import qualification_vector
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

WATCHLIST=Path('evidence/unvalidated_seed_watchlist.json')
REPORT=Path(os.environ.get('MM_DISCOVERY_COMPARE_REPORT','discovery-lane-comparison.json'))
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-17 paired shadow discovery comparison; not performance continuity'
DISCOVERY_SECONDS=max(120,min(int(os.environ.get('MM_DISCOVERY_COMPARE_SECONDS','3300')),3300))
POST_SECONDS=max(120,min(int(os.environ.get('MM_DISCOVERY_COMPARE_POST_SECONDS','1000')),1000))
MAX_PER_LANE=max(1,min(int(os.environ.get('MM_DISCOVERY_COMPARE_MAX_PER_LANE','20')),30))
POLL_SECONDS=1


def _save(report):
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))


def _watchlist():
    watch=json.loads(WATCHLIST.read_text())
    admitted=int(watch.get('created_at_unix',0))
    records=[dict(wallet=x['wallet'],eligible_after=int(x.get('eligible_after_unix',admitted)),source='watchlist')
             for x in watch['seeds']]
    return records,[x['wallet'] for x in records],{x['wallet']:x['eligible_after'] for x in records}


def _eligible_scout(events,admission):
    return [e for e in events if e['wallet'] in admission and
            int(e['market_time'])>int(admission[e['wallet']])]


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


def _rpc_delta(before,after):
    return {k:int(after.get(k,0))-int(before.get(k,0)) for k in before}


def _evaluate(lane,nomination,tape,adapter,reader,scout_engine,workdir,index,first_activity):
    result=dict(
        lane=lane,mint=nomination['mint'],nomination_id=nomination['id'],
        nomination_market_time=int(nomination['market_time']),
        first_meaningful_activity=int(first_activity),complete=False,
    )
    before=_rpc_snapshot(adapter.rpc,reader)
    observed=int(time.time())
    try:
        if not tape.covered(observed):
            raise Unavailable('incomplete_market_window')
        initial=adapter.snapshot(nomination['mint'],observed,priority=True)
        if not tape.covered(int(time.time())):
            raise Unavailable('incomplete_market_window')
        concentration,meta=reader.read(nomination['mint'],initial,priority=True)
        final=adapter.snapshot(nomination['mint'],int(time.time()),priority=True)
        qualified_at=int(time.time())
        if not tape.covered(qualified_at):
            raise Unavailable('incomplete_market_window')
        market=tape.window(nomination['mint'],qualified_at,max_slot=final['slot'])
        evidence=dict(snapshot=final,events=market,covered=True,concentration_bps=concentration)

        if lane=='scout':
            vector=qualification_vector(scout_engine,nomination,evidence,qualified_at)
        else:
            # Discovery did not use this wallet identity. A real triggering buy is
            # used only because unchanged Engine.qualify requires a nomination seed
            # and excludes that lead wallet from independent-demand corroboration.
            store=Store(str(Path(workdir)/f'market-qual-{index}.db'),'prospective',
                        GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
            try:
                engine=Engine(store,[nomination['wallet']])
                vector=qualification_vector(engine,nomination,evidence,qualified_at)
            finally:
                store.close()

        curve=pump.curve(final['accounts'][0])
        result.update(
            complete=True,reason=vector['actual_reason'],qualification_vector=vector,
            qualified_at=qualified_at,
            seconds_first_activity_to_qualification=max(0,qualified_at-int(first_activity)),
            evidence_events=len(market),concentration_bps=concentration,
            concentration_source=meta.get('source'),real_sol_lamports=curve.real_sol,
            snapshot_slot=final['slot'],evidence=evidence,
        )
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        result.update(reason='unavailable_executable_evidence',limitation=str(exc))
    after=_rpc_snapshot(adapter.rpc,reader)
    result['rpc_delta']=_rpc_delta(before,after)
    return result


def _start_lifecycle(lane,row,seeds,adapter,postgrad_adapter,workdir,index):
    nomination=copy.deepcopy(row['nomination'])
    evidence=copy.deepcopy(row['evidence'])
    path=Path(workdir)/f'lifecycle-{lane}-{index}.db'
    store=Store(str(path),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
    lifecycle_seeds=list(seeds) if lane=='scout' else [nomination['wallet']]
    engine=Engine(store,lifecycle_seeds)
    reason=engine.consider(nomination,evidence,int(row['qualified_at']))
    if reason!='qualified':
        store.close()
        return None
    runtime=PumpSwapPaperRuntime(store,postgrad_adapter)
    return dict(
        lane=lane,mint=nomination['mint'],oid=nomination['id'],store=store,engine=engine,
        runtime=runtime,adapter=adapter,started=int(row['qualified_at']),
        entered=False,pump_entry=False,graduated=False,settled=False,cancelled=False,
        mfe_bps=None,mae_bps=None,terminal=None,
    )


def _service_lifecycle(item,now):
    if item['terminal'] is not None:
        return
    _monitor_existing(item['engine'],item['adapter'],now,pumpswap_runtime=item['runtime'])
    store=item['store'];oid=item['oid'];mint=item['mint']
    order=store.state['orders'].get(oid) or {}
    position=store.state['positions'].get(mint)
    fill=order.get('fill') or {}
    if fill:
        item['entered']=True
        item['pump_entry']=fill.get('surface')!='pumpswap'
        item['entry_surface']=fill.get('surface','pump')
        item['entry_time']=fill.get('time')
    if (position and position.get('postgrad_handoff')) or order.get('postgrad_handoff'):
        item['graduated']=True
    if position and position.get('mark') is not None and int(position.get('basis',0))>0:
        bps=(int(position['mark'])-int(position['basis']))*10000//int(position['basis'])
        item['mfe_bps']=bps if item['mfe_bps'] is None else max(item['mfe_bps'],bps)
        item['mae_bps']=bps if item['mae_bps'] is None else min(item['mae_bps'],bps)
    if order.get('exit') and position is None:
        exit_record=order['exit']
        item.update(
            settled=True,terminal='settled',exit_reason=exit_record.get('reason'),
            exit_surface=exit_record.get('surface','pump'),
            realized_lamports=int(exit_record.get('realized',0)),exit_time=exit_record.get('time'),
        )
        return
    if order.get('status')=='cancelled' and position is None:
        item.update(cancelled=True,terminal='entry_cancelled',cancel_reason=order.get('reason'))


def _lifecycle_public(item):
    keys=(
        'lane','mint','oid','started','entered','pump_entry','entry_surface','entry_time',
        'graduated','settled','cancelled','terminal','exit_reason','exit_surface',
        'realized_lamports','exit_time','mfe_bps','mae_bps','cancel_reason',
    )
    return {k:item.get(k) for k in keys if k in item}


def _lane_summary(lane,rows,lifecycles,discovered_count):
    lane_rows=[r for r in rows if r['lane']==lane]
    complete=[r for r in lane_rows if r.get('complete')]
    qualified=[r for r in complete if r.get('reason')=='qualified']
    reject=Counter(r.get('reason','unknown') for r in complete if r.get('reason')!='qualified')
    seconds=[r['seconds_first_activity_to_qualification'] for r in qualified]
    lane_life=[x for x in lifecycles if x['lane']==lane]
    entries=[x for x in lane_life if x.get('entered')]
    settled=[x for x in lane_life if x.get('settled')]
    rpc=Counter()
    for row in lane_rows:
        rpc.update(row.get('rpc_delta',{}))
    return dict(
        discovered=discovered_count,evaluated=len(lane_rows),complete=len(complete),
        qualified=len(qualified),qualification_rate=None if not complete else len(qualified)/len(complete),
        rejection_distribution=dict(sorted(reject.items())),
        first_activity_to_qualification_seconds=dict(
            values=seconds,
            mean=None if not seconds else statistics.mean(seconds),
            median=None if not seconds else statistics.median(seconds),
        ),
        pump_entry_opportunities=sum(bool(x.get('pump_entry')) for x in entries),
        entries=len(entries),graduated_entries=sum(bool(x.get('graduated')) for x in entries),
        graduation_rate=None if not entries else sum(bool(x.get('graduated')) for x in entries)/len(entries),
        settled=len(settled),paper_realized_lamports=sum(int(x.get('realized_lamports',0)) for x in settled),
        maximum_favorable_excursion_bps=[x.get('mfe_bps') for x in lane_life if x.get('mfe_bps') is not None],
        maximum_adverse_excursion_bps=[x.get('mae_bps') for x in lane_life if x.get('mae_bps') is not None],
        evidence_rpc=dict(rpc),
        evidence_rpc_logical_per_qualified=None if not qualified else rpc.get('primary_logical',0)/len(qualified),
        paper_pnl_scope='isolated exact 5% starter lifecycle per qualified opportunity; no cross-candidate capital competition',
    )


def main():
    records,seeds,admission=_watchlist()
    started=int(time.time())
    report=dict(
        kind='paired_scout_vs_market_native_shadow',network='solana-mainnet',protocol='pump.fun',
        qualification_policy='continuation-v1',qualification_policy_frozen=True,
        scout_lane_unchanged=True,market_native_order_authority=False,
        market_native_trigger='fresh finalized buy + >=3 events + >=3 distinct non-system wallets in covered 60-second window',
        trigger_optimized_from_outcomes=False,
        discovery_seconds=DISCOVERY_SECONDS,post_seconds=POST_SECONDS,max_evidence_per_lane=MAX_PER_LANE,
        paper_only=True,signing_available=False,transaction_submission_available=False,
        shared_portfolio_performance_claim=False,started=started,rows=[],lifecycles=[],limitations=[],
    )
    _save(report)

    url=primary_rpc_url()
    rpc=new_rpc(limit=240)
    adapter=PumpAdapter(rpc)
    reader=ConcentrationReader(rpc,secondary_url=os.environ.get('MM_SOLANA_CONCENTRATION_RPC_URL','').strip())
    postgrad_adapter=PostGraduationAdapter(rpc,scan_rpc=object())
    tape=PumpTape();stop=threading.Event();ready=threading.Event();stream=PumpLogStream(url,tape,ws_url=discovery_ws_url())
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True);thread.start()

    with tempfile.TemporaryDirectory() as td:
        scout_store=Store(str(Path(td)/'scout-shadow.db'),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        scout_engine=Engine(scout_store,seeds)
        cursor=None;coverage_ready_at=None
        scout_discovered={};market_discovered={};observed={}
        attempted={'scout':set(),'market_native':set()}
        rows=[];lifecycles=[];life_index=0;eval_index=0
        try:
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            else:
                discovery_deadline=time.monotonic()+WINDOW_SECONDS+DISCOVERY_SECONDS
                absolute_deadline=discovery_deadline+POST_SECONDS
                while time.monotonic()<absolute_deadline:
                    now=int(time.time())
                    for item in lifecycles:
                        _service_lifecycle(item,now)
                    if stream.error_kind:
                        report['limitations'].append('stream_continuity_lost')
                        break
                    if time.monotonic()>=discovery_deadline:
                        if all(x.get('terminal') is not None for x in lifecycles):
                            break
                        stop.wait(POLL_SECONDS);continue
                    if not tape.covered(now):
                        cursor=None;stop.wait(0.25);continue
                    if cursor is None:
                        cursor=tape.latest_sequence();coverage_ready_at=now
                        stop.wait(0.25);continue
                    fresh,cursor=tape.events_since(cursor)
                    if not fresh:
                        stop.wait(0.25);continue

                    for e in fresh:
                        c=observed.setdefault(e['mint'],dict(events=0,buys=0,first_market_time=int(e['market_time']),last_market_time=int(e['market_time']),wallets=set()))
                        c['events']+=1;c['buys']+=1 if e.get('buy') else 0
                        c['first_market_time']=min(c['first_market_time'],int(e['market_time']))
                        c['last_market_time']=max(c['last_market_time'],int(e['market_time']))
                        c['wallets'].add(e['wallet'])

                    eligible=_eligible_scout(fresh,admission)
                    scout_found=scout_engine.scout(eligible,now) if eligible else []
                    for nomination in sorted(scout_found,key=lambda n:(n['market_time'],n['id'])):
                        mint=nomination['mint']
                        scout_discovered.setdefault(mint,dict(nomination=dict(nomination),discovery_time=now))
                        if mint in attempted['scout'] or len(attempted['scout'])>=MAX_PER_LANE:
                            continue
                        attempted['scout'].add(mint);eval_index+=1
                        first=observed.get(mint,{}).get('first_market_time',nomination['market_time'])
                        row=_evaluate('scout',nomination,tape,adapter,reader,scout_engine,td,eval_index,first)
                        row['nomination']=dict(nomination);rows.append(row)
                        if row.get('reason')=='qualified':
                            life_index+=1
                            life=_start_lifecycle('scout',row,seeds,adapter,postgrad_adapter,td,life_index)
                            if life:lifecycles.append(life)

                    native=discover_market_native(fresh,tape,now,set(market_discovered))
                    for candidate in native:
                        mint=candidate['mint'];market_discovered[mint]=candidate
                        if mint in attempted['market_native'] or len(attempted['market_native'])>=MAX_PER_LANE:
                            continue
                        attempted['market_native'].add(mint);eval_index+=1
                        nomination=candidate['nomination']
                        first=observed.get(mint,{}).get('first_market_time',candidate['first_window_market_time'])
                        row=_evaluate('market_native',nomination,tape,adapter,reader,scout_engine,td,eval_index,first)
                        row.update(nomination=dict(nomination),discovery_trigger=candidate['trigger'],
                                   discovery_window_events=candidate['window_events'],
                                   discovery_distinct_wallets=candidate['distinct_non_system_wallets'])
                        rows.append(row)
                        if row.get('reason')=='qualified':
                            life_index+=1
                            life=_start_lifecycle('market_native',row,seeds,adapter,postgrad_adapter,td,life_index)
                            if life:lifecycles.append(life)

                    report.update(
                        current_time=now,coverage_ready_at=coverage_ready_at,
                        observed_mints=len(observed),scout_discovered=len(scout_discovered),
                        market_native_discovered=len(market_discovered),rows=[{k:v for k,v in r.items() if k!='evidence'} for r in rows],
                        lifecycles=[_lifecycle_public(x) for x in lifecycles],stream=tape.status(now),
                    )
                    _save(report)
                    stop.wait(0.25)
        finally:
            now=int(time.time())
            for item in lifecycles:
                _service_lifecycle(item,now)
            buckets=classify_buckets(scout_discovered,market_discovered,observed)
            for row in rows:
                mint=row['mint']
                row['bucket']=('both' if mint in scout_discovered and mint in market_discovered else
                               'scout_only' if mint in scout_discovered else
                               'market_native_only' if mint in market_discovered else
                               'neither_pending_retrospective_review')
            census=sorted((dict(mint=m,events=v['events'],buys=v['buys'],distinct_wallets=len(v['wallets']),
                                      first_market_time=v['first_market_time'],last_market_time=v['last_market_time'])
                           for m,v in observed.items()),key=lambda x:(-x['events'],x['mint']))
            report.update(
                ended=now,stream=tape.status(now),stream_error_kind=stream.error_kind,
                bucket_counts={k:len(v) for k,v in buckets.items()},buckets=buckets,
                retrospective_review_queue=census[:200],
                rows=[{k:v for k,v in r.items() if k!='evidence'} for r in rows],
                lifecycles=[_lifecycle_public(x) for x in lifecycles],
                scout=_lane_summary('scout',rows,lifecycles,len(scout_discovered)),
                market_native=_lane_summary('market_native',rows,lifecycles,len(market_discovered)),
                provider=dict(logical_requests=rpc.calls,transport_requests=rpc.http_requests,
                              failures=rpc.failures,retries=rpc.retries,failure_kinds=rpc.failure_kinds),
                concentration_retrieval=reader.status(),
                provider_spend_usd=0 if url=='https://api.mainnet-beta.solana.com' else None,
                infrastructure_spend_usd=0,
            )
            if len(scout_discovered)>len(attempted['scout']):
                report['limitations'].append('scout_evidence_budget_exhausted')
            if len(market_discovered)>len(attempted['market_native']):
                report['limitations'].append('market_native_evidence_budget_exhausted')
            _save(report)
            for item in lifecycles:
                item['store'].close()
            scout_store.close();stop.set();thread.join(timeout=3)

    print(json.dumps(dict(
        bucket_counts=report['bucket_counts'],scout=report['scout'],
        market_native=report['market_native'],limitations=report['limitations'],
        provider=report['provider'],
    ),sort_keys=True))


if __name__=='__main__':
    main()
