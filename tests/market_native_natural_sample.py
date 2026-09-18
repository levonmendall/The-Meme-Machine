"""Time-distributed natural market-native qualification sample.

This collector exists only for later human review of frozen continuation-v1. It is
separate from the active evidence prioritizer on purpose: a trading prioritizer keeps
stronger policy-feasible candidates, which would bias threshold research.

Sampling rule: after a complete 60-second finalized Pump stream warmup, divide the
observation period into fixed time slots and take the first newly discovered
market-native candidate in each slot. No wallet identity, policy margin, price result,
future outcome, Fomo signal, or scout signal affects selection. Every selected candidate
receives full point-in-time evidence, including concentration, but no order authority.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import Engine
from meme_machine.market_native_runtime import MarketNativeAuthority
from meme_machine.market_native_shadow import discover_market_native
from meme_machine.provider import RPC, PumpAdapter, Unavailable
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

REPORT=Path(os.environ.get('MM_MARKET_NATIVE_SAMPLE_REPORT','market-native-natural-sample.json'))
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-17 unbiased market-native natural sample; research only'
OBSERVE_SECONDS=max(120,min(int(os.environ.get('MM_MARKET_NATIVE_SAMPLE_SECONDS','3300')),3300))
SAMPLE_BUDGET=max(1,min(int(os.environ.get('MM_MARKET_NATIVE_SAMPLE_BUDGET','20')),20))
SLOT_SECONDS=max(1,math.ceil(OBSERVE_SECONDS/SAMPLE_BUDGET))
MAX_DISCOVERED=5_000


def _save(report):
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))


def _evaluate(candidate,tape,adapter,reader,authority):
    nomination=dict(candidate['nomination'])
    nomination['discovery_source']='market_native'
    row=dict(
        mint=candidate['mint'],nomination_id=nomination['id'],
        natural_market_native_sample=True,evidence_stage='started',
        discovery_time=int(candidate['discovery_time']),
        nomination_market_time=int(nomination['market_time']),
        sampling_rule='first_new_market_native_candidate_in_fixed_time_slot',
        research_only=True,order_authority=False,
    )
    try:
        now=int(time.time())
        if not tape.covered(now):
            raise Unavailable('incomplete_market_window')
        initial=adapter.snapshot(candidate['mint'],now,priority=True)
        concentration,meta=reader.read(candidate['mint'],initial,priority=True)
        final=adapter.snapshot(candidate['mint'],int(time.time()),priority=True)
        qualified_at=int(time.time())
        if not tape.covered(qualified_at):
            raise Unavailable('incomplete_market_window')
        events=tape.window(candidate['mint'],qualified_at,max_slot=final['slot'])
        evidence=dict(snapshot=final,events=events,covered=True,
                      concentration_bps=concentration)
        vector=authority.vector(nomination,evidence,qualified_at)
        row.update(
            evidence_stage='complete',actual_reason=vector['actual_reason'],
            qualification_vector=vector,qualified_at=qualified_at,
            evidence_events=len(events),concentration_bps=concentration,
            concentration_source=meta.get('source'),
        )
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        row.update(evidence_stage='incomplete',actual_reason='unavailable_executable_evidence',
                   limitation=str(exc))
    return row


def main():
    started=int(time.time())
    report=dict(
        kind='market_native_natural_sample',network='solana-mainnet',protocol='pump.fun',
        qualification_policy='continuation-v1',qualification_policy_frozen=True,
        sampling_rule='first newly discovered market-native candidate per fixed time slot',
        sampling_uses_policy_score=False,sampling_uses_wallet_identity=False,
        sampling_uses_outcomes=False,scout_lane_active=False,fomo_active=False,
        research_only=True,order_authority=False,paper_trades=0,
        observe_seconds=OBSERVE_SECONDS,sample_budget=SAMPLE_BUDGET,
        slot_seconds=SLOT_SECONDS,started=started,results=[],limitations=[],
    )
    _save(report)

    url=os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
    rpc=RPC(url,limit=160)
    adapter=PumpAdapter(rpc)
    reader=ConcentrationReader(rpc,secondary_url=os.environ.get('MM_SOLANA_CONCENTRATION_RPC_URL','').strip())
    tape=PumpTape();stop=threading.Event();ready=threading.Event();stream=PumpLogStream(url,tape)
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True);thread.start()

    discovered=set();sampled_slots=set();cursor=None;coverage_ready_at=None
    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'sample.db'),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        engine=Engine(store,[])
        authority=MarketNativeAuthority(engine)
        try:
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            else:
                deadline=time.monotonic()+WINDOW_SECONDS+OBSERVE_SECONDS
                while time.monotonic()<deadline and len(report['results'])<SAMPLE_BUDGET:
                    now=int(time.time())
                    if stream.error_kind:
                        report['limitations'].append('stream_continuity_lost')
                        break
                    if not tape.covered(now):
                        cursor=None;coverage_ready_at=None
                        discovered.clear();sampled_slots.clear()
                        stop.wait(0.25);continue
                    if cursor is None:
                        cursor=tape.latest_sequence();coverage_ready_at=now
                        report['coverage_ready_at']=now
                        stop.wait(0.25);continue
                    fresh,cursor=tape.events_since(cursor)
                    if not fresh:
                        stop.wait(0.25);continue
                    native=discover_market_native(fresh,tape,now,discovered)
                    for candidate in native:
                        if len(discovered)>=MAX_DISCOVERED:
                            report['limitations'].append('discovery_identity_capacity_exhausted')
                            break
                        discovered.add(candidate['mint'])
                    if coverage_ready_at is None:
                        continue
                    slot=max(0,(now-coverage_ready_at)//SLOT_SECONDS)
                    if slot not in sampled_slots and native:
                        chosen=min(native,key=lambda c:(
                            int(c['nomination']['market_time']),c['nomination']['id'],c['mint']))
                        chosen=dict(chosen,discovery_time=now)
                        sampled_slots.add(slot)
                        row=_evaluate(chosen,tape,adapter,reader,authority)
                        row['sample_slot']=slot
                        report['results'].append(row)
                        report.update(current_time=int(time.time()),discovered=len(discovered),
                                      complete=sum(r.get('evidence_stage')=='complete' for r in report['results']))
                        _save(report)
                    stop.wait(0.25)
        finally:
            ended=int(time.time())
            stop.set();thread.join(timeout=3)
            report.update(
                ended=ended,discovered=len(discovered),
                complete=sum(r.get('evidence_stage')=='complete' for r in report['results']),
                sampled=len(report['results']),stream=tape.status(ended),
                stream_error_kind=stream.error_kind,
                provider=dict(logical_requests=rpc.calls,transport_requests=rpc.http_requests,
                              failures=rpc.failures,retries=rpc.retries,
                              failure_kinds=rpc.failure_kinds),
                concentration_retrieval=reader.status(),
                provider_spend_usd=0 if url=='https://api.mainnet-beta.solana.com' else None,
                infrastructure_spend_usd=0,
                orders=len(store.state['orders']),positions=len(store.state['positions']),
                wallets=len(store.state['wallets']),
            )
            _save(report);store.close()
    print(json.dumps(dict(
        sampled=report['sampled'],complete=report['complete'],discovered=report['discovered'],
        limitations=report['limitations'],provider=report['provider'],
    ),sort_keys=True))


if __name__=='__main__':
    main()
